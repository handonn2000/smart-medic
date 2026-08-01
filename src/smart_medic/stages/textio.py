"""Đọc văn bản đầu vào **không làm xê dịch một ký tự nào**.

Đề bài chấm `position = [start, end]` là chỉ số ký tự trên chuỗi input, và
`text_score` dùng WER trên chính đoạn cắt ra từ hai chỉ số đó. Nên mọi phép
biến đổi âm thầm ở bước đọc file đều ăn điểm ở *hai* thành phần cùng lúc.

★ CÁI BẪY ĐÃ THẤY THẬT
──────────────────────
`sample_output.json` của BTC có 19/19 mục lệch offset so với `sample_input.txt`.
Lệch tăng đều +2 mỗi mục danh sách. Tái dựng được chính xác: văn bản gốc là danh
sách đánh số, **mỗi dòng kết thúc bằng `" \\r\\n"`** (dấu cách rồi CRLF).

    tách mục bằng " \\r\\n"  →  khớp 19/19
    tách mục bằng "\\r\\n"   →  khớp  0/19

Python **mặc định bật universal newlines**: `open(p)` biến `\\r\\n` thành `\\n`,
làm ngắn chuỗi đi 1 ký tự cho mỗi dòng. Mọi `position` sau dòng đầu tiên lệch
dần — im lặng, không lỗi, không cảnh báo.

Hai quy tắc, cả hai đều bắt buộc:

1. `newline=""` — không dịch ký tự xuống dòng.
2. **Không** `unicodedata.normalize`. NFC/NFD đổi độ dài chuỗi: đo trên mẫu
   thật, cùng văn bản là 532 ký tự NFC nhưng 582 ký tự NFD. Chuẩn hoá để so
   khớp thì làm trên BẢN SAO, không bao giờ trên chuỗi dùng để tính offset.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

ENCODING = "utf-8"


def read_document(path: Path | str) -> str:
    """Đọc file input, giữ nguyên từng ký tự kể cả `\\r`.

    Dùng hàm này ở MỌI chỗ đọc input của đề. Không gọi `Path.read_text()` —
    nó bật universal newlines.
    """
    with open(path, encoding=ENCODING, newline="") as f:
        return f.read()


def has_crlf(text: str) -> bool:
    """Văn bản có dùng CRLF không — biết để không ngạc nhiên khi debug offset."""
    return "\r\n" in text


def is_nfc(text: str) -> bool:
    """Chuỗi đã ở dạng NFC chưa.

    Không tự sửa: sửa là đổi offset. Chỉ báo để bên gọi tự quyết định.
    """
    return unicodedata.is_normalized("NFC", text)


def slice_span(text: str, start: int, end: int) -> str:
    """Cắt theo đúng quy ước của đề: chỉ số ký tự, nửa mở `[start, end)`."""
    return text[start:end]


def verify_spans(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str, str]]:
    """Đối chiếu `(start, end, text)` với văn bản. Trả về danh sách LỆCH.

    Rỗng nghĩa là mọi span khớp. Dùng trong test và như cổng kiểm tra trước khi
    nộp bài — phát hiện lệch offset ở lúc build, không phải lúc bị chấm điểm.
    """
    bad = []
    for start, end, want in spans:
        got = slice_span(text, start, end)
        if got != want:
            bad.append((start, end, want, got))
    return bad
