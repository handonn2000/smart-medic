"""Corpus `.json` → ví dụ BIO, **offset-safe**.

★ MỘT PHÉP THỬ ĐÃ CHẠY, VÀ KẾT QUẢ CỦA NÓ QUYẾT ĐỊNH THIẾT KẾ
──────────────────────────────────────────────────────────────
Câu hỏi: `offset_mapping` của XLM-R trỏ vào chuỗi GỐC hay chuỗi đã chuẩn hoá?
Nếu là chuỗi đã chuẩn hoá thì mọi span trả ra đều lệch trên 20/100 file
`data/test` không NFC — im lặng.

Đo trực tiếp trên `xlm-roberta-base`, ba dạng đầu vào:

    NFC   "tiền sản giật nặng"  18 ký tự  → offset (0,4) (5,8) (9,13) (14,18)
    NFD   cùng chuỗi            25 ký tự  → offset (0,6) (7,11) (12,14) …
    TRỘN  NFC+NFD trong 1 cụm   21 ký tự  → offset (0,4) (5,9) (10,12) …

Cả ba đều trỏ đúng vào **chuỗi gốc**. Nhưng TOKEN thì đã bị chuẩn hoá: đầu vào
NFD cho ra token `▁tiên` chứ không phải `▁tiền`.

⇒ Hệ quả bắt buộc: **không bao giờ ghép lại văn bản từ token**. Luôn cắt từ
`text` bằng offset. Quy tắc này cài ở `stages.bio._make`.

★ CỬA SỔ TRƯỢT
Tài liệu trung vị 1.838 ký tự → vượt 512 token của XLM-R. Cắt cửa sổ có
`stride` để span nằm ở mép cửa sổ này vẫn nằm giữa cửa sổ kia. Offset luôn là
offset TUYỆT ĐỐI trên tài liệu gốc, không phải trên cửa sổ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from smart_medic.stages.bio import spans_to_tags
from smart_medic.stages.scoring import Entity
from smart_medic.stages.textio import read_document

MAX_LEN = 512
STRIDE = 128


@dataclass(slots=True)
class Window:
    """Một cửa sổ token của một tài liệu."""

    doc: str
    input_ids: list[int]
    attention_mask: list[int]
    labels: list[int]
    offsets: list[tuple[int, int]]


def load_corpus(root: Path, names: list[str] | None = None) -> list[tuple[str, str, list[Entity]]]:
    """`(tên, văn bản, span)` — đọc bằng `read_document`, KHÔNG `Path.read_text`."""
    ann_dir = root / "annotations"
    text_dir = root / "text"
    stems = names or sorted((p.stem for p in ann_dir.glob("*.json")), key=lambda s: (len(s), s))
    out = []
    for stem in stems:
        text = read_document(text_dir / f"{stem}.txt")
        raw = json.loads((ann_dir / f"{stem}.json").read_text(encoding="utf-8"))
        out.append((stem, text, [Entity.from_dict(d) for d in raw]))
    return out


def encode_document(
    name: str, text: str, spans: list[Entity], tokenizer, *, max_len: int = MAX_LEN
) -> list[Window]:
    """Cắt tài liệu thành cửa sổ, gán nhãn BIO theo offset ký tự tuyệt đối."""
    enc = tokenizer(
        text,
        return_offsets_mapping=True,
        truncation=True,
        max_length=max_len,
        stride=STRIDE,
        return_overflowing_tokens=True,
        padding=False,
    )
    out: list[Window] = []
    for i in range(len(enc["input_ids"])):
        offsets = [tuple(o) for o in enc["offset_mapping"][i]]
        out.append(
            Window(
                doc=name,
                input_ids=enc["input_ids"][i],
                attention_mask=enc["attention_mask"][i],
                labels=spans_to_tags(offsets, spans),
                offsets=offsets,
            )
        )
    return out


def build(root: Path, tokenizer, names: list[str] | None = None) -> list[Window]:
    out: list[Window] = []
    for name, text, spans in load_corpus(root, names):
        out.extend(encode_document(name, text, spans, tokenizer))
    return out


def read_splits(root: Path) -> dict[str, list[str]]:
    return json.loads((root / "splits.json").read_text(encoding="utf-8"))
