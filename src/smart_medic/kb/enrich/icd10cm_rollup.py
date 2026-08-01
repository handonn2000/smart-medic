"""E2 — tên tiếng Anh của ICD-10-CM gắn vào mã WHO tương ứng.

ICD-10-CM (bản Mỹ) chi tiết hơn WHO một cấp và **không có dấu chấm**:

    K2100  Gastro-esophageal reflux disease with esophagitis, without bleeding
    K2101  Gastro-esophageal reflux disease with esophagitis, with bleeding
    K219   Gastro-esophageal reflux disease without esophagitis
                    │
                    └─ rollup 4 ký tự → K21.0 / K21.9 (WHO)

Cho thêm cách diễn đạt tiếng Anh, bổ trợ cho tên WHO 2019 vốn chỉ có một bản.

★ Rủi ro đã biết: tên CM có thể **đặc hiệu hơn** mã WHO nhận nó (`K2100` nói rõ
"without bleeding" còn `K21.0` thì không). Vì vậy tier là `derived` và evidence
ghi lại mã CM gốc để truy được nguồn khi retrieval trả kết quả lạ.
"""

from __future__ import annotations

import re

from smart_medic.kb import config
from smart_medic.kb.enrich.base import EnrichBatch
from smart_medic.kb.normalize.codes import is_disease_code

NAME = "icd10cm_2027"
TIER = "derived"
VOCAB = "icd10"

# Dòng có dạng "<mã><khoảng trắng><mô tả>"
_LINE = re.compile(r"^([A-Z]\d{2}[A-Z0-9]*)\s+(.+)$")


def cm_to_who_candidates(cm_code: str) -> list[str]:
    """Các mã WHO có thể ứng với một mã CM, xếp từ ĐẶC HIỆU NHẤT xuống.

    >>> cm_to_who_candidates("K2100")
    ['K21.00', 'K21.0', 'K21']
    >>> cm_to_who_candidates("A15")
    ['A15']

    Phải trả nhiều ứng viên chứ không một: CM chi tiết hơn WHO nên `K2100`
    không có mã WHO cùng độ dài — `K21.00` không tồn tại, `K21.0` mới có.
    Người gọi chọn ứng viên đầu tiên CÓ THẬT trong KB. Cắt cứng 2 chữ số như
    bản đầu sẽ âm thầm bỏ mất phần lớn mã CM.
    """
    head, tail = cm_code[:3], cm_code[3:]
    if not is_disease_code(head):
        return []
    out = []
    for n in (2, 1):
        if len(tail) >= n:
            cand = f"{head}.{tail[:n]}"
            if is_disease_code(cand):
                out.append(cand)
    out.append(head)
    return out


def cm_to_who(cm_code: str, known: set[str] | None = None) -> str | None:
    """Mã WHO đặc hiệu nhất ứng với `cm_code` mà **có thật** trong `known`."""
    cands = cm_to_who_candidates(cm_code)
    if known is None:
        return cands[0] if cands else None
    return next((c for c in cands if c in known), None)


class Icd10CmRollup:
    name = NAME

    def __init__(self, path=None) -> None:
        self.path = path or config.ICD10CM_CODES
        self.n_lines = 0

    def available(self) -> bool:
        return self.path.is_file()

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        batch = EnrichBatch()
        codes = known.get(VOCAB, set())
        seen: set[tuple[str, str]] = set()

        with self.path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LINE.match(line.strip())
                if not m:
                    continue
                self.n_lines += 1
                cm_code, name = m.group(1), m.group(2).strip()
                who = cm_to_who(cm_code, codes)
                if who is None:
                    continue
                key = (who, name)
                if key in seen:
                    continue
                seen.add(key)
                batch.add_term(
                    vocab=VOCAB,
                    code=who,
                    source=NAME,
                    term=name,
                    lang="en",
                    term_type="cm_rollup",
                    tier=TIER,
                    evidence={"via": "icd10cm_rollup", "cm_code": cm_code},
                )
        return batch
