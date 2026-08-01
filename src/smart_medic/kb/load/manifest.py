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
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def read(path: Path | None = None) -> dict:
    path = path or config.KB_MANIFEST
    return json.loads(path.read_text(encoding="utf-8"))
