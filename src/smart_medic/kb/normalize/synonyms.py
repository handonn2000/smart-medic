"""Tách tên bệnh ghép nhiều cách gọi trong `ICD10.csv`.

Một số ô chứa nhiều tên ngăn bằng dấu phẩy:
    A17.81  "U lao não và tủy sống, Áp xe lao não và tủy sống"
    A18.02  "Lao ở khớp háng, Lao khớp gối, Lao cột sống"
Tách ra thành nhiều synonym tăng recall đáng kể.

Nhưng có tên bệnh **hợp lệ** cũng chứa dấu phẩy:
    "Bệnh trào ngược dạ dày - thực quản, không đặc hiệu"
nên phải có heuristic, và (quyết định D4) **kèm duyệt tay một lần** —
`smk kb extract` in ra toàn bộ ca bị tách để người soát, không tự động mù.
"""

from __future__ import annotations

import re
from typing import Final

# Mảnh bắt đầu bằng các từ này là **bổ nghĩa** cho mảnh trước, không phải
# một tên bệnh độc lập → không được tách.
MODIFIER_PREFIXES: Final = (
    "không",
    "có",
    "chưa",
    "khác",
    "được",
    "kèm",
    "hoặc",
    "và",
    "với",
    "kể cả",
    "loại trừ",
    "bao gồm",
    "phần",
    "biến chứng",
    "thể",
    "giai đoạn",
    "mức độ",
    "nguyên phát",
    "thứ phát",
)

MIN_PART_LEN: Final = 3

_WS: Final = re.compile(r"\s+")


def _is_modifier(part: str) -> bool:
    low = part.lower().lstrip()
    return any(low.startswith(p) for p in MODIFIER_PREFIXES)


def split_synonyms(name: str) -> list[str]:
    """Tách tên ghép thành danh sách tên. Trả `[name]` nếu không tách.

    Chỉ tách khi **mọi** mảnh đều đủ dài và **không mảnh nào** là bổ nghĩa —
    thà bỏ sót còn hơn cắt nhầm tên bệnh, vì tên sai làm hỏng cả retrieval.

    >>> split_synonyms("Lao ở khớp háng, Lao khớp gối")
    ['Lao ở khớp háng', 'Lao khớp gối']
    >>> split_synonyms("Bệnh trào ngược dạ dày, không đặc hiệu")
    ['Bệnh trào ngược dạ dày, không đặc hiệu']
    """
    name = _WS.sub(" ", name).strip()
    if "," not in name:
        return [name]

    parts = [p.strip() for p in name.split(",")]
    if len(parts) < 2:
        return [name]
    if any(len(p) < MIN_PART_LEN for p in parts):
        return [name]
    if any(_is_modifier(p) for p in parts):
        return [name]
    return parts


def was_split(name: str) -> bool:
    """Tên này có bị tách không — dùng để xuất danh sách cho người duyệt."""
    return len(split_synonyms(name)) > 1
