"""Chuẩn hoá hàm lượng, đơn vị và số — chủ yếu cho nhánh THUỐC.

Bẫy đáng chú ý: **tiếng Việt dùng dấu phẩy làm dấu thập phân**. Trong đề bài
kết quả xét nghiệm ghi `WBC: 14,43`, trong khi RxNorm ghi `0.4 MG/ML`. Không
được đổi `,` → `.` vô điều kiện vì `1,000` ở nguồn tiếng Anh nghĩa là một nghìn.
"""

from __future__ import annotations

import re
from typing import Final

# Dấu phẩy thập phân kiểu Việt: đúng 1–2 chữ số sau dấu phẩy, và KHÔNG có
# chữ số nào nữa liền sau. Loại được `1,000` (phân tách hàng nghìn kiểu Anh).
_VN_DECIMAL: Final = re.compile(r"(?<=\d),(?=\d{1,2}(?!\d))")

# Khoảng trắng giữa số và đơn vị: "81mg" → "81 mg"
_NUM_UNIT: Final = re.compile(r"(?<=\d)\s*(mg|ml|mcg|g|iu|meq|mmol|%)\b", re.IGNORECASE)

_WS: Final = re.compile(r"\s+")

UNIT_CANON: Final = {
    "mg/ml": "mg/ml",
    "mg": "mg",
    "ml": "ml",
    "mcg": "mcg",
    "ug": "mcg",
    "µg": "mcg",
    "g": "g",
    "iu": "iu",
    "meq": "meq",
    "mmol": "mmol",
}


def vn_decimal_to_dot(s: str) -> str:
    """Đổi dấu phẩy thập phân kiểu Việt sang dấu chấm.

    >>> vn_decimal_to_dot("WBC: 14,43")
    'WBC: 14.43'
    >>> vn_decimal_to_dot("1,000 mg")     # phân tách hàng nghìn — giữ nguyên
    '1,000 mg'
    """
    return _VN_DECIMAL.sub(".", s)


def normalize_units(s: str) -> str:
    """Hạ chữ thường đơn vị và chèn khoảng trắng giữa số với đơn vị.

    >>> normalize_units("Aspirin 81MG Oral Tablet")
    'Aspirin 81 mg Oral Tablet'
    >>> normalize_units("Chlorpheniramine 0.4 MG/ML")
    'Chlorpheniramine 0.4 mg/ML'
    """
    s = _NUM_UNIT.sub(lambda m: " " + m.group(1).lower(), s)
    return _WS.sub(" ", s).strip()


def normalize_dosage(s: str, *, lang: str = "en") -> str:
    """Chuẩn hoá đầy đủ cho chuỗi có hàm lượng.

    `lang='vi'` mới đổi dấu phẩy thập phân — nguồn tiếng Anh (RxNorm) dùng
    dấu phẩy để phân tách hàng nghìn nên đổi là sai.
    """
    if lang == "vi":
        s = vn_decimal_to_dot(s)
    return normalize_units(s)
