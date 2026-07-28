import argparse
import os

import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, get_linear_schedule_with_warmup

try:
    from src.model import PhoBERT_CRF
    from src.dataset import MedicalNERDataset
except ImportError:
    from model import PhoBERT_CRF
    from dataset import MedicalNERDataset

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

# Labels (must match src/inference.py get_labels())
labels = ["O",
          "B-THUOC", "I-THUOC",
          "B-TRIEU_CHUNG", "I-TRIEU_CHUNG",
          "B-BENH", "I-BENH",
          "B-XET_NGHIEM", "I-XET_NGHIEM",
          "B-BENH_NHAN", "I-BENH_NHAN"]
label2id = {label: i for i, label in enumerate(labels)}
id2label = {i: label for label, i in label2id.items()}


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
    return parser.parse_args()


def main():
    args = parse_args()
    epochs = args.epochs

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = PhoBERT_CRF(num_labels=len(labels))

    train_dataset = MedicalNERDataset(TRAIN_FILE, tokenizer, label2id, MAX_LEN)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=0,
        num_training_steps=len(train_loader) * epochs,
    )

    device = torch.device(get_device())
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


if __name__ == "__main__":
    main()
