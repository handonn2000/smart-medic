"""Chuẩn hóa chuỗi — MỘT nguồn sự thật duy nhất.

Nguyên tắc sống còn (system design §5.2): hàm normalize phải là một mẩu code
duy nhất, dùng chung lúc build KB và lúc query. Tách đôi là sinh skew — alias
trong index chuẩn hóa kiểu A, mention lúc chạy chuẩn hóa kiểu B, không bao giờ
khớp và rất khó phát hiện vì không có exception nào được ném.

Cưỡng chế bằng test: tests/test_textref.py khẳng định
    build_textref(s).norm == norm_text(s)
với mọi chuỗi, kể cả toàn bộ 100 file corpus. Nếu hai đường đi lệch nhau,
test đỏ ngay.

NORMALIZER_VERSION được ghi vào MANIFEST.json của KB. Pipeline từ chối chạy
nếu KB được build bằng version khác.
"""

from __future__ import annotations

import unicodedata

NORMALIZER_VERSION = 1

# Biến thể gạch ngang gộp về '-'. Chỉ ánh xạ 1 ký tự → 1 ký tự để không phá
# offset map. Tên bệnh ICD dùng '–' (en dash) rất nhiều, ví dụ:
# "trào ngược dạ dày – thực quản".
_DASHES = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
}

# Dấu tiếng Việt → không dấu, dùng cho trường fuzzy fallback (alias_nodiac).
_VN_BASE = str.maketrans(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ",
    "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd",
)


def _fold_group(piece: str) -> str:
    """Chuẩn hóa một nhóm ký tự: NFC → casefold → gộp gạch ngang."""
    piece = unicodedata.normalize("NFC", piece).casefold()
    return "".join(_DASHES.get(ch, ch) for ch in piece)


def norm_text(s: str) -> str:
    """Chuẩn hóa chuỗi (không cần offset). Dùng cho alias trong KB.

    Phải cho kết quả GIỐNG HỆT ``build_textref(s).norm``. Xem docstring module.
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            out.append(" ")
            i = j
            continue
        j = i + 1
        while j < n and unicodedata.combining(s[j]):
            j += 1
        out.append(_fold_group(s[i:j]))
        i = j
    return "".join(out).strip()


def nodiac(s: str) -> str:
    """Bỏ dấu tiếng Việt. Chỉ dùng cho fuzzy fallback, không dùng để tra chính."""
    return unicodedata.normalize("NFC", s).casefold().translate(_VN_BASE)


# --- Nhánh RxNorm (tiếng Anh) -------------------------------------------------

_UNIT_CANON = {
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "mcg": "mcg", "microgram": "mcg", "ug": "mcg",
    "g": "g", "gram": "g", "grams": "g",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "unt": "unt", "unit": "unt", "units": "unt",
    "meq": "meq", "mmol": "mmol", "l": "l",
}

_FORM_CANON = {
    "tab": "tablet", "tabs": "tablet", "tablets": "tablet",
    "cap": "capsule", "caps": "capsule", "capsules": "capsule",
    "soln": "solution", "sol": "solution", "solutions": "solution",
    "susp": "suspension", "inj": "injection", "injectable": "injection",
    "er": "extended release", "xl": "extended release", "sr": "extended release",
}


def norm_drug(s: str) -> str:
    """Chuẩn hóa chuỗi thuốc tiếng Anh: đơn vị + dạng bào chế về dạng chuẩn.

    Khác norm_text() vì hai kho mã bất đối xứng ngôn ngữ: ICD là Việt→Việt,
    RxNorm là Anh→Anh (system design §5.2).
    """
    base = norm_text(s)
    toks = base.replace("/", " / ").split()
    out = []
    for t in toks:
        out.append(_FORM_CANON.get(t, _UNIT_CANON.get(t, t)))
    return " ".join(out)
