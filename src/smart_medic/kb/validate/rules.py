"""Cổng chất lượng — khai báo dạng dữ liệu, FAIL HARD chứ không cảnh báo suông.

Mỗi rule là một câu SQL trả về **một số**, kèm điều kiện. Viết dạng khai báo
để thêm rule không phải sửa code, và để `smk kb validate` in ra bảng đọc được.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    sql: str
    check: Callable[[int], bool]
    expected: str
    phase: str = "1"

    def run(self, conn: sqlite3.Connection) -> tuple[bool, int]:
        value = conn.execute(self.sql).fetchone()[0]
        return self.check(value), value


def _zero(v: int) -> bool:
    return v == 0


def _positive(v: int) -> bool:
    return v > 0


# ── Rule chung, áp cho mọi phase ─────────────────────────────────────────
COMMON_RULES = [
    Rule(
        "concept_khong_co_term",
        "SELECT count(*) FROM concepts c "
        "WHERE NOT EXISTS (SELECT 1 FROM terms t WHERE t.concept_id = c.concept_id)",
        _zero,
        "= 0",
    ),
    Rule(
        "canh_mo_coi_src",
        "SELECT count(*) FROM relations r "
        "WHERE NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = r.src_concept)",
        _zero,
        "= 0",
    ),
    Rule(
        "canh_mo_coi_dst",
        "SELECT count(*) FROM relations r "
        "WHERE NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = r.dst_concept)",
        _zero,
        "= 0",
    ),
    Rule(
        "canh_tu_vong",
        "SELECT count(*) FROM relations WHERE src_concept = dst_concept",
        _zero,
        "= 0",
    ),
    Rule(
        "attribute_mo_coi",
        "SELECT count(*) FROM attributes a "
        "WHERE NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = a.concept_id)",
        _zero,
        "= 0",
    ),
    Rule(
        "term_derived_thieu_evidence",
        "SELECT count(*) FROM terms WHERE tier = 'derived' AND evidence IS NULL",
        _zero,
        "= 0",
    ),
    Rule(
        "norm_term_rong",
        "SELECT count(*) FROM terms WHERE trim(norm_term) = ''",
        _zero,
        "= 0",
    ),
    Rule(
        "fts_dong_bo_voi_terms",
        "SELECT (SELECT count(*) FROM terms) - (SELECT count(*) FROM terms_fts)",
        _zero,
        "= 0",
    ),
]

# ── ICD-10 (Phase 1) ─────────────────────────────────────────────────────
ICD_RULES = [
    Rule(
        "icd_ma_benh_sai_dinh_dang",
        r"SELECT count(*) FROM concepts WHERE vocab = 'icd10' AND entity_kind = 'disease' "
        r"AND code NOT GLOB '[A-Z][0-9][0-9]' "
        r"AND code NOT GLOB '[A-Z][0-9][0-9].[0-9]' "
        r"AND code NOT GLOB '[A-Z][0-9][0-9].[0-9][0-9]'",
        _zero,
        "= 0",
    ),
    Rule(
        # 15.843 mã hợp lệ từ PDF + 1.101 mã chỉ có ở ICD10.csv.
        #
        # Kế hoạch ban đầu ghi 16.949; con số đó đếm trên dữ liệu THÔ, trước khi
        # phát hiện hai loại rác phải lọc (xem docs §10, Phase 1):
        #   · PDF  — 1 hàng "đánh số cột" ở trang 1 lọt qua bộ lọc tiêu đề,
        #            và 1 mã gõ sai `U13/9`
        #   · CSV  — 4 dòng test còn sót của BYT (`I65565`→"gdfgdfg", `T112233`→"aaaa"…)
        "icd_so_ma_benh",
        "SELECT count(*) FROM concepts WHERE vocab = 'icd10' AND entity_kind = 'disease'",
        lambda v: v == 16944,
        "= 16.944  (15.843 từ PDF + 1.101 chỉ có ở ICD10.csv)",
    ),
    Rule(
        "icd_con_dau_ky_hieu_trong_ma",
        "SELECT count(*) FROM concepts WHERE vocab = 'icd10' "
        "AND (code LIKE '%†%' OR code LIKE '%*%')",
        _zero,
        "= 0",
    ),
    Rule(
        "icd_co_ten_tieng_anh",
        "SELECT count(*) FROM terms t JOIN concepts c USING (concept_id) "
        "WHERE c.vocab = 'icd10' AND t.lang = 'en'",
        _positive,
        "> 0  (mở đường cho embedding y sinh tiếng Anh)",
    ),
    Rule(
        "icd_co_phan_cap_isa",
        "SELECT count(*) FROM relations r JOIN concepts c ON c.concept_id = r.src_concept "
        "WHERE r.rel = 'isa' AND c.vocab = 'icd10'",
        _positive,
        "> 0",
    ),
]

# ── RxNorm (Phase 2) ─────────────────────────────────────────────────────
# `rela` được phép — phải khớp ALLOWED_RELA ở extract/rxnorm_rrf.py.
# Chỉ giữ chiều thuận; chiều nghịch là bản sao gương nên bị loại.
_ALLOWED_RELA_SQL = (
    "'isa','has_ingredient','has_precise_ingredient','has_tradename',"
    "'has_dose_form','has_doseformgroup','consists_of','has_form'"
)

RXNORM_RULES = [
    Rule(
        "rxnorm_so_concept",
        "SELECT count(*) FROM concepts WHERE vocab = 'rxnorm'",
        lambda v: v == 124708,
        "= 124.708  (rxcui có ≥1 atom SAB=RXNORM, suppress='N')",
        phase="2",
    ),
    Rule(
        "rxnorm_thieu_ten_hien_thi",
        "SELECT count(*) FROM concepts WHERE vocab = 'rxnorm' AND pref_en IS NULL",
        _zero,
        "= 0",
        phase="2",
    ),
    Rule(
        "rxnorm_quan_he_ngoai_danh_sach",
        "SELECT count(*) FROM relations r JOIN concepts c ON c.concept_id = r.src_concept "
        f"WHERE c.vocab = 'rxnorm' AND r.rel NOT IN ({_ALLOWED_RELA_SQL})",
        _zero,
        "= 0  (gồm cả inactive_ingredient và mọi chiều nghịch)",
        phase="2",
    ),
    Rule(
        "rxnorm_quan_he_hai_chieu_trung_lap",
        "SELECT count(*) FROM relations a JOIN relations b "
        "ON a.src_concept = b.dst_concept AND a.dst_concept = b.src_concept "
        "JOIN concepts c ON c.concept_id = a.src_concept WHERE c.vocab = 'rxnorm'",
        _zero,
        "= 0  (chỉ lưu một chiều)",
        phase="2",
    ),
]

# ── closure (Phase 3 / H1) ───────────────────────────────────────────────
CLOSURE_RULES = [
    Rule(
        "closure_tu_to_tien",
        "SELECT count(*) FROM closure WHERE ancestor = descendant",
        _zero,
        "= 0",
        phase="3",
    ),
    Rule(
        "closure_co_chu_trinh",
        "SELECT count(*) FROM closure a JOIN closure b "
        "ON a.ancestor = b.descendant AND a.descendant = b.ancestor",
        _zero,
        "= 0  (DAG phải là DAG)",
        phase="3",
    ),
    Rule(
        "closure_mo_coi",
        "SELECT count(*) FROM closure cl "
        "WHERE NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = cl.ancestor) "
        "   OR NOT EXISTS (SELECT 1 FROM concepts c WHERE c.concept_id = cl.descendant)",
        _zero,
        "= 0",
        phase="3",
    ),
]


def rules_for(conn: sqlite3.Connection) -> list[Rule]:
    """Chọn rule theo dữ liệu thực sự có trong artifact.

    Build từng phần (`--source icd`) không nên fail vì thiếu RxNorm.
    """
    have = {r[0] for r in conn.execute("SELECT DISTINCT vocab FROM concepts")}
    selected = list(COMMON_RULES)
    if "icd10" in have:
        selected += ICD_RULES
    if "rxnorm" in have:
        selected += RXNORM_RULES
    if conn.execute("SELECT count(*) FROM closure").fetchone()[0]:
        selected += CLOSURE_RULES
    return selected
