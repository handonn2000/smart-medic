"""Hợp đồng staging — biên giới giữa `extract` và `load`.

Mọi extractor, bất kể nguồn nào, phải xuất ra đúng 4 file với đúng schema dưới đây.
Đây là hợp đồng được kiểm bằng `tests/contract/`; đổi nó là breaking change.

Staging dùng `(vocab, code)` làm khoá tự nhiên — **chưa có `concept_id`**.
Id số chỉ được gán ở pha `load` (xem `load/ids.py`), nhờ vậy các extractor
hoàn toàn độc lập và chạy song song được.

Lưu ý đặt tên: ở tầng staging và store, `vocab` là BỘ MÃ ('icd10'), còn
`source` là FILE GỐC ('icd10_pdf_who'). Một concept ICD gộp term từ hai file
nên provenance bắt buộc phải nằm ở mức term.
"""

from __future__ import annotations

from typing import Final

import pyarrow as pa

# Giá trị hợp lệ, dùng chung cho cả extract lẫn validate.
VOCABS: Final = ("icd10", "rxnorm", "snomed")
TIERS: Final = ("authoritative", "derived", "generated")
LANGS: Final = ("vi", "en")

# `source` có mặt ở đây để pha `load` merge được TẤT ĐỊNH khi cùng một mã đến
# từ nhiều file (mã ICD có ở cả PDF lẫn ICD10.csv). Không có nó thì thứ tự
# thắng/thua phụ thuộc thứ tự dòng — mà sort của pyarrow không bảo đảm ổn định.
CONCEPTS_SCHEMA: Final = pa.schema(
    [
        pa.field("vocab", pa.string(), nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("entity_kind", pa.string(), nullable=False),
        pa.field("pref_vi", pa.string()),
        pa.field("pref_en", pa.string()),
        pa.field("is_active", pa.bool_(), nullable=False),
    ]
)

TERMS_SCHEMA: Final = pa.schema(
    [
        pa.field("vocab", pa.string(), nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("term", pa.string(), nullable=False),
        pa.field("lang", pa.string(), nullable=False),
        pa.field("term_type", pa.string(), nullable=False),
        pa.field("is_preferred", pa.bool_(), nullable=False),
        pa.field("tier", pa.string(), nullable=False),
        pa.field("evidence", pa.string()),
    ]
)

RELATIONS_SCHEMA: Final = pa.schema(
    [
        pa.field("src_vocab", pa.string(), nullable=False),
        pa.field("src_code", pa.string(), nullable=False),
        pa.field("rel", pa.string(), nullable=False),
        pa.field("dst_vocab", pa.string(), nullable=False),
        pa.field("dst_code", pa.string(), nullable=False),
        pa.field("rel_group", pa.int32()),
        pa.field("priority", pa.int32()),
        pa.field("tier", pa.string(), nullable=False),
        pa.field("meta", pa.string()),
    ]
)

ATTRIBUTES_SCHEMA: Final = pa.schema(
    [
        pa.field("vocab", pa.string(), nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("attr", pa.string(), nullable=False),
        pa.field("value", pa.string()),
    ]
)

SOURCES_SCHEMA: Final = pa.schema(
    [
        pa.field("source", pa.string(), nullable=False),
        pa.field("release", pa.string()),
        pa.field("origin_file", pa.string()),
        pa.field("sha256", pa.string()),
        pa.field("n_rows", pa.int64()),
    ]
)

# Tên file → schema. `load` lặp qua đúng dict này, không hard-code tên ở chỗ khác.
STAGING_SCHEMAS: Final[dict[str, pa.Schema]] = {
    "concepts": CONCEPTS_SCHEMA,
    "terms": TERMS_SCHEMA,
    "relations": RELATIONS_SCHEMA,
    "attributes": ATTRIBUTES_SCHEMA,
    "sources": SOURCES_SCHEMA,
}

# ── Sau pha `normalize` ───────────────────────────────────────────────────
# Chỉ `terms` đổi hình: thêm hai cột dẫn xuất. Các bảng khác chép nguyên.
# Tách hai thư mục `raw/` và `norm/` để chỉnh luật chuẩn hoá chỉ phải chạy lại
# pha rẻ, không đụng tới pha đắt (PDF mất 274 s).
NORM_TERMS_SCHEMA: Final = pa.schema(
    [
        *TERMS_SCHEMA,
        pa.field("norm_term", pa.string(), nullable=False),
        pa.field("ascii_term", pa.string(), nullable=False),
    ]
)

NORM_SCHEMAS: Final[dict[str, pa.Schema]] = {
    **STAGING_SCHEMAS,
    "terms": NORM_TERMS_SCHEMA,
}

RAW_SUBDIR: Final = "raw"
NORM_SUBDIR: Final = "norm"
