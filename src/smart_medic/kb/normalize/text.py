"""Chuẩn hoá chuỗi — HÀM THUẦN, không I/O.

Đây là nơi bug retrieval hay nằm nhất, nên nó phải là nơi dễ test nhất:
mọi thứ ở đây là `str -> str`, test không cần fixture, chạy mili-giây.
"""

from __future__ import annotations


def to_nfc(s: str) -> str:
    """Chuẩn hoá Unicode về NFC. Tiếng Việt tổ hợp làm lệch offset ký tự."""
    raise NotImplementedError("Phase 1")


def normalize_term(s: str) -> str:
    """Dạng dùng để khớp, GIỮ dấu tiếng Việt: NFC + lowercase + gộp khoảng trắng."""
    raise NotImplementedError("Phase 1")


def to_ascii(s: str) -> str:
    """Bỏ dấu tiếng Việt.

    Bẫy kinh điển: `đ`/`Đ` KHÔNG phải ký tự tổ hợp nên NFD không tách được —
    phải map tường minh trước khi bỏ dấu, nếu không "đau đầu" thành "đau đâu".
    """
    raise NotImplementedError("Phase 1")
