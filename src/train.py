import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, get_linear_schedule_with_warmup
from src.model import PhoBERT_CRF
from src.dataset import MedicalNERDataset
from seqeval.metrics import classification_report
import os

# Config
MODEL_NAME = "vinai/phobert-base"
MAX_LEN = 256
BATCH_SIZE = 16
EPOCHS = 10
LR = 2e-5

# Labels (tùy chỉnh theo annotation của bạn)
labels = ["O", "B-BENH_NHAN", "I-BENH_NHAN", "B-CHAN_DOAN", "I-CHAN_DOAN", 
          "B-XET_NGHIEM", "I-XET_NGHIEM", "B-DON_THUOC", "I-DON_THUOC", ...]
label2id = {label: i for i, label in enumerate(labels)}
id2label = {i: label for label, i in label2id.items()}

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = PhoBERT_CRF(num_labels=len(labels))

train_dataset = MedicalNERDataset("data/train.txt", tokenizer, label2id, MAX_LEN)
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=0, num_training_steps=len(train_loader)*EPOCHS)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)

for epoch in range(EPOCHS):
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
    
    print(f"Epoch {epoch+1}/{EPOCHS}, Loss: {total_loss/len(train_loader):.4f}")

# Save model
torch.save(model.state_dict(), "pho_bert_crf_medical.pth")