"""Chuẩn hoá chuỗi — TOÀN HÀM THUẦN, không I/O.

★ Module này KHÔNG được import pyarrow hay bất kỳ dependency nào chỉ có ở image
  `builder`. Lý do: `kb.query.lexical` dùng `normalize.text`, mà import một
  module con sẽ chạy `__init__` của package — nên mọi thứ nặng ở đây sẽ chui
  vào image `runtime` vốn cố tình không cài chúng.

  Phần chạy pha (đọc/ghi parquet) nằm ở `normalize/phase.py` và chỉ được nạp
  khi thật sự cần. `tests/integration/test_runtime_isolation.py` canh bất biến
  này — nó chính là test đã phát hiện rò rỉ.
"""

from __future__ import annotations

__all__ = ["run"]


def run() -> dict[str, int]:
    """staging/raw/ → staging/norm/. Nạp muộn để giữ `__init__` sạch."""
    from smart_medic.kb.normalize.phase import run as _run

    return _run()
