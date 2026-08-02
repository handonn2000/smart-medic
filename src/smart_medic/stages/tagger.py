"""Suy luận bằng tagger XLM-R — **torch nạp lười, thiếu thì suy biến an toàn**.

★ RÀNG BUỘC ĐÓNG GÓI (PRD §5 — cài lại không được thì BỊ LOẠI)
──────────────────────────────────────────────────────────────
`pyproject.toml` CỐ Ý tách `torch` (~1 GB) khỏi dependency lõi; image `runtime`
chỉ mang nhánh từ vựng. Module này phá ranh giới đó nếu `import torch` nằm ở
đầu file — mọi lần `smk solve` sẽ đòi 1 GB dependency chỉ để chạy pipeline luật.

Nên torch **nạp bên trong hàm**. Thiếu torch, thiếu weights, hay tắt cờ ⇒ trả
danh sách rỗng và pipeline chạy tiếp bằng proposer luật. Đó chính là "fallback
offline" mà PRD §8 khuyến nghị, và là điều kiện để Phase 6 đóng gói được.

★ ƯU TIÊN SỐ MỘT LÀ OFFSET
Toàn bộ phần dễ sai — ánh xạ subword → ký tự và ràng buộc BIO — nằm ở
`stages/bio.py`, **không phụ thuộc torch**, nên test được đầy đủ kể cả khi máy
chưa cài gì. Module này chỉ lo phần gọi model và ghép cửa sổ.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.config import ARTIFACT_DIR
from smart_medic.stages.bio import LABELS, tags_to_spans, transition_mask, viterbi
from smart_medic.stages.flags import flag
from smart_medic.stages.scoring import Entity

TAGGER_DIR = ARTIFACT_DIR / "tagger" / "v1"
MAX_LEN = 512
STRIDE = 128


class TaggerUnavailable(RuntimeError):
    """Không dùng được tagger. KHÔNG phải lỗi — pipeline luật chạy tiếp."""


@dataclass(slots=True)
class Tagger:
    tokenizer: object
    model: object
    threshold: float = 0.0

    def score_windows(self, text: str) -> list[tuple[list[tuple[int, int]], list[list[float]]]]:
        """`(offsets, log-prob theo token)` cho từng cửa sổ."""
        import torch

        enc = self.tokenizer(
            text,
            return_offsets_mapping=True,
            truncation=True,
            max_length=MAX_LEN,
            stride=STRIDE,
            return_overflowing_tokens=True,
            padding=False,
        )
        out = []
        for i in range(len(enc["input_ids"])):
            ids = torch.tensor([enc["input_ids"][i]])
            with torch.no_grad():
                logits = self.model(input_ids=ids).logits[0]
            logp = torch.log_softmax(logits, dim=-1).tolist()
            out.append(([tuple(o) for o in enc["offset_mapping"][i]], logp))
        return out

    def predict(self, text: str) -> list[Entity]:
        """Span + nhãn cho một văn bản. Ghép cửa sổ bằng hợp span, ưu tiên span dài.

        Ghép ở mức SPAN chứ không mức token: hai cửa sổ chồng nhau có thể cho hai
        chuỗi nhãn khác nhau ở vùng giao, và trộn token của chúng sẽ tạo ra chuỗi
        BIO không cửa sổ nào thật sự dự đoán — đúng thứ Viterbi vừa loại bỏ.
        """
        mask = transition_mask()
        spans: list[Entity] = []
        for offsets, logp in self.score_windows(text):
            if self.threshold:
                logp = [_suppress(row, self.threshold) for row in logp]
            spans.extend(tags_to_spans(text, offsets, viterbi(logp, mask)))
        return _merge(spans)


def _suppress(row: list[float], threshold: float) -> list[float]:
    """Đẩy nhãn thực thể xuống nếu chưa vượt ngưỡng tin cậy so với `O`.

    Ngưỡng hiệu chỉnh trên dev TỔNG HỢP (`train/calibrate.py`), **không bao giờ**
    trên `gold_real` — nó là cổng (quy tắc §5.7).
    """
    best = max(range(1, len(row)), key=lambda i: row[i])
    if row[best] - row[0] < threshold:
        return [row[0] + 1e3] + row[1:]
    return row


def _merge(spans: list[Entity]) -> list[Entity]:
    """Bỏ span trùng/chồng lấn giữa các cửa sổ. Dài trước, tie-break theo vị trí."""
    out: list[Entity] = []
    for e in sorted(spans, key=lambda x: (-(x.end - x.start), x.start, x.type)):
        if all(e.start >= o.end or e.end <= o.start for o in out):
            out.append(e)
    return sorted(out, key=lambda x: (x.start, x.end))


@functools.lru_cache(maxsize=1)
def load(path: Path | None = None) -> Tagger:
    """Nạp checkpoint. Ném `TaggerUnavailable` nếu thiếu torch hoặc thiếu weights."""
    d = path or TAGGER_DIR
    if not (d / "config.json").is_file():
        raise TaggerUnavailable(f"chưa có checkpoint ở {d}")
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError as exc:  # torch/transformers không cài — đường chạy runtime
        raise TaggerUnavailable("thiếu torch/transformers") from exc

    meta_path = d / "smk_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if meta.get("labels") and list(meta["labels"]) != list(LABELS):
        # Thứ tự nhãn khác ⇒ chỉ số nhãn trong weights trỏ nhầm. Hỏng ÂM THẦM,
        # chỉ biểu hiện thành điểm tụt không rõ lý do — cùng loại bẫy `concept_id`.
        raise TaggerUnavailable("thứ tự nhãn của checkpoint khác stages.bio.LABELS")

    model = AutoModelForTokenClassification.from_pretrained(d)
    model.eval()
    return Tagger(
        AutoTokenizer.from_pretrained(d, use_fast=True), model, meta.get("threshold", 0.0)
    )


def detect(text: str, *, enabled: bool | None = None) -> list[Entity]:
    """Điểm vào cho pipeline. **Không bao giờ ném** — thiếu gì thì trả rỗng."""
    if not flag("tagger", override=enabled):
        return []
    try:
        return load().predict(text)
    except (TaggerUnavailable, OSError):
        return []
