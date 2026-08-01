"""Quản vòng đời kết nối tới store.

Đây là MỘT trong hai nơi duy nhất được phép `import sqlite3` (nơi kia là `load/`).
Mọi module khác đi qua API ở `query/__init__.py`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.schema.version import SCHEMA_VERSION


class SchemaVersionMismatch(RuntimeError):
    """Artifact được build bởi phiên bản schema khác với code đang chạy."""


class KBStore:
    """Kết nối chỉ-đọc tới `kb.sqlite`.

    Mở ở chế độ read-only để một lỗi lập trình phía downstream không thể
    làm hỏng artifact — KB là dữ liệu dẫn xuất, nhưng build lại tốn phút.
    """

    def __init__(self, path: Path | None = None, *, check_version: bool = True) -> None:
        self.path = path or config.KB_SQLITE
        if not self.path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy artifact KB: {self.path}\nChạy `smk kb build` để dựng."
            )
        self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        if check_version:
            self._check_version()

    def _check_version(self) -> None:
        row = self.conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        found = row["value"] if row else None
        if found != SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                f"Artifact có schema_version={found!r} nhưng code cần {SCHEMA_VERSION!r}. "
                f"Chạy lại `smk kb load`."
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> KBStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
