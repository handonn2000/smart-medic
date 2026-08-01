"""Trích ICD-10 từ `ICD10.csv` — danh mục của Bộ Y tế (QĐ 4469/BYT).

Nguồn này **bổ sung** chứ không thay thế PDF: đo được 1.105 mã chỉ có ở đây,
là các **mã mở rộng 5 ký tự của BYT** chi tiết hơn WHO một cấp (`A06.81`,
`A17.83`, `A18.02`). Ngược lại PDF có 3.868 mã mà CSV không có.

Hai đặc thù phải xử lý:
  1. Mã lặp rất nhiều (36.689 dòng nhưng chỉ 13.081 mã duy nhất) → dedupe.
  2. Một ô có thể chứa nhiều tên ngăn bằng dấu phẩy → tách theo heuristic
     ở `normalize/synonyms.py`, và in ra để duyệt tay (quyết định D4).
"""

from __future__ import annotations

import csv
import re
import unicodedata

from smart_medic.kb import config
from smart_medic.kb.extract.base import SingleFileExtractor, StagingBatch, sha256_file
from smart_medic.kb.normalize.codes import is_disease_code, split_crossref, strip_marker
from smart_medic.kb.normalize.synonyms import split_synonyms

SOURCE = "icd10_csv_byt"
VOCAB = "icd10"

HEADER_ROW = 4  # 4 dòng đầu là tiêu đề tài liệu, không phải dữ liệu

C_CODE = 1
C_NAME = 2
C_GROUP = 3
C_CHRONIC = 4
C_SPECIALTY = 10
C_DECISION = 11
C_EFFECTIVE = 12

_WS = re.compile(r"\s+")


def _clean(cell: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", cell or "")).strip()


class ICDCsvExtractor(SingleFileExtractor):
    name = SOURCE

    def __init__(self, path=None) -> None:
        self.path = path or config.ICD_CSV
        # Mọi tên bị tách, để `smk kb extract` in ra cho người soát một lần.
        self.split_report: list[tuple[str, str, list[str]]] = []
        # Mã bị loại vì sai định dạng. File công bố của BYT còn sót vài dòng
        # test ("18"→"22", "I65565"→"gdfgdfg", "T112233"→"aaaa"…) nên phải lọc,
        # nhưng lọc có báo cáo chứ không im lặng.
        self.reject_report: list[tuple[str, str]] = []

    def extract(self) -> StagingBatch:
        batch = StagingBatch()
        seen_concepts: set[str] = set()
        seen_terms: set[tuple[str, str]] = set()
        n_rows = 0

        with self.path.open(encoding="utf-8-sig", newline="") as f:
            for i, raw in enumerate(csv.reader(f)):
                if i <= HEADER_ROW or len(raw) <= C_NAME:
                    continue
                code, _marker = strip_marker(_clean(raw[C_CODE]))
                if not code:
                    continue
                if not is_disease_code(code):
                    self.reject_report.append((code, _clean(raw[C_NAME])[:80]))
                    continue
                n_rows += 1
                self._emit(raw, code, batch, seen_concepts, seen_terms)

        batch.sources.append(
            {
                "source": SOURCE,
                "release": "QĐ 4469/BYT ngày 28/10/2020",
                "origin_file": self.path.name,
                "sha256": sha256_file(self.path),
                "n_rows": n_rows,
            }
        )
        return batch

    def _emit(
        self,
        raw: list[str],
        code: str,
        batch: StagingBatch,
        seen_concepts: set[str],
        seen_terms: set[tuple[str, str]],
    ) -> None:
        name, _refs = split_crossref(_clean(raw[C_NAME]))
        parts = split_synonyms(name) if name else []
        if len(parts) > 1:
            self.split_report.append((code, name, parts))

        if code not in seen_concepts:
            seen_concepts.add(code)
            batch.concepts.append(
                {
                    "vocab": VOCAB,
                    "code": code,
                    "source": SOURCE,
                    "entity_kind": "disease",
                    "pref_vi": parts[0] if parts else None,
                    "pref_en": None,
                    "is_active": True,
                }
            )
            for col, attr in (
                (C_GROUP, "byt_group"),
                (C_CHRONIC, "byt_chronic"),
                (C_SPECIALTY, "byt_specialty"),
                (C_DECISION, "byt_decision"),
                (C_EFFECTIVE, "byt_effective"),
            ):
                value = _clean(raw[col]) if len(raw) > col else ""
                if value:
                    batch.attributes.append(
                        {"vocab": VOCAB, "code": code, "attr": attr, "value": value}
                    )

        for idx, part in enumerate(parts):
            key = (code, part)
            if key in seen_terms:
                continue
            seen_terms.add(key)
            batch.terms.append(
                {
                    "vocab": VOCAB,
                    "code": code,
                    "source": SOURCE,
                    "term": part,
                    "lang": "vi",
                    "term_type": "preferred" if idx == 0 else "synonym",
                    "is_preferred": idx == 0,
                    "tier": "authoritative",
                    "evidence": None,
                }
            )
