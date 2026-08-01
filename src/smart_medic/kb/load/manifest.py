"""`manifest.json` — đi kèm mọi artifact.

Mọi mốc thời gian nằm ở ĐÂY chứ không nằm trong `kb.sqlite`, để file .sqlite
giữ được tính tất định byte-level (mục tiêu G2). Nhờ vậy câu hỏi "KB này build
từ đâu, có khớp code không" trả lời được trong một giây — cần cho debug điểm
số lẫn cho việc nộp BTC.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.schema.version import SCHEMA_VERSION


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# Truy vấn dựng checksum NỘI DUNG. Sắp xếp tường minh ở mọi bảng để kết quả
# không phụ thuộc thứ tự lưu trữ vật lý.
_CONTENT_SQL = {
    "sources": "SELECT source,release,origin_file,sha256,n_rows FROM sources ORDER BY source",
    "concepts": "SELECT concept_id,vocab,code,entity_kind,pref_vi,pref_en,is_active "
    "FROM concepts ORDER BY concept_id",
    "terms": "SELECT concept_id,vocab,source,term,norm_term,ascii_term,lang,term_type,"
    "is_preferred,tier,evidence FROM terms ORDER BY concept_id,source,lang,term_type,term",
    "relations": "SELECT src_concept,rel,dst_concept,rel_group,priority,tier,meta "
    "FROM relations ORDER BY src_concept,rel,dst_concept",
    "attributes": "SELECT concept_id,attr,value FROM attributes ORDER BY concept_id,attr,value",
    "closure": "SELECT ancestor,descendant,min_dist FROM closure ORDER BY ancestor,descendant",
}


def content_sha256(db: Path) -> str:
    """Checksum của NỘI DUNG LOGIC, độc lập với bố cục byte của file.

    ★ Vì sao cần cả hai loại checksum:

    `artifact_sha256` (byte) chỉ ổn định trong **cùng một môi trường**. Đo được:
    build native (SQLite 3.51.0) và build container (SQLite 3.46.1) trên cùng
    staging cho ra hai file khác byte nhưng **nội dung sáu bảng giống hệt** —
    hai phiên bản SQLite serialize B-tree và index FTS5 khác nhau.

    Vậy lời cam kết đúng phải là: *cùng môi trường → trùng byte; khác môi trường
    → trùng nội dung*. `content_sha256` là thứ kiểm được vế thứ hai, và nó mới
    là điều thực sự quan trọng — "hai bên có dựng ra cùng một KB không".
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        for name, sql in _CONTENT_SQL.items():
            h.update(name.encode())
            for row in conn.execute(sql):
                h.update(repr(row).encode())
        return h.hexdigest()
    finally:
        conn.close()


def _table_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = ("sources", "concepts", "terms", "relations", "attributes", "closure")
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


def _sources(db: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT source, release, origin_file, sha256, n_rows FROM sources ORDER BY source"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def write(db: Path | None = None, out: Path | None = None) -> dict:
    db = db or config.KB_SQLITE
    out = out or config.KB_MANIFEST
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "builder_image": os.environ.get("SMK_BUILDER_IMAGE"),
        "sources": _sources(db),
        "counts": _table_counts(db),
        "artifact_sha256": sha256_file(db),
        "content_sha256": content_sha256(db),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def read(path: Path | None = None) -> dict:
    path = path or config.KB_MANIFEST
    return json.loads(path.read_text(encoding="utf-8"))
