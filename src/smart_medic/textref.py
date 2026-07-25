"""TextRef — tầng nền của toàn hệ thống.

Vấn đề (đo được trên corpus): 20/100 file lưu ở dạng NFD — dấu thanh tiếng Việt
là ký tự tổ hợp (combining) riêng. Extractor trả về NFC. ``str.find()`` thất bại
dù mắt thường thấy chuỗi có trong văn bản. File 14: raw 2.672 ký tự vs NFC 2.538
— lệch 134.

Lỗi này KHÔNG ném exception. Nó chỉ âm thầm làm sai ``position`` và mất điểm.
Vì vậy TextRef là tầng nền có test suite riêng, không phải một hàm tiện ích.

Hợp đồng:
    * MỌI so khớp làm trên ``.norm``
    * MỌI ``position`` xuất ra tính trên ``.raw``
    * ``to_raw()`` là cây cầu duy nhất giữa hai thế giới
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .normalize import _fold_group


@dataclass(frozen=True)
class TextRef:
    """Văn bản kèm bản chuẩn hóa và ánh xạ offset hai chiều."""

    raw: str
    norm: str
    #: offset trong norm → offset BẮT ĐẦU của nhóm tương ứng trong raw
    n2r: list[int] = field(repr=False)
    #: offset trong norm → offset KẾT THÚC của nhóm tương ứng trong raw
    n2r_end: list[int] = field(repr=False)

    def to_raw(self, ns: int, ne: int) -> tuple[int, int]:
        """Ánh xạ khoảng [ns, ne) trên norm về khoảng [start, end) trên raw."""
        if not (0 <= ns < ne <= len(self.norm)):
            raise ValueError(f"khoảng norm không hợp lệ: [{ns}, {ne})")
        return self.n2r[ns], self.n2r_end[ne - 1]

    def slice_raw(self, ns: int, ne: int) -> str:
        s, e = self.to_raw(ns, ne)
        return self.raw[s:e]


def build_textref(raw: str) -> TextRef:
    """Dựng TextRef với offset map.

    Thuật toán gom nhóm:
      * một ký tự cơ sở + mọi dấu tổ hợp theo sau  → một nhóm
      * một chuỗi khoảng trắng liên tiếp            → một nhóm (→ một dấu cách)

    Mỗi nhóm sinh ra ≥0 ký tự trong norm; mọi ký tự norm của nhóm đều trỏ về
    cùng cặp (start, end) của nhóm đó trong raw. Nhờ vậy ánh xạ ngược luôn
    đúng kể cả khi NFC gộp nhiều ký tự raw thành một, hoặc khi khoảng trắng
    bị co lại.
    """
    parts: list[str] = []
    n2r: list[int] = []
    n2r_end: list[int] = []

    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch.isspace():
            j = i + 1
            while j < n and raw[j].isspace():
                j += 1
            piece = " "
        else:
            j = i + 1
            while j < n and unicodedata.combining(raw[j]):
                j += 1
            piece = _fold_group(raw[i:j])

        parts.append(piece)
        for _ in piece:
            n2r.append(i)
            n2r_end.append(j)
        i = j

    norm = "".join(parts)

    # norm_text() có .strip() ở cuối — phải cắt map tương ứng để hai đường
    # đi cho kết quả giống hệt nhau (xem normalize.py).
    lead = len(norm) - len(norm.lstrip())
    trail = len(norm) - len(norm.rstrip())
    if lead or trail:
        end = len(norm) - trail
        norm = norm[lead:end]
        n2r = n2r[lead:end]
        n2r_end = n2r_end[lead:end]

    return TextRef(raw=raw, norm=norm, n2r=n2r, n2r_end=n2r_end)


def read_textref(path) -> TextRef:
    """Đọc file UTF-8 strict. Không đoán encoding — hỏng thì báo lỗi to."""
    with open(path, encoding="utf-8") as fh:
        return build_textref(fh.read())
