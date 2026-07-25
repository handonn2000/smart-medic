import torch
from torch.utils.data import Dataset

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
        o_id = self.label2id["O"]

        # Start with the <s>/CLS token (label O, ignored via attention mask).
        input_ids = [self.tokenizer.cls_token_id]
        label_ids = [o_id]

        # Tokenize word-by-word so each gold label aligns to its subwords.
        # The first subword keeps the original tag; continuations become I-*.
        for word, label in zip(words, labels):
            sub_ids = self.tokenizer.encode(word, add_special_tokens=False)
            if not sub_ids:
                sub_ids = [self.tokenizer.unk_token_id]

            input_ids.extend(sub_ids)
            label_ids.append(self.label2id.get(label, o_id))

            if len(sub_ids) > 1:
                cont_label = ("I-" + label[2:]) if label.startswith("B-") else label
                cont_id = self.label2id.get(cont_label, o_id)
                label_ids.extend([cont_id] * (len(sub_ids) - 1))

        # Append </s>/SEP token.
        input_ids.append(self.tokenizer.sep_token_id)
        label_ids.append(o_id)

        # Truncate (keeping input_ids and label_ids in lockstep).
        input_ids = input_ids[:self.max_len]
        label_ids = label_ids[:self.max_len]
        attention_mask = [1] * len(input_ids)

        # Pad to max_len (padding stays at the end, as CRF expects).
        pad_len = self.max_len - len(input_ids)
        input_ids += [self.tokenizer.pad_token_id] * pad_len
        label_ids += [o_id] * pad_len
        attention_mask += [0] * pad_len

        return {
            "input_ids": torch.tensor(input_ids),
            "attention_mask": torch.tensor(attention_mask),
            "labels": torch.tensor(label_ids),
        }