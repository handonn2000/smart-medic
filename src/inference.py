import json

import torch
from underthesea import word_tokenize
from transformers import AutoTokenizer

try:
    from src.model import PhoBERT_CRF
    from src.labels import LABELS, ID2LABEL, ENTITY_TYPE_MAP
    from src.assertions import assertions_at
    from src.tokenization import chunk_words, group_entities, segment_document
except ImportError:
    from model import PhoBERT_CRF
    from labels import LABELS, ID2LABEL, ENTITY_TYPE_MAP
    from assertions import assertions_at
    from tokenization import chunk_words, group_entities, segment_document

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
        words = segment_document(text, self._segment_line)
        if not words:
            return []

        # Encode one word at a time, exactly as MedicalNERDataset does at training time,
        # so the model sees the same input_ids and so every subword is traceable back to
        # the word — and therefore to the character span — it came from.
        subwords = [self.tokenizer.encode(surface, add_special_tokens=False)
                    or [self.tokenizer.unk_token_id]
                    for surface, _, _ in words]
        sizes = [len(ids) for ids in subwords]

        entities = []
        for lo, hi in chunk_words(words, sizes, self.MAX_LEN - 2):
            labels = self._label_words(subwords[lo:hi])
            entities += self._entities(words[lo:hi], labels, text)

        return self._post_process(entities, text)

    def _segment_line(self, line: str):
        # use_token_normalize would rewrite spellings ("òa" -> "oà"), which desyncs a
        # token from the input it came from. Older releases lack the argument.
        try:
            return word_tokenize(line, use_token_normalize=False)
        except TypeError:
            return word_tokenize(line)

    def _label_words(self, subwords):
        """One predicted label per word, taken from the word's first subword."""
        flat = [wid for ids in subwords for wid in ids]
        input_ids = [self.tokenizer.cls_token_id] + flat + [self.tokenizer.sep_token_id]
        tensor = torch.tensor([input_ids], device=self.device)
        mask = torch.ones_like(tensor)

        with torch.no_grad():
            predictions = self.model(tensor, mask)["predictions"][0]

        labels, pos = [], 1  # position 0 is <s>
        for ids in subwords:
            inside = pos < len(predictions)
            labels.append(self.id2label.get(predictions[pos], "O") if inside else "O")
            pos += len(ids)
        return labels

    def _entities(self, words, labels, text):
        """Concept dicts whose text is a literal slice of `text` at its own position."""
        return [{
            "text": text[start:end],
            "type": self._get_type(f"B-{etype}"),
            "candidates": [],
            "assertions": [],
            "position": [start, end],
        } for etype, start, end in group_entities(words, labels)]

    def _get_type(self, label):
        """Scored type name for a B- label, or None if it has no scored counterpart."""
        return ENTITY_TYPE_MAP.get(label)

    def _post_process(self, entities, text):
        """Drop unscored types, then fill assertions and candidate codes."""
        # A span whose label has no counterpart in the competition's five types (patient,
        # exogenous agent) can only lose points: it never matches a gold concept, and the
        # gold concept it shadows goes unmatched too, so it is charged twice.
        entities = [ent for ent in entities if ent["type"] is not None]

        for ent in entities:
            ent["assertions"] = assertions_at(text, ent["position"][0], ent["type"])

            # Only diagnoses and drugs have standard codes. Gold leaves the three other
            # types empty, so emitting a code there turns a free J = 1 into J = 0.
            if ent["type"] == "THUỐC":
                ent["candidates"] = self.normalizer.normalize_drug(ent["text"])
            elif ent["type"] == "CHẨN_ĐOÁN":
                ent["candidates"] = self.normalizer.normalize_disease(ent["text"])
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