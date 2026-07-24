from torch.utils.data import Dataset
from underthesea import word_tokenize
from transformers import AutoTokenizer
import torch

class MedicalNERDataset(Dataset):
    def __init__(self, file_path, tokenizer, label2id, max_len=256):
        self.tokenizer = tokenizer
        self.max_len = max_len
        self.label2id = label2id
        self.examples = self.read_data(file_path)

    def read_data(self, file_path):
        examples = []
        with open(file_path, 'r', encoding='utf-8') as f:
            words, labels = [], []
            for line in f:
                line = line.strip()
                if line == "":
                    if words:
                        examples.append((words, labels))
                        words, labels = [], []
                else:
                    word, label = line.split()  # word label
                    words.append(word)
                    labels.append(label)
        return examples

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        words, labels = self.examples[idx]
        # Word-segmented text
        text = " ".join(words)
        
        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_len,
            padding="max_length",
            return_tensors="pt"
        )

        # Align labels (simple word-level alignment)
        label_ids = [self.label2id[label] for label in labels]
        # Pad or truncate label_ids
        label_ids = label_ids[:self.max_len]
        label_ids += [self.label2id["O"]] * (self.max_len - len(label_ids))
        
        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": torch.tensor(label_ids)
        }