"""Tiêm nhiễu theo **phân bố đã đo trên `data/test`**, không theo cảm tính.

★ CẠM BẪY MÀ MODULE NÀY TỒN TẠI ĐỂ TRÁNH
─────────────────────────────────────────
LLM viết bệnh án gọn gàng. Văn bản thật thì không. Khoảng cách 0,23 giữa `gold`
(0,667 — bệnh án tự viết) và `gold_real` (0,433 — văn bản thật) chính là giá của
việc hiệu chỉnh trên văn bản sạch rồi đem chấm trên văn bản bẩn.

Số đo trên 100 file `data/test`, đã kiểm lại trong phiên v2 và khớp chính xác:

    không ở dạng NFC          20/100        có gạch đầu dòng    90/100
    có tên thuốc bị che ***   30/100        có mẫu `NHÃN:`      97/100
    CRLF                       0/100        giọng hỏi–đáp       49/100
    độ dài trung vị        1.838 ký tự

★ NFD PHẢI ĐI QUA `DocBuilder.build(transform=…)`
Chuẩn hoá NFD đổi độ dài chuỗi. Áp nó SAU khi đã ghi offset thì mọi span phía
sau lệch — im lặng. Xem docstring `schema.DocBuilder`.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass

# Tỉ lệ đích, đo trên `data/test` (100 file).
P_NFD = 0.20
P_MASK = 0.30
P_BULLET = 0.90
P_LABEL = 0.97
P_QA_VOICE = 0.49
LEN_MEDIAN = 1838
MASK_LEN_MEDIAN = 12

# Rác OCR/splice — có thật ở `gold_real`, dựng bằng **biến đổi cơ học** chuỗi có
# sẵn, không chép nguyên văn cụm nào từ bộ gold (nó là cổng).
_OCR_SWAPS = str.maketrans({"ổ": "ô", "ậ": "â", "ệ": "ê", "ị": "i", "ầ": "â"})


@dataclass(slots=True)
class DocNoise:
    """Quyết định nhiễu cho MỘT tài liệu. Rút một lần rồi dùng suốt tài liệu."""

    nfd: bool
    bullets: bool
    labels: bool
    qa_voice: bool
    # ★ Che thuốc là tính chất của TÀI LIỆU, không phải của từng mention.
    #   Số đo thật: 30/100 **file** có `***` (99 lần xuất hiện trên 30 file).
    #   Rút theo mention thì 83% tài liệu dính ít nhất một lần che — lệch
    #   +52,6 điểm phần trăm, đo được ở mẻ sinh đầu tiên.
    mask_drugs: bool

    @classmethod
    def draw(cls, rng: random.Random) -> DocNoise:
        return cls(
            nfd=rng.random() < P_NFD,
            bullets=rng.random() < P_BULLET,
            labels=rng.random() < P_LABEL,
            qa_voice=rng.random() < P_QA_VOICE,
            mask_drugs=rng.random() < P_MASK,
        )

    def transform(self, s: str) -> str:
        """Phép biến đổi mức KÝ TỰ, áp lên từng mảnh trong `DocBuilder.build`.

        Chỉ chứa thứ **không đổi ranh giới mảnh**. NFD thoả: nó chỉ tách ký tự
        thành ký tự nền + dấu tổ hợp, không bao giờ gộp qua biên mảnh.
        """
        return unicodedata.normalize("NFD", s) if self.nfd else s


def mask_token(rng: random.Random) -> str:
    """Token thuốc bị che. Độ dài trung vị 12 — đo trên 99 lần xuất hiện thật."""
    n = max(4, int(rng.gauss(MASK_LEN_MEDIAN, 4)))
    return "*" * n


def ocr_junk(rng: random.Random, source: str) -> str:
    """Rác OCR/splice sinh bằng biến đổi cơ học, KHÔNG chép từ bộ gold.

    Hai hiện tượng thật quan sát được: dấu tiếng Việt bị đọc sai thành dấu khác
    (`"Tổn thương"` → `"Tô thương"`), và một cụm bị lặp lại do lỗi ghép trang.
    """
    if rng.random() < 0.5:
        return source.translate(_OCR_SWAPS)
    return f"{source} {source}"
