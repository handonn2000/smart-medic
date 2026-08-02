"""Chọn tập span KHÔNG chồng lấn có tổng trọng số lớn nhất.

★ VÌ SAO PHẢI CÓ MỘT TẦNG RIÊNG, KHÔNG NỐI THÊM MỘT MẮT XÍCH
─────────────────────────────────────────────────────────────
Pipeline cũ là chuỗi detector nối tiếp, mỗi cái nhận `taken` rồi tự tránh chồng
lấn: `ner.detect` → `labtest.detect` → `detect_masked_drugs`. Với ba detector
luật thì thứ tự đó còn biện hộ được (đặc hiệu trước, tổng quát sau). Thêm một
model vào thì **thứ tự quyết định thắng thua**, mà thứ tự thì không có căn cứ đo
được — nó chỉ là dòng nào viết trước trong `annotate()`.

Tách ra thì xung đột span thành bài toán tối ưu có lời giải đúng:

    cho N khoảng có thể chồng lấn, mỗi khoảng một trọng số,
    chọn tập con KHÔNG chồng lấn có TỔNG TRỌNG SỐ lớn nhất

Đây đúng là **weighted interval scheduling** (Kleinberg & Tardos, *Algorithm
Design*, §6.1). Quy hoạch động O(n log n), nghiệm tối ưu toàn cục, tất định.

Ba thứ được thêm nhờ tách tầng:
  1. đổi trọng số đo được độc lập với đổi proposer;
  2. bất biến 2 của bài nộp (không chồng lấn) thành **đúng theo kiến tạo**;
  3. thêm/bớt proposer không phải đụng code cũ.

★ TẤT ĐỊNH LÀ YÊU CẦU, KHÔNG PHẢI MONG MUỐN
────────────────────────────────────────────
Cùng đầu vào phải cho cùng đầu ra, **kể cả khi thứ tự proposer đảo**. Không có
tính chất đó thì `smk eval compare` mất ý nghĩa: Δ đo được có thể chỉ là thứ tự
duyệt đổi. Nên mọi hoà điểm đều tie-break bằng khoá tường minh
`(start, end, type, proposer)`, và danh sách đầu vào được sắp chuẩn trước.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from smart_medic.stages.scoring import Entity


@dataclass(frozen=True, slots=True)
class Proposal:
    """Một span do MỘT proposer đề xuất. Bất biến để không ai sửa sau khi nộp."""

    start: int
    end: int
    type: str
    text: str
    weight: float
    proposer: str
    candidates: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_entity(self) -> Entity:
        return Entity(
            text=self.text,
            type=self.type,
            start=self.start,
            end=self.end,
            candidates=self.candidates,
            assertions=self.assertions,
        )

    def sort_key(self) -> tuple:
        """Khoá sắp chuẩn — quyết định tất định khi hoà điểm."""
        return (self.end, self.start, self.type, self.proposer)


def select(proposals: list[Proposal]) -> list[Entity]:
    """Weighted interval scheduling. Trả span đã sắp theo vị trí.

    Hai khoảng KỀ NHAU (`a.end == b.start`) không chồng lấn — khớp đúng định
    nghĩa của `solve.check_invariants`.

    >>> p = lambda s, e, w: Proposal(s, e, "THUỐC", "x", w, "test")
    >>> [ (e.start, e.end) for e in select([p(0, 10, 1.0), p(5, 8, 5.0)]) ]
    [(5, 8)]
    >>> [ (e.start, e.end) for e in select([p(0, 5, 1.0), p(5, 9, 1.0)]) ]
    [(0, 5), (5, 9)]
    """
    if not proposals:
        return []
    items = sorted(proposals, key=Proposal.sort_key)
    ends = [p.end for p in items]

    # p(j): chỉ số cuối cùng có `end <= items[j].start`. `ends` đã tăng dần nên
    # bisect chạy được — đây là chỗ O(n log n) thay cho O(n²) quét lùi.
    best = [0.0] * (len(items) + 1)
    for j, it in enumerate(items, 1):
        take = it.weight + best[bisect_right(ends, it.start, 0, j - 1)]
        best[j] = max(take, best[j - 1])

    chosen: list[Proposal] = []
    j = len(items)
    while j > 0:
        it = items[j - 1]
        prev = bisect_right(ends, it.start, 0, j - 1)
        if it.weight + best[prev] >= best[j - 1]:
            chosen.append(it)
            j = prev
        else:
            j -= 1
    return [p.to_entity() for p in sorted(chosen, key=lambda p: (p.start, p.end))]
