import torch
import torch.nn as nn
from transformers import AutoModel
from torchcrf import CRF

class PhoBERT_CRF(nn.Module):
    def __init__(self, num_labels, model_name="vinai/phobert-base-v2"):
        super().__init__()
        self.phobert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(self.phobert.config.hidden_size, num_labels)
        self.crf = CRF(num_labels, batch_first=True)

    def forward(self, input_ids, attention_mask, labels=None):
        outputs = self.phobert(input_ids=input_ids, attention_mask=attention_mask)
        sequence_output = outputs.last_hidden_state  # (batch, seq_len, hidden)
        
        sequence_output = self.dropout(sequence_output)
        emissions = self.classifier(sequence_output)  # (batch, seq_len, num_labels)

        if labels is not None:
            loss = -self.crf(emissions, labels, mask=attention_mask.bool())
            return {"loss": loss, "logits": emissions}
        else:
            prediction = self.crf.decode(emissions, mask=attention_mask.bool())
            return {"predictions": prediction}