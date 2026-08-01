"""Trích ICD-10 từ `icd-10-vn.pdf` — bảng Excel của BYT export ra PDF.

**Không OCR** (quyết định D1): file có text layer 8,4 triệu ký tự và 0 ảnh nhúng.
PyMuPDF `find_tables()` cho ra đúng 29 cột trên cả 1.271 trang, và cột STT chạy
liên tục 1→15.844 nên tính toàn vẹn *chứng minh được*, không phải ước lượng.

Giá trị riêng của nguồn này so với `ICD10.csv`: có **tên tiếng Anh WHO 2019**
(mở đường cho embedding y sinh tiếng Anh ở cả nhánh ICD) và **phân cấp đầy đủ**
chương → khối → tiểu khối → nhóm 3 ký tự.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from smart_medic.kb import config
from smart_medic.kb.extract.base import SingleFileExtractor, StagingBatch, sha256_file
from smart_medic.kb.normalize.codes import (
    is_disease_code,
    is_range_code,
    split_crossref,
    strip_marker,
)
from smart_medic.kb.normalize.text import fix_hyphen_wrap

SOURCE = "icd10_pdf_who"
VOCAB = "icd10"

# Vị trí cột trong bảng 29 cột — đã đối chiếu với hàng tiêu đề trang 1
# và kiểm chéo trên dữ liệu thật (xem docs/kb-pipeline-plan.md §10).
C_STT = 0
C_CHAPTER_CODE = 2
C_CHAPTER_EN, C_CHAPTER_VI = 3, 4
C_BLOCK_CODE = 5
C_BLOCK_EN, C_BLOCK_VI = 6, 7
C_SUB1_CODE, C_SUB1_EN, C_SUB1_VI = 8, 9, 10
C_SUB2_CODE, C_SUB2_EN, C_SUB2_VI = 11, 12, 13
C_CAT3_CODE, C_CAT3_EN, C_CAT3_VI = 14, 15, 16
C_CODE = 17
C_CODE_NODOT = 18
C_NAME_EN = 19
C_GUIDE_EN = 20
C_NAME_VI = 21
C_GUIDE_VI = 22

# Các cột cờ: ô có giá trị nghĩa là cờ bật (giá trị chính là mã bệnh).
FLAG_COLUMNS = {
    23: "not_primary",
    24: "discouraged_primary",
    25: "superseded_by_more_specific",
    26: "mortality_coding_only",
    27: "female_only",
    28: "male_only",
}

N_COLS = 29
_WS = re.compile(r"\s+")


def _clean(cell: str | None) -> str:
    if not cell:
        return ""
    text = _WS.sub(" ", unicodedata.normalize("NFC", cell)).strip()
    return fix_hyphen_wrap(text)


@dataclass(slots=True)
class _Level:
    """Một bậc trong phân cấp ICD."""

    code: str
    name_en: str
    name_vi: str


class ICDPdfExtractor(SingleFileExtractor):
    name = SOURCE

    def __init__(self, path=None) -> None:
        self.path = path or config.ICD_PDF
        # Mã bị loại vì sai định dạng — in ra chứ không bỏ lặng lẽ.
        self.reject_report: list[tuple[str, str]] = []

    def extract(self) -> StagingBatch:
        import fitz  # nạp muộn: chỉ pha `extract` cần pymupdf

        batch = StagingBatch()
        seen_concepts: set[str] = set()
        seen_terms: set[tuple[str, str, str]] = set()
        seen_rels: set[tuple[str, str, str]] = set()
        n_rows = 0

        doc = fitz.open(self.path)
        try:
            for page_no in range(doc.page_count):
                tables = doc[page_no].find_tables()
                if not tables.tables:
                    continue
                table = tables.tables[0]
                if table.col_count != N_COLS:
                    raise ValueError(
                        f"{self.path.name} trang {page_no + 1}: mong {N_COLS} cột, "
                        f"thấy {table.col_count}. Nguồn thô đã đổi — dừng thay vì đoán."
                    )
                for raw in table.extract():
                    row = [_clean(c) for c in raw]
                    if not row[C_STT].isdigit():
                        continue  # hàng tiêu đề lặp trên mỗi trang
                    n_rows += 1
                    self._emit_row(row, batch, seen_concepts, seen_terms, seen_rels)
        finally:
            doc.close()

        batch.sources.append(
            {
                "source": SOURCE,
                "release": "WHO 2019 / QĐ BYT",
                "origin_file": self.path.name,
                "sha256": sha256_file(self.path),
                "n_rows": n_rows,
            }
        )
        return batch

    # ── nội bộ ───────────────────────────────────────────────────────────

    def _emit_row(
        self,
        row: list[str],
        batch: StagingBatch,
        seen_concepts: set[str],
        seen_terms: set[tuple[str, str, str]],
        seen_rels: set[tuple[str, str, str]],
    ) -> None:
        code, marker = strip_marker(row[C_CODE])
        if not code:
            return
        if not is_disease_code(code):
            self.reject_report.append((code, row[C_NAME_VI][:80]))
            return

        # ── concept cấp bệnh ──
        name_en, refs_en = split_crossref(row[C_NAME_EN])
        name_vi, refs_vi = split_crossref(row[C_NAME_VI])

        if code not in seen_concepts:
            seen_concepts.add(code)
            batch.concepts.append(
                {
                    "vocab": VOCAB,
                    "code": code,
                    "source": SOURCE,
                    "entity_kind": "disease",
                    "pref_vi": name_vi or None,
                    "pref_en": name_en or None,
                    "is_active": True,
                }
            )

        for text, lang in ((name_vi, "vi"), (name_en, "en")):
            self._add_term(batch, seen_terms, code, text, lang, "preferred", True)

        # ── attributes ──
        attrs: list[tuple[str, str]] = []
        if marker:
            attrs.append(("who_marker", marker))
        if row[C_CODE_NODOT]:
            attrs.append(("code_nodot", row[C_CODE_NODOT]))
        if row[C_GUIDE_EN]:
            attrs.append(("who_guidance_en", row[C_GUIDE_EN]))
        if row[C_GUIDE_VI]:
            attrs.append(("who_guidance_vi", row[C_GUIDE_VI]))
        if row[C_CHAPTER_CODE]:
            attrs.append(("chapter", row[C_CHAPTER_CODE]))
        if row[C_BLOCK_CODE]:
            attrs.append(("block", row[C_BLOCK_CODE]))
        for col, attr in FLAG_COLUMNS.items():
            if row[col]:
                attrs.append((attr, "1"))
        for attr, value in attrs:
            batch.attributes.append({"vocab": VOCAB, "code": code, "attr": attr, "value": value})

        # ── quan hệ dagger → asterisk ──
        # "Amoebic liver abscess (K77.0*)": mã nguyên nhân trỏ tới mã biểu hiện.
        for ref in dict.fromkeys(refs_en + refs_vi):
            if is_disease_code(ref) and ref != code:
                self._add_rel(batch, seen_rels, code, "manifests_as", ref)

        # ── phân cấp: bệnh → nhóm 3 ký tự → tiểu khối → khối → chương ──
        levels = self._levels(row)
        chain = [code, *[lv.code for lv in levels]]
        for child, parent in zip(chain, chain[1:], strict=False):
            if child != parent:
                self._add_rel(batch, seen_rels, child, "isa", parent)

        for lv in levels:
            if lv.code in seen_concepts:
                continue
            seen_concepts.add(lv.code)
            batch.concepts.append(
                {
                    "vocab": VOCAB,
                    "code": lv.code,
                    "source": SOURCE,
                    "entity_kind": "icd_group",
                    "pref_vi": lv.name_vi or None,
                    "pref_en": lv.name_en or None,
                    "is_active": True,
                }
            )
            for text, lang in ((lv.name_vi, "vi"), (lv.name_en, "en")):
                self._add_term(batch, seen_terms, lv.code, text, lang, "group_name", True)

    @staticmethod
    def _levels(row: list[str]) -> list[_Level]:
        """Các bậc phân cấp của hàng, từ hẹp tới rộng. Bỏ bậc trống.

        Mã nhóm cũng mang ký hiệu dagger/asterisk (`D63*`, `G01*` — các nhóm
        "biểu hiện" của WHO) nên phải strip y như mã bệnh, nếu không cùng một
        nhóm sẽ tồn tại hai concept `G01` và `G01*`.
        """
        spec = [
            (C_CAT3_CODE, C_CAT3_EN, C_CAT3_VI),
            (C_SUB2_CODE, C_SUB2_EN, C_SUB2_VI),
            (C_SUB1_CODE, C_SUB1_EN, C_SUB1_VI),
            (C_BLOCK_CODE, C_BLOCK_EN, C_BLOCK_VI),
            (C_CHAPTER_CODE, C_CHAPTER_EN, C_CHAPTER_VI),
        ]
        out = []
        for c_code, c_en, c_vi in spec:
            if not row[c_code]:
                continue
            code, _marker = strip_marker(row[c_code])
            if code and (is_disease_code(code) or is_range_code(code)):
                out.append(_Level(code, row[c_en], row[c_vi]))
        return out

    @staticmethod
    def _add_term(
        batch: StagingBatch,
        seen: set[tuple[str, str, str]],
        code: str,
        text: str,
        lang: str,
        term_type: str,
        preferred: bool,
    ) -> None:
        if not text:
            return
        key = (code, lang, text)
        if key in seen:
            return
        seen.add(key)
        batch.terms.append(
            {
                "vocab": VOCAB,
                "code": code,
                "source": SOURCE,
                "term": text,
                "lang": lang,
                "term_type": term_type,
                "is_preferred": preferred,
                "tier": "authoritative",
                "evidence": None,
            }
        )

    @staticmethod
    def _add_rel(
        batch: StagingBatch,
        seen: set[tuple[str, str, str]],
        src: str,
        rel: str,
        dst: str,
    ) -> None:
        key = (src, rel, dst)
        if key in seen:
            return
        seen.add(key)
        batch.relations.append(
            {
                "src_vocab": VOCAB,
                "src_code": src,
                "rel": rel,
                "dst_vocab": VOCAB,
                "dst_code": dst,
                "rel_group": None,
                "priority": None,
                "tier": "authoritative",
                "meta": None,
            }
        )
