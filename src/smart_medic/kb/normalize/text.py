"""Chuẩn hoá chuỗi — HÀM THUẦN, không I/O.

Đây là nơi bug retrieval hay nằm nhất, nên nó phải là nơi dễ test nhất:
mọi thứ ở đây là `str -> str`, test không cần fixture, chạy mili-giây.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")

# Ngắt dòng giữa từ trong ô PDF: "glucose-6-\nphosphate" → sau khi gộp khoảng
# trắng thành "glucose-6- phosphate". Chỉ nối lại khi dấu gạch KHÔNG có khoảng
# trắng phía trước — nhờ vậy gạch nối đúng nghĩa trong tiếng Việt
# ("dạ dày - thực quản", có khoảng trắng hai bên) không bị đụng tới.
_HYPHEN_WRAP = re.compile(r"(?<=[^\s\-])-\s+(?=\S)")

# Ký tự cần gỡ ở hai đầu chuỗi. Không gỡ trong lòng chuỗi vì tên bệnh
# có dấu ngoặc vuông có nghĩa: "Thiếu máu do thiếu men ... [G6PD]".
_TRIM = " \t\r\n.,;:·-–—"

# `đ`/`Đ` KHÔNG phải ký tự tổ hợp nên NFD không tách được — phải map tường minh.
# Bỏ bước này thì "đau đầu" thành "đau đâu": chữ đ còn nguyên, chỉ mất dấu.
_DSTROKE = str.maketrans({"đ": "d", "Đ": "D"})


def to_nfc(s: str) -> str:
    """Chuẩn hoá Unicode về NFC.

    Tiếng Việt có thể được gõ ở dạng tổ hợp (NFD) hoặc dựng sẵn (NFC). Trộn
    hai dạng làm chuỗi trông giống nhau nhưng không bằng nhau, và làm lệch
    offset ký tự — đúng cái bẫy PRD §8 cảnh báo.
    """
    return unicodedata.normalize("NFC", s)


def fix_hyphen_wrap(s: str) -> str:
    """Nối lại từ bị PDF ngắt dòng ngay sau dấu gạch nối.

    >>> fix_hyphen_wrap("glucose-6- phosphate dehydrogenase")
    'glucose-6-phosphate dehydrogenase'
    >>> fix_hyphen_wrap("dạ dày - thực quản")   # gạch nối đúng nghĩa, giữ nguyên
    'dạ dày - thực quản'
    """
    return _HYPHEN_WRAP.sub("-", s)


def normalize_term(s: str) -> str:
    """Dạng dùng để khớp, GIỮ dấu tiếng Việt.

    NFC → lowercase → gộp khoảng trắng → gỡ dấu câu hai đầu.
    """
    s = to_nfc(s).lower()
    s = _WS.sub(" ", s)
    return s.strip(_TRIM)


def to_ascii(s: str) -> str:
    """Bỏ dấu tiếng Việt để tăng recall.

    Dùng cho cột `ascii_term`: retrieve rộng bằng cột này rồi rerank bằng
    `norm_term` (giữ dấu) để lấy lại precision.
    """
    s = to_nfc(s).translate(_DSTROKE)
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped)


def normalize_pair(s: str) -> tuple[str, str]:
    """Tiện ích: trả `(norm_term, ascii_term)` — hai cột luôn đi cùng nhau."""
    norm = normalize_term(s)
    return norm, to_ascii(norm)
