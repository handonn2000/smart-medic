import json
import re

import torch
from underthesea import word_tokenize
from transformers import AutoTokenizer

try:
    from src.model import PhoBERT_CRF
    from src.labels import LABELS, ID2LABEL, ENTITY_TYPE_MAP
except ImportError:
    from model import PhoBERT_CRF
    from labels import LABELS, ID2LABEL, ENTITY_TYPE_MAP

from normalizer import MedicalNormalizer


def get_device():
    """Pick the best available device: CUDA (NVIDIA) > MPS (Apple Silicon) > CPU."""
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


class MedicalExtractor:
    MODEL_NAME = "vinai/phobert-base-v2"
    MAX_LEN = 256  # PhoBERT position embeddings only support up to 256

    def __init__(self, model_path="pho_bert_crf_medical.pth", device=None):
        self.device = device or get_device()
        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
        self.model = PhoBERT_CRF(num_labels=len(LABELS), model_name=self.MODEL_NAME)
        state = torch.load(model_path, map_location=self.device)
        self.model.load_state_dict(state)
        self.model.to(self.device)
        self.model.eval()
        self.id2label = ID2LABEL
        self.normalizer = MedicalNormalizer()

    def extract(self, text: str):
        # Word segmentation (PhoBERT expects pre-segmented Vietnamese text)
        segmented = word_tokenize(text, format="text")

        encoding = self.tokenizer(
            segmented,
            return_tensors="pt",
            truncation=True,
            max_length=self.MAX_LEN,
            padding=True,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(encoding["input_ids"], encoding["attention_mask"])
            predictions = outputs["predictions"][0]  # label ids for non-padded tokens

        # Align tokens with CRF decode length (mask length, not padded length)
        seq_len = len(predictions)
        tokens = self.tokenizer.convert_ids_to_tokens(encoding["input_ids"][0][:seq_len])

        entities = []
        current_tokens = None
        current_label = None

        for token, pred_id in zip(tokens, predictions):
            if token in ["<s>", "</s>", "<pad>"]:
                continue

            label = self.id2label.get(pred_id, "O")

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
        return ENTITY_TYPE_MAP.get(label, "UNKNOWN")

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