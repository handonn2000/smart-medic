"""Pha 1 — raw → staging/raw/*.parquet.

Pha ĐẮT (PDF mất ~274 s, RRF/RF2 vài phút) nên có cache theo checksum nguồn:
chỉ chạy lại khi file thô đổi, hoặc khi ép bằng `--force`.

Extractor không biết pyarrow: nó trả `StagingBatch` (list[dict]), việc ép kiểu
và ghi parquet tập trung ở đây để hợp đồng chỉ được thực thi tại một chỗ.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from smart_medic.kb import config, staging
from smart_medic.kb.extract.base import Extractor, StagingBatch

__all__ = ["EXTRACTORS", "run", "write_batch"]


def _icd_extractors() -> list[Extractor]:
    from smart_medic.kb.extract.icd_csv import ICDCsvExtractor
    from smart_medic.kb.extract.icd_pdf import ICDPdfExtractor

    return [ICDPdfExtractor(), ICDCsvExtractor()]


def _rxnorm_extractors() -> list[Extractor]:
    from smart_medic.kb.extract.rxnorm_rrf import RxNormExtractor

    return [RxNormExtractor()]


def _snomed_extractors() -> list[Extractor]:
    from smart_medic.kb.extract.snomed_rf2 import SnomedExtractor

    return [SnomedExtractor()]


# Thứ tự trong dict quyết định thứ tự merge ở `load` (nguồn trước thắng khi
# chọn pref_vi/pref_en), nên nó phải ổn định.
EXTRACTORS = {
    "icd": _icd_extractors,
    "rxnorm": _rxnorm_extractors,
    "snomed": _snomed_extractors,
}

# Khoá sắp xếp cho từng bảng — bảo đảm parquet tất định giữa các lần chạy.
SORT_KEYS = {
    "concepts": ["vocab", "code"],
    "terms": ["vocab", "code", "source", "lang", "term"],
    "relations": ["src_vocab", "src_code", "rel", "dst_vocab", "dst_code"],
    "attributes": ["vocab", "code", "attr", "value"],
    "sources": ["source"],
}


def write_batch(batch: StagingBatch, subdir: str = staging.RAW_SUBDIR) -> dict[str, int]:
    """Ghi `StagingBatch` ra parquet, ép đúng schema và sắp xếp tất định."""
    out_dir = config.STAGING_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    for name, schema in staging.STAGING_SCHEMAS.items():
        rows = getattr(batch, name)
        table = pa.Table.from_pylist(rows, schema=schema)
        if table.num_rows:
            table = table.sort_by([(k, "ascending") for k in SORT_KEYS[name]])
        pq.write_table(table, out_dir / f"{name}.parquet", compression="zstd")
        counts[name] = table.num_rows

    return counts


def cache_path() -> Path:
    return config.STAGING_DIR / ".extract-cache.json"


def load_cache() -> dict:
    p = cache_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _select(source: str) -> Iterable[Extractor]:
    keys = list(EXTRACTORS) if source == "all" else [source]
    for key in keys:
        try:
            yield from EXTRACTORS[key]()
        except ImportError:
            # Nguồn chưa được implement ở phase hiện tại — bỏ qua thay vì nổ,
            # để `--source all` vẫn chạy được khi mở rộng dần từng phase.
            print(f"  ⊘ {key}: extractor chưa có ở phase này, bỏ qua")


def _staging_complete() -> bool:
    raw = config.STAGING_DIR / staging.RAW_SUBDIR
    return all((raw / f"{n}.parquet").is_file() for n in staging.STAGING_SCHEMAS)


def run(*, source: str = "all", force: bool = False) -> dict[str, int]:
    """Chạy các extractor được chọn và ghi staging/raw/. Trả số dòng mỗi bảng."""
    extractors = [ex for ex in _select(source) if ex.available()]

    # Cache theo checksum nguồn: pha này đắt (PDF ~274 s) nên không chạy lại
    # nếu file thô không đổi. Tính sha256 rẻ hơn parse rất nhiều.
    current = {ex.name: ex.fingerprint() for ex in extractors}
    cached = load_cache()
    if not force and _staging_complete() and cached.get("fingerprint") == current:
        print("  ⏭ nguồn thô không đổi — dùng lại staging/raw/ (dùng --force để ép)")
        return cached.get("counts", {})

    batch = StagingBatch()
    splits: list[tuple[str, list]] = []
    rejects: list[tuple[str, list]] = []

    for ex in extractors:
        print(f"  → {ex.name} …", flush=True)
        part = ex.extract()
        batch.extend(part)
        print(f"    {part.counts()}")
        if getattr(ex, "split_report", None):
            splits.append((ex.name, ex.split_report))
        if getattr(ex, "reject_report", None):
            rejects.append((ex.name, ex.reject_report))

    fingerprint = current

    counts = write_batch(batch)
    config.STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(
        json.dumps({"fingerprint": fingerprint, "counts": counts}, indent=2),
        encoding="utf-8",
    )

    # Quyết định D4: tách synonym theo dấu phẩy KÈM DUYỆT TAY — in ra để soát,
    # không tự động mù.
    for name, rows in splits:
        path = config.STAGING_DIR / f"{name}.synonym-splits.tsv"
        with path.open("w", encoding="utf-8") as f:
            f.write("code\toriginal\tparts\n")
            for code, original, parts in rows:
                f.write(f"{code}\t{original}\t{' | '.join(parts)}\n")
        print(f"  ⚠ {name}: {len(rows)} tên bị tách → {path.name} (cần duyệt tay một lần)")

    # Mã bị loại vì sai định dạng. Lọc là đúng, nhưng lọc IM LẶNG thì không —
    # nếu nguồn thô đổi và số này nhảy vọt, ta phải thấy được.
    for name, rows in rejects:
        path = config.STAGING_DIR / f"{name}.rejected-codes.tsv"
        with path.open("w", encoding="utf-8") as f:
            f.write("code\tname\n")
            for code, label in rows:
                f.write(f"{code}\t{label}\n")
        preview = ", ".join(repr(c) for c, _ in rows[:5])
        print(f"  ⚠ {name}: loại {len(rows)} mã sai định dạng ({preview}) → {path.name}")

    return counts
