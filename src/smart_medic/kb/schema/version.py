"""Phiên bản schema của store.

Tăng khi `ddl.sql` đổi theo cách không tương thích ngược. Giá trị này được ghi
vào `schema_meta` trong artifact và vào `manifest.json`, để phát hiện ngay
trường hợp artifact cũ gặp code mới.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final = "1.0.0"

DDL_PATH: Final = Path(__file__).with_name("ddl.sql")


def read_ddl() -> str:
    """Trả về nội dung `ddl.sql` — nguồn sự thật duy nhất về cấu trúc store."""
    return DDL_PATH.read_text(encoding="utf-8")
