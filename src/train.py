import argparse
import os

import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, get_linear_schedule_with_warmup

try:
    from src.model import PhoBERT_CRF
    from src.dataset import MedicalNERDataset
    from src.labels import LABELS, LABEL2ID
except ImportError:
    from model import PhoBERT_CRF
    from dataset import MedicalNERDataset
    from labels import LABELS, LABEL2ID

# Resolve paths relative to the project root so the script works from any CWD.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
TRAIN_FILE = os.path.join(ROOT_DIR, "data", "train.txt")
MODEL_DIR = os.path.join(ROOT_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "pho_bert_crf_medical.pth")

# Config
MODEL_NAME = "vinai/phobert-base-v2"
MAX_LEN = 256
BATCH_SIZE = 16
DEFAULT_EPOCHS = 4
LR = 2e-5


def get_device():
    """Pick the best available device: CUDA (NVIDIA) > MPS (Apple Silicon) > CPU."""
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def parse_args():
    parser = argparse.ArgumentParser(description="Train PhoBERT-CRF medical NER model.")
    parser.add_argument(
        "-e",
        "--epochs",
        type=int,
        default=DEFAULT_EPOCHS,
        help=f"Number of training epochs (default: {DEFAULT_EPOCHS}).",
    )
    parser.add_argument(
        "--from-scratch",
        action="store_true",
        help="Ignore existing checkpoint and train a new model.",
    )
    parser.add_argument(
        "--checkpoint",
        default=MODEL_PATH,
        help=f"Checkpoint to resume from if it exists (default: {MODEL_PATH}).",
    )
    parser.add_argument(
        "--data",
        default=TRAIN_FILE,
        help=f"BIO training file (default: {TRAIN_FILE}). "
             f"Build one with scripts/prepare_training_data.py.",
    )
    return parser.parse_args()


def load_checkpoint(model, checkpoint_path, device):
    """Load fine-tuned weights if the checkpoint file exists."""
    if not os.path.isfile(checkpoint_path):
        print(f"No checkpoint found at {checkpoint_path}; starting from PhoBERT base.")
        return False

    state = torch.load(checkpoint_path, map_location=device)
    try:
        model.load_state_dict(state)
    except RuntimeError as err:
        # The classifier and CRF are sized by len(LABELS), so adding a label makes every
        # older checkpoint unloadable. Say so plainly instead of re-printing shape lists.
        raise SystemExit(
            f"Checkpoint {checkpoint_path} was trained with a different label set than "
            f"src/labels.py defines now ({len(LABELS)} labels). Train with "
            f"--from-scratch, or point --checkpoint at a matching file.\n  {err}"
        ) from err
    print(f"Loaded checkpoint: {checkpoint_path}")
    return True


def main():
    args = parse_args()
    epochs = args.epochs
    device = torch.device(get_device())

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = PhoBERT_CRF(num_labels=len(LABELS))

    if not args.from_scratch:
        load_checkpoint(model, args.checkpoint, device)

    train_dataset = MedicalNERDataset(args.data, tokenizer, LABEL2ID, MAX_LEN)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    print(f"Training data: {args.data} ({len(train_dataset)} blocks)")

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=0,
        num_training_steps=len(train_loader) * epochs,
    )

    print(f"Using device: {device}")
    print(f"Training for {epochs} epoch(s)")
    model.to(device)

    for epoch in range(epochs):
        model.train()
        total_loss = 0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs["loss"]

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()

        print(f"Epoch {epoch+1}/{epochs}, Loss: {total_loss/len(train_loader):.4f}")

    # Save model
    os.makedirs(MODEL_DIR, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"Saved model to: {MODEL_PATH}")

# Usage: 
# python src/train.py --data data/train_generated.txt --from-scratch -e 6
# python src/train.py -e 4 --data data/train_generated.txt --checkpoint models/pho_bert_crf_medical.pth
if __name__ == "__main__":
    main()
