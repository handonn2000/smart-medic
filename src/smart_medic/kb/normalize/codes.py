"""Chuẩn hoá và kiểm tra mã ICD-10.

Quy ước dagger/asterisk của WHO:
  `†` mã **nguyên nhân / bệnh nền** — dùng làm bệnh chính
  `*` mã **biểu hiện tại cơ quan** — mã phụ

Tên bệnh thường mang sẵn tham chiếu chéo trong ngoặc:
  `A06.4†  "Amoebic liver abscess (K77.0*)"`
Chuỗi ngoặc này phải được gỡ khỏi `term` (nếu để lại sẽ nhiễu BM25 và
embedding) và chuyển thành quan hệ `manifests_as`.
"""

from __future__ import annotations

import re
from typing import Final

# Mã bệnh WHO/BYT: 1 chữ cái + 2 số, tuỳ chọn `.` + 1–2 số.
# BYT có mã mở rộng 5 ký tự (A06.81) nên phần thập phân cho phép 2 chữ số.
ICD_CODE_RE: Final = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,2})?$")

# Mã nhóm/khối: A00-B99, A92-A99 …
ICD_RANGE_RE: Final = re.compile(r"^[A-Z]\d{2}-[A-Z]\d{2}$")

# Tham chiếu chéo asterisk trong tên bệnh: "(K77.0*)"
CROSSREF_RE: Final = re.compile(r"\s*\(\s*([A-Z]\d{2}(?:\.\d{1,2})?)\s*\*\s*\)")

DAGGER: Final = "†"
ASTERISK: Final = "*"


def strip_marker(code: str) -> tuple[str, str | None]:
    """Tách mã trần khỏi ký hiệu dagger/asterisk.

    >>> strip_marker("A06.4†")
    ('A06.4', 'dagger')
    >>> strip_marker("K77.0*")
    ('K77.0', 'asterisk')
    >>> strip_marker("K21.0")
    ('K21.0', None)
    """
    c = code.strip()
    if c.endswith(DAGGER):
        return c[:-1].strip(), "dagger"
    if c.endswith(ASTERISK):
        return c[:-1].strip(), "asterisk"
    return c, None


def is_disease_code(code: str) -> bool:
    """Mã bệnh hợp lệ (đã strip dagger/asterisk)."""
    return bool(ICD_CODE_RE.match(code))


def is_range_code(code: str) -> bool:
    """Mã chương/khối dạng khoảng."""
    return bool(ICD_RANGE_RE.match(code))


def parent_code(code: str) -> str | None:
    """Mã cha trực tiếp trong phân cấp ICD.

    A17.83 → A17.8 → A17 → None

    Cho phép rơi về mã ít đặc hiệu hơn khi retrieval lưỡng lự — an toàn hơn
    đoán bừa dưới Jaccard.
    """
    if "." not in code:
        return None
    head, tail = code.split(".", 1)
    return f"{head}.{tail[:-1]}" if len(tail) > 1 else head


def split_crossref(name: str) -> tuple[str, list[str]]:
    """Gỡ tham chiếu asterisk khỏi tên bệnh.

    >>> split_crossref("Amoebic liver abscess (K77.0*)")
    ('Amoebic liver abscess', ['K77.0'])
    """
    refs = CROSSREF_RE.findall(name)
    return (CROSSREF_RE.sub("", name).strip() if refs else name.strip(), refs)
