import json
import re

import torch
from underthesea import word_tokenize
from transformers import AutoTokenizer

try:
    from src.model import PhoBERT_CRF
except ImportError:
    from model import PhoBERT_CRF

from normalizer import MedicalNormalizer

class MedicalExtractor:
    def __init__(self, model_path="pho_bert_crf_medical.pth", device="cpu"):
        self.tokenizer = AutoTokenizer.from_pretrained("vinai/phobert-base")
        self.model = PhoBERT_CRF(num_labels=len(self.get_labels()))
        self.model.load_state_dict(torch.load(model_path, map_location=device))
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.id2label = {v: k for k, v in self.get_label2id().items()}
        self.normalizer = MedicalNormalizer()

    def get_labels(self):
        return ["O",
                "B-THUOC", "I-THUOC",
                "B-TRIEU_CHUNG", "I-TRIEU_CHUNG",
                "B-BENH", "I-BENH",
                "B-XET_NGHIEM", "I-XET_NGHIEM",
                "B-BENH_NHAN", "I-BENH_NHAN"]

    def get_label2id(self):
        return {label: i for i, label in enumerate(self.get_labels())}

    def extract(self, text: str):
        # Word segmentation
        segmented = word_tokenize(text, format="text")
        
        encoding = self.tokenizer(
            segmented,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding="max_length"
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(encoding["input_ids"], encoding["attention_mask"])
            predictions = outputs["predictions"][0]  # list of label ids

        tokens = self.tokenizer.convert_ids_to_tokens(encoding["input_ids"][0])
        
        entities = []
        current_tokens = None
        current_label = None

        for i, (token, pred_id) in enumerate(zip(tokens, predictions)):
            if token in ["<s>", "</s>", "<pad>"]:
                continue

            label = self.id2label[pred_id]

            if label.startswith("B-"):
                if current_tokens:
                    entities.append(
                        self._create_entity(current_tokens, current_label, text)
                    )
                current_tokens = [token.replace("▁", " ").strip()]
                current_label = label

            elif label.startswith("I-") and current_tokens:
                current_tokens.append(token.replace("▁", " ").strip())

            elif current_tokens:
                entities.append(
                    self._create_entity(current_tokens, current_label, text)
                )
                current_tokens = None
                current_label = None

        if current_tokens:
            entities.append(
                self._create_entity(current_tokens, current_label, text)
            )

        return self._post_process(entities, text)

    def _create_entity(self, tokens, label, original_text):
        text = " ".join(tokens).strip()
        # Approximate span in the original text
        match = re.search(re.escape(text[:30]), original_text)
        pos_start = match.start() if match else 0
        pos_end = pos_start + len(text)

        return {
            "text": text,
            "type": self._get_type(label),
            "candidates": [],
            "assertions": [],
            "position": [pos_start, pos_end],
        }

    def _get_type(self, label):
        type_map = {
            "B-THUOC": "THUỐC",
            "B-TRIEU_CHUNG": "TRIỆU_CHỨNG",
            "B-BENH": "BENH",
            "B-XET_NGHIEM": "XET_NGHIEM",
            "B-BENH_NHAN": "BENH_NHAN",
        }
        return type_map.get(label, "UNKNOWN")

    def _post_process(self, entities, text):
        """Thêm normalization và assertions"""
        for ent in entities:
            # Simple assertions detection
            if any(word in text.lower() for word in ["đã từng", "tiền sử", "history", "before"]):
                ent["assertions"].append("isHistorical")
            if any(word in text.lower() for word in ["không", "không có", "denied", "negative"]):
                ent["assertions"].append("negated")

            # Normalization candidates (demo)
            if ent["type"] == "THUỐC":
                ent["candidates"] = self.normalizer.normalize_drug(ent["text"])
            elif ent["type"] in ["BENH", "CHAN_DOAN"]:
                ent["candidates"] = self.normalizer.normalize_disease(ent["text"])
            elif ent["type"] == "XET_NGHIEM":
                ent["candidates"] = self.normalizer.normalize_test(ent["text"])
            else:
                ent["candidates"] = []

        return entities


# ==================== USAGE ====================
if __name__ == "__main__":
    extractor = MedicalExtractor(model_path="pho_bert_crf_medical.pth")
    
    text = """Bệnh nhân nam 55 tuổi, bị đau khớp gối phải, khớp gối có triệu chứng sưng, 
    bệnh nhân đã từng giải phẫu tái tạo dây chằng chéo trước khớp gối phải. 
    Bệnh nhân đã từng được chỉ định xét nghiệm Axit Uric máu với kết quả 519, 
    và được kê đơn thuốc Celecoxib 400mg, Esomeprazol 20mg, Febuxostat 40mg"""
    
    result = extractor.extract(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))