"""Bóc phần *sig* (chỉ dẫn dùng thuốc) khỏi mention thuốc.

`sig` là phần đơn thuốc nói **cách dùng** — đường dùng, tần suất, điều kiện:
`po`, `bid`, `q6h:prn`, `qhs`. Nó KHÔNG định danh thuốc, nên với bước truy hồi
nó là nhiễu thuần tuý.

★ Vì sao đây không phải tối ưu vặt mà là sửa lỗi
─────────────────────────────────────────────────
Một số tên thuốc viết tắt trong RxNorm chứa **đúng những token đó** như một phần
tên thật:

    zanamivir 5 mg/blstr po inhl rotadisk kit
                         ↑↑

Token `po` hiếm trong index nên IDF của nó rất cao. Mọi mention đơn thuốc đều
chứa `po`, nên BM25 hút chúng về nhóm tên viết tắt này. Đo được: `759471`
(zanamivir) đứng **hạng 1 cho ba truy vấn không liên quan** — amlodipine,
guaifenesin, clonazepam.

Bỏ token sig ở phía TRUY VẤN là đủ để chặn: không có `po` trong truy vấn thì
tên kia không còn được cộng điểm. Không phải build lại index.

Giữ nguyên hàm lượng và dạng bào chế — `10 mg`, `oral tablet` — vì đó chính là
thứ phân biệt các tầng TTY mà đề bài chấm.
"""

from __future__ import annotations

import re

# Đường dùng (route). Chỉ những dạng viết tắt chuẩn trong đơn thuốc.
ROUTE: frozenset[str] = frozenset(
    {"po", "iv", "im", "sq", "sc", "sl", "pr", "pv", "top", "inh", "ng", "gt", "od", "os", "ou"}
)

# Tần suất & điều kiện dùng (frequency).
FREQUENCY: frozenset[str] = frozenset(
    {
        "daily", "bid", "tid", "qid", "qd", "qod", "qhs", "qam", "qpm", "qwk",
        "prn", "stat", "ac", "pc", "hs", "ud", "asdir",
    }
)  # fmt: skip

# `q6h`, `q4h`, `q12h`, `q8hr`…
_QNH = re.compile(r"^q\d+h(r|rs)?$", re.IGNORECASE)

SIG_TOKENS: frozenset[str] = ROUTE | FREQUENCY

# Cắt theo cùng quy tắc với tokenizer `unicode61` của FTS5, nhưng GIỮ dấu hai
# chấm và gạch nối làm ranh giới — `q6h:prn` phải tách thành `q6h` + `prn`.
_SPLIT = re.compile(r"((?:[^\W_]|[̀-ͯ])+)", re.UNICODE)


def is_sig_token(token: str) -> bool:
    """Token có phải chỉ dẫn dùng thuốc không (không phân biệt hoa thường)."""
    t = token.lower()
    return t in SIG_TOKENS or bool(_QNH.match(t))


def strip_sig(text: str) -> str:
    """Bỏ mọi token sig, giữ nguyên phần còn lại và khoảng trắng hợp lý.

    Hàm thuần: không I/O, không state. Bảo toàn thứ tự token.

    >>> strip_sig("aspirin 81 mg po daily")
    'aspirin 81 mg'
    >>> strip_sig("acetaminophen 325-650 mg po q6h:prn")
    'acetaminophen 325-650 mg'
    >>> strip_sig("nystatin oral suspension 5 ml po qid:prn")
    'nystatin oral suspension 5 ml'

    Không đụng tới hàm lượng và dạng bào chế:

    >>> strip_sig("metoprolol succinate xl 50 mg po daily")
    'metoprolol succinate xl 50 mg'

    An toàn khi mention KHÔNG phải đơn thuốc — không có token sig thì trả
    nguyên văn:

    >>> strip_sig("Thiếu men G6PD")
    'Thiếu men G6PD'
    """
    parts = _SPLIT.split(text)
    # `re.split` với nhóm bắt: chỉ số lẻ là token, chỉ số chẵn là phần ngăn cách.
    kept: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1 and is_sig_token(part):
            continue
        kept.append(part)
    return re.sub(r"\s+", " ", "".join(kept).replace(":", " ")).strip(" -:,.")


def strip_sig_if_drug(text: str, vocab: str | None) -> str:
    """Chỉ áp dụng cho nhánh thuốc.

    Cố ý KHÔNG áp cho ICD: vài token sig là chuỗi hai ký tự (`os`, `od`, `pr`)
    có thể trùng âm tiết tiếng Việt trong tên bệnh. Nhánh chẩn đoán không có
    đơn thuốc để bóc, nên không có gì để được mà lại có thứ để mất.

    Nếu bóc xong còn rỗng thì trả lại nguyên văn — thà truy vấn nhiễu còn hơn
    truy vấn rỗng.
    """
    if vocab != "rxnorm":
        return text
    return strip_sig(text) or text
