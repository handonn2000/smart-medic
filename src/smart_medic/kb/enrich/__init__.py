"""Pha 2b — enrichment. staging/norm/ → staging/enrich/.

Chạy giữa `normalize` và `load`. Chỉ SINH THÊM dòng; các dòng authoritative ở
`staging/norm/` không bị đụng tới, nên `DELETE FROM terms WHERE tier !=
'authoritative'` luôn đưa KB về đúng trạng thái Phase 2.

Mỗi nguồn bật/tắt độc lập qua `--only` / `--skip` để đo đóng góp riêng (§P3.3).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from smart_medic.kb import config, staging
from smart_medic.kb.enrich.base import EnrichBatch, Enricher

__all__ = ["ENRICH_DIR", "SOURCES", "run"]

ENRICH_DIR = "enrich"

# Thứ tự cố định để parquet tất định.
ALL_SOURCES = ("curated_vi", "icd_group_rollup", "icd10cm_2027", "snomed_int")

# ★ HAI trong bốn nguồn BỊ TẮT MẶC ĐỊNH vì đo được là CÓ HẠI.
#
# Ablation trên probe set 122 cặp (chi tiết ở docs §10, Phase 3):
#
#       cấu hình              tổng R@1/R@5    KHÓ R@1/R@5
#       ─────────────────────────────────────────────────
#       không enrichment      0,623 / 0,844   0,400 / 0,714
#       chỉ E5                0,828 / 0,959   0,857 / 0,943
#       chỉ E4                0,623 / 0,836   0,400 / 0,714   ← tệ hơn không làm gì
#       chỉ E2                0,623 / 0,844   0,400 / 0,714   ← đóng góp đúng 0
#       E5 + E1               0,836 / 0,975   0,857 / 0,971   ← TỐT NHẤT
#       E5 + E1 + E2          0,828 / 0,967   0,857 / 0,971   ← E2 làm tụt
#
# E4 (`icd_group_rollup`): mọi mã con của cùng một nhóm nhận đúng MỘT chuỗi
#   giống hệt nhau nên BM25 không phân biệt được — đúng rủi ro đã ghi sẵn
#   trong `icd_groups.py`.
# E2 (`icd10cm_2027`): tên tiếng Anh của ICD-10-CM không giúp gì cho probe set
#   vốn 84/122 là mention tiếng Việt, mà lại pha loãng tín hiệu.
#
# Quy tắc §P3.7: không đạt cổng hiệu quả thì BỎ. Code vẫn giữ và bật lại được
# bằng `--only`, để ai có probe set khác (ví dụ nhiều mention tiếng Anh) thì
# đo lại — kết quả âm này gắn với probe set hiện tại, không phải chân lý.
SOURCES = ("curated_vi", "snomed_int")

SORT_KEYS = {
    "sources": ["source"],
    "terms": ["vocab", "code", "source", "lang", "term"],
    "relations": ["src_vocab", "src_code", "rel", "dst_vocab", "dst_code"],
    "attributes": ["vocab", "code", "attr", "value"],
}


def _relative_origin(enricher) -> str | None:
    """Đường dẫn nguồn ở dạng TƯƠNG ĐỐI so với `DATA_DIR`.

    Đường dẫn TUYỆT ĐỐI rò vào artifact sẽ phá tính tái lập giữa các máy:
    `/Users/…/data/curated/vi_synonyms.yaml` trên máy dev vs
    `/app/data/curated/vi_synonyms.yaml` trong container — cùng một file, hai
    chuỗi khác nhau, và artifact khác nhau. Đã bắt được đúng lỗi này khi đối
    chiếu staging giữa build native và build container.
    """
    path = getattr(enricher, "path", None)
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(config.DATA_DIR))
    except ValueError:
        return Path(path).name


def _known_concepts() -> dict[str, set[str]]:
    """{vocab: {code}} từ staging đã chuẩn hoá.

    Enricher chỉ được gắn thêm vào concept ĐÃ CÓ — đó là cách giữ KB tập trung
    vào hai bộ mã được chấm điểm.
    """
    path = config.STAGING_DIR / staging.NORM_SUBDIR / "concepts.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Thiếu {path}. Chạy `smk kb normalize` trước.")
    table = pq.read_table(path, columns=["vocab", "code"])
    out: dict[str, set[str]] = {}
    for vocab, code in zip(
        table.column("vocab").to_pylist(), table.column("code").to_pylist(), strict=True
    ):
        out.setdefault(vocab, set()).add(code)
    return out


def _group_names() -> dict[str, str]:
    """{mã ICD 3 ký tự: tên tiếng Việt} — đầu vào cho E4.

    KHÔNG lọc theo `entity_kind`: phần lớn mã 3 ký tự (`K21`, `J45`, `I10`)
    vừa là nhóm vừa là **mã bệnh hợp lệ**, nên sau khi merge chúng mang
    `entity_kind='disease'`. Lọc theo `icd_group` sẽ chỉ còn lại mã khoảng
    (`A00-B99`) và E4 ra rỗng — đúng lỗi đã gặp ở lần chạy đầu.
    """
    path = config.STAGING_DIR / staging.NORM_SUBDIR / "concepts.parquet"
    table = pq.read_table(path, columns=["vocab", "code", "pref_vi"])
    out: dict[str, str] = {}
    for vocab, code, name in zip(
        table.column("vocab").to_pylist(),
        table.column("code").to_pylist(),
        table.column("pref_vi").to_pylist(),
        strict=True,
    ):
        if vocab == "icd10" and name and "." not in code and "-" not in code:
            out.setdefault(code, name)
    return out


def _build(names: tuple[str, ...]) -> list[Enricher]:
    from smart_medic.kb.enrich.curated import CuratedSynonyms
    from smart_medic.kb.enrich.icd10cm_rollup import Icd10CmRollup
    from smart_medic.kb.enrich.icd_groups import IcdGroupRollup
    from smart_medic.kb.enrich.snomed_terms import SnomedTermDonor

    factory = {
        "curated_vi": CuratedSynonyms,
        "icd_group_rollup": lambda: IcdGroupRollup(_group_names()),
        "icd10cm_2027": Icd10CmRollup,
        "snomed_int": SnomedTermDonor,
    }
    return [factory[n]() for n in names if n in factory]


def run(*, only: str | None = None, skip: str | None = None) -> dict[str, int]:
    names = tuple(only.split(",")) if only else SOURCES
    if skip:
        dropped = set(skip.split(","))
        names = tuple(n for n in names if n not in dropped)

    known = _known_concepts()
    batch = EnrichBatch()

    for enricher in _build(names):
        if not enricher.available():
            print(f"  ⊘ {enricher.name}: nguồn không sẵn sàng, bỏ qua")
            continue
        print(f"  → {enricher.name} …", flush=True)
        part = enricher.enrich(known)
        if part.terms or part.relations or part.attributes:
            part.register_source(
                name=enricher.name,
                release=getattr(enricher, "release", None),
                origin_file=_relative_origin(enricher),
                sha256=enricher.fingerprint() if hasattr(enricher, "fingerprint") else None,
                n_rows=len(part.terms),
            )
        batch.extend(part)
        print(f"    {part.counts()}")
        for label, value in getattr(enricher, "stats", {}).items():
            print(f"      {label}: {value:,}")
        if getattr(enricher, "skipped", None):
            print(f"    ⚠ bỏ {len(enricher.skipped)} mã không có trong KB: {enricher.skipped[:5]}")

    out_dir = config.STAGING_DIR / ENRICH_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in ("sources", "terms", "relations", "attributes"):
        schema = staging.NORM_SCHEMAS[name]
        table = pa.Table.from_pylist(getattr(batch, name), schema=schema)
        if table.num_rows:
            table = table.sort_by([(k, "ascending") for k in SORT_KEYS[name]])
        pq.write_table(table, out_dir / f"{name}.parquet", compression="zstd")
        counts[name] = table.num_rows
    return counts
