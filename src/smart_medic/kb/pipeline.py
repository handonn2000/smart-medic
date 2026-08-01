"""Điều phối 4 pha. CLI chỉ gọi vào đây, không gọi thẳng module con.

Mỗi hàm trả về exit code kiểu Unix: 0 là thành công.
"""

from __future__ import annotations


def run_extract(*, source: str = "all", force: bool = False) -> int:
    raise NotImplementedError("Phase 1")


def run_normalize() -> int:
    raise NotImplementedError("Phase 1")


def run_load(*, out: str | None = None) -> int:
    raise NotImplementedError("Phase 1")


def run_validate(*, db: str | None = None) -> int:
    raise NotImplementedError("Phase 1")


def run_build(*, source: str = "all", force: bool = False) -> int:
    raise NotImplementedError("Phase 1")
