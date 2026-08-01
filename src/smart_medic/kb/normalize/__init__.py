"""Pha 2 — staging/raw/ → staging/norm/.

Pha RẺ. Chỉ `terms` đổi hình (thêm `norm_term`, `ascii_term`); bảng khác chép
nguyên. Tách khỏi `extract` để chỉnh luật chuẩn hoá không phải chạy lại pha đắt.

Toàn bộ logic nằm ở các module con dưới dạng **hàm thuần** — đó là lý do
`normalize/` có coverage cao nhất trong repo: nơi bug retrieval hay nằm nhất
phải là nơi dễ test nhất.
"""

from __future__ import annotations

import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from smart_medic.kb import config, staging
from smart_medic.kb.normalize.dosage import normalize_dosage
from smart_medic.kb.normalize.text import normalize_pair, to_nfc

__all__ = ["run"]

# Bộ mã có hàm lượng trong tên → cần chuẩn hoá đơn vị trước khi khớp.
_DOSAGE_VOCABS = {"rxnorm"}


def _normalize_terms(table: pa.Table) -> pa.Table:
    vocabs = table.column("vocab").to_pylist()
    langs = table.column("lang").to_pylist()
    terms = table.column("term").to_pylist()

    raw_out, norm_out, ascii_out = [], [], []
    for vocab, lang, term in zip(vocabs, langs, terms, strict=True):
        text = to_nfc(term)
        if vocab in _DOSAGE_VOCABS:
            text = normalize_dosage(text, lang=lang)
        norm, ascii_ = normalize_pair(text)
        # `norm_term` rỗng sẽ làm FTS5 bỏ qua dòng — rơi về chuỗi gốc đã NFC.
        raw_out.append(text)
        norm_out.append(norm or text.lower())
        ascii_out.append(ascii_ or text.lower())

    return (
        table.set_column(table.schema.get_field_index("term"), "term", pa.array(raw_out))
        .append_column("norm_term", pa.array(norm_out))
        .append_column("ascii_term", pa.array(ascii_out))
    )


def run() -> dict[str, int]:
    src = config.STAGING_DIR / staging.RAW_SUBDIR
    dst = config.STAGING_DIR / staging.NORM_SUBDIR
    if not src.is_dir():
        raise FileNotFoundError(f"Chưa có staging thô: {src}. Chạy `smk kb extract` trước.")
    dst.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for name in staging.STAGING_SCHEMAS:
        src_file = src / f"{name}.parquet"
        dst_file = dst / f"{name}.parquet"
        if name != "terms":
            shutil.copyfile(src_file, dst_file)
            counts[name] = pq.read_metadata(dst_file).num_rows
            continue

        table = pq.read_table(src_file)
        out = _normalize_terms(table).cast(staging.NORM_TERMS_SCHEMA)
        pq.write_table(out, dst_file, compression="zstd")
        counts[name] = out.num_rows

    return counts
