"""Pha 3 — staging/norm/ → kb.sqlite.

Pha RẺ và chạy lại được, nên đây là điểm chốt cho mục tiêu G3: đổi schema chỉ
phải chạy lại pha này (~1–2 phút) thay vì build từ đầu.

★ Tính tất định byte-level (mục tiêu G2). Bốn điều kiện:
  1. `concept_id` gán bằng sort (vocab, code) — xem `load/ids.py`
  2. Thứ tự INSERT tất định ở mọi bảng
  3. `page_size` cố định và `VACUUM` ở cuối để loại bố cục trang ngẫu nhiên
  4. **KHÔNG có timestamp trong file .sqlite** — mọi mốc thời gian nằm ở
     `manifest.json`. Vì vậy cột `sources.ingested_at` để NULL một cách có chủ đích.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from smart_medic.kb import config, staging
from smart_medic.kb.load.ids import assign_ids, first_non_null, pick_entity_kind
from smart_medic.kb.schema.version import SCHEMA_VERSION, read_ddl

# Thứ tự ưu tiên nguồn khi merge concept trùng mã. PDF trước CSV vì nó có cả
# tên tiếng Việt lẫn tiếng Anh WHO; CSV chỉ có tiếng Việt.
SOURCE_PRIORITY = (
    "icd10_pdf_who",
    "icd10_csv_byt",
    "rxnorm_rrf",
    "snomed_int",
)

PAGE_SIZE = 4096


def _source_rank(source: str) -> tuple[int, str]:
    try:
        return (SOURCE_PRIORITY.index(source), source)
    except ValueError:
        return (len(SOURCE_PRIORITY), source)


def _read(name: str):
    path = config.STAGING_DIR / staging.NORM_SUBDIR / f"{name}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Thiếu {path}. Chạy `smk kb normalize` trước.")
    return pq.read_table(path).to_pylist()


def _merge_concepts(rows: list[dict]) -> list[dict]:
    """Gộp các dòng cùng (vocab, code) đến từ nhiều file thành một concept.

    ICD gộp PDF + ICD10.csv thành MỘT bộ mã (quyết định D3); provenance giữ ở
    mức term nên ở đây chỉ cần chọn giá trị hiển thị một cách tất định.
    """
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["vocab"], r["code"])].append(r)

    merged = []
    for (vocab, code), group in grouped.items():
        group.sort(key=lambda r: _source_rank(r["source"]))
        merged.append(
            {
                "vocab": vocab,
                "code": code,
                "entity_kind": pick_entity_kind(r["entity_kind"] for r in group),
                "pref_vi": first_non_null(r["pref_vi"] for r in group),
                "pref_en": first_non_null(r["pref_en"] for r in group),
                "is_active": any(r["is_active"] for r in group),
            }
        )
    return merged


def build(out_path: Path | None = None) -> dict:
    out_path = out_path or config.KB_SQLITE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.unlink(missing_ok=True)

    concepts = _merge_concepts(_read("concepts"))
    ids = assign_ids((c["vocab"], c["code"]) for c in concepts)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
        conn.executescript(read_ddl())
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )

        stats = {
            "sources": _load_sources(conn),
            "concepts": _load_concepts(conn, concepts, ids),
            "terms": _load_terms(conn, ids),
            "relations": _load_relations(conn, ids),
            "attributes": _load_attributes(conn, ids),
        }

        # FTS5 external-content: dựng index từ bảng `terms` sau khi nạp xong.
        conn.execute("INSERT INTO terms_fts(terms_fts) VALUES ('rebuild')")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    os.replace(tmp_path, out_path)  # atomic: không bao giờ để artifact nửa vời
    return stats


# ── nạp từng bảng ────────────────────────────────────────────────────────


def _load_sources(conn: sqlite3.Connection) -> int:
    rows = sorted(_read("sources"), key=lambda r: r["source"])
    conn.executemany(
        "INSERT INTO sources (source, release, origin_file, sha256, n_rows) "
        "VALUES (:source, :release, :origin_file, :sha256, :n_rows)",
        rows,
    )
    return len(rows)


def _load_concepts(conn: sqlite3.Connection, concepts: list[dict], ids: dict) -> int:
    payload = sorted(
        (
            {
                "concept_id": ids[(c["vocab"], c["code"])],
                "vocab": c["vocab"],
                "code": c["code"],
                "entity_kind": c["entity_kind"],
                "pref_vi": c["pref_vi"],
                "pref_en": c["pref_en"],
                "is_active": int(c["is_active"]),
            }
            for c in concepts
        ),
        key=lambda r: r["concept_id"],
    )
    conn.executemany(
        "INSERT INTO concepts (concept_id, vocab, code, entity_kind, pref_vi, pref_en, is_active) "
        "VALUES (:concept_id, :vocab, :code, :entity_kind, :pref_vi, :pref_en, :is_active)",
        payload,
    )
    return len(payload)


def _load_terms(conn: sqlite3.Connection, ids: dict) -> int:
    rows = _read("terms")
    payload = []
    for r in rows:
        cid = ids.get((r["vocab"], r["code"]))
        if cid is None:
            continue  # term mồ côi: concept bị lọc ở nguồn khác
        payload.append(
            {
                "concept_id": cid,
                "vocab": r["vocab"],
                "source": r["source"],
                "term": r["term"],
                "norm_term": r["norm_term"],
                "ascii_term": r["ascii_term"],
                "lang": r["lang"],
                "term_type": r["term_type"],
                "is_preferred": int(r["is_preferred"]),
                "tier": r["tier"],
                "evidence": r["evidence"],
            }
        )
    payload.sort(key=lambda r: (r["concept_id"], r["source"], r["lang"], r["term_type"], r["term"]))
    conn.executemany(
        "INSERT INTO terms (concept_id, vocab, source, term, norm_term, ascii_term, lang, "
        "term_type, is_preferred, tier, evidence) "
        "VALUES (:concept_id, :vocab, :source, :term, :norm_term, :ascii_term, :lang, "
        ":term_type, :is_preferred, :tier, :evidence)",
        payload,
    )
    return len(payload)


def _load_relations(conn: sqlite3.Connection, ids: dict) -> int:
    payload = []
    for r in _read("relations"):
        src = ids.get((r["src_vocab"], r["src_code"]))
        dst = ids.get((r["dst_vocab"], r["dst_code"]))
        if src is None or dst is None or src == dst:
            continue  # bỏ cạnh mồ côi và tự-vòng
        payload.append(
            {
                "src_concept": src,
                "rel": r["rel"],
                "dst_concept": dst,
                "rel_group": r["rel_group"],
                "priority": r["priority"],
                "tier": r["tier"],
                "meta": r["meta"],
            }
        )
    payload.sort(key=lambda r: (r["src_concept"], r["rel"], r["dst_concept"]))
    conn.executemany(
        "INSERT INTO relations (src_concept, rel, dst_concept, rel_group, priority, tier, meta) "
        "VALUES (:src_concept, :rel, :dst_concept, :rel_group, :priority, :tier, :meta)",
        payload,
    )
    return len(payload)


def _load_attributes(conn: sqlite3.Connection, ids: dict) -> int:
    payload = []
    for r in _read("attributes"):
        cid = ids.get((r["vocab"], r["code"]))
        if cid is None:
            continue
        payload.append({"concept_id": cid, "attr": r["attr"], "value": r["value"]})
    payload.sort(key=lambda r: (r["concept_id"], r["attr"], r["value"] or ""))
    conn.executemany(
        "INSERT INTO attributes (concept_id, attr, value) VALUES (:concept_id, :attr, :value)",
        payload,
    )
    return len(payload)
