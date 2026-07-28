"""Locate — định vị chuỗi span trên văn bản gốc.

Luật cứng (system design §4.2): Extractor KHÔNG được trả position. Nó trả chuỗi
span; tầng này tự tính offset trên chuỗi thô. Span không định vị được thì LOẠI
BỎ, không đoán. Tỉ lệ đo được: 1/472 span bị loại vì LLM diễn giải thay vì trích
nguyên văn.

Hai bẫy đã gặp thật, cả hai xử lý ở đây:
  * lệch NFC → so khớp trên norm, trả offset trên raw (qua TextRef)
  * span lặp lại → con trỏ đẩy qua HẾT độ dài match, không phải +1
"""

from __future__ import annotations

from ..normalize import norm_text
from ..schema import Span
from ..textref import TextRef


class Locator:
    """Định vị span, theo dõi vị trí đã dùng để mention thứ n khớp lần thứ n."""

    def __init__(self, tref: TextRef) -> None:
        self.tref = tref
        self._cursor: dict[str, int] = {}
        self.method: str = ""

    def locate(self, text: str) -> Span | None:
        needle = norm_text(text)
        if not needle:
            return None

        hay = self.tref.norm
        start_from = self._cursor.get(needle, 0)

        ns = hay.find(needle, start_from)
        method = "nth_occurrence" if start_from else "exact"
        if ns < 0:                    # hết lượt → quay lại từ đầu
            ns = hay.find(needle)
            method = "wrapped"
        if ns < 0:
            return None

        ne = ns + len(needle)
        self._cursor[needle] = ne     # đẩy qua hết match, KHÔNG phải +1

        rs, re_ = self.tref.to_raw(ns, ne)
        span = Span(rs, re_, self.tref.raw[rs:re_])
        if not span.verify(self.tref.raw):
            return None               # bất biến vỡ → loại, không đoán
        self.method = method
        return span


def dedupe_overlaps(spans: list[Span]) -> list[Span]:
    """Giữ span dài nhất khi chồng lấn; ưu tiên xuất hiện sớm khi bằng nhau."""
    ordered = sorted(spans, key=lambda s: (-(s.end - s.start), s.start))
    kept: list[Span] = []
    for s in ordered:
        if not any(s.overlaps(k) for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)
