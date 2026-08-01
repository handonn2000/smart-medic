"""H1 — bao đóng truyền ứng của quan hệ IS-A.

Chạy SAU `load` vì nó cần `concept_id`, và nó là **bảng dẫn xuất của store**
đúng nghĩa — cùng loại với index FTS5, nên được dựng ở cùng chỗ.

── Điều chỉnh phạm vi so với kế hoạch ───────────────────────────────────
Kế hoạch §P3.4 đo bao đóng trên đồ thị IS-A của **SNOMED** (383.853 concept,
638.927 cạnh, ~7,6 triệu cặp) và dùng con số đó để kết luận không cần graph DB.

Nhưng Phase 3 đã chốt SNOMED là **nguồn cho, không phải bộ mã thứ ba** — ta
không tạo concept SNOMED nào. Không có concept thì không có `concept_id` để
bao đóng trỏ tới.

May là ba ứng dụng của H1 đều thao tác trên **mã ICD**, và ICD *có sẵn* phân
cấp riêng (16.117 cạnh `isa` nạp từ PDF):
  1. loại ứng viên nằm sai nhánh (khác chương)
  2. rơi về mã cha có cơ sở khi hai ứng viên là anh em ruột (K21.0/K21.9 → K21)
  3. kiểm tra nhất quán giữa các ứng viên top-k

⇒ Bao đóng dựng trên đồ thị IS-A **của chính ICD/RxNorm**, không phải SNOMED.
Nhỏ hơn nhiều, và phục vụ đúng ba mục đích đã nêu. Kết luận "không cần graph
DB" càng đúng hơn.

Thuật toán: sắp xếp topo rồi hợp tập theo thứ tự ngược —
`anc(c) = ⋃ₚ (anc(p) ∪ {p})` với mọi cha `p`. Một lượt O(V+E), chạy trong RAM.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque

ISA = "isa"


def _parents(conn: sqlite3.Connection) -> dict[int, set[int]]:
    out: dict[int, set[int]] = defaultdict(set)
    for src, dst in conn.execute(
        "SELECT src_concept, dst_concept FROM relations WHERE rel = ?", (ISA,)
    ):
        if src != dst:
            out[src].add(dst)
    return out


def _topo_order(parents: dict[int, set[int]]) -> list[int]:
    """Thứ tự topo: cha trước con. Nút trong chu trình bị bỏ lại (xem bên dưới)."""
    children: dict[int, set[int]] = defaultdict(set)
    indeg: dict[int, int] = defaultdict(int)
    nodes = set(parents)
    for child, ps in parents.items():
        indeg[child] = len(ps)
        for p in ps:
            children[p].add(child)
            nodes.add(p)
    for n in nodes:
        indeg.setdefault(n, 0)

    queue = deque(sorted(n for n in nodes if indeg[n] == 0))
    order: list[int] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for ch in sorted(children[n]):
            indeg[ch] -= 1
            if indeg[ch] == 0:
                queue.append(ch)
    return order


def compute(conn: sqlite3.Connection) -> list[tuple[int, int, int]]:
    """Trả về [(ancestor, descendant, min_dist)]."""
    parents = _parents(conn)
    if not parents:
        return []

    order = _topo_order(parents)
    # Nút không nằm trong thứ tự topo là nút thuộc chu trình. Dữ liệu chuẩn
    # không nên có, nhưng nếu có thì BỎ chúng đi còn hơn sinh ra bao đóng có
    # chu trình — cổng `closure_co_chu_trinh` ở validate sẽ bắt được nếu lọt.
    anc_dist: dict[int, dict[int, int]] = {}
    for node in order:
        acc: dict[int, int] = {}
        for p in parents.get(node, ()):
            if p not in anc_dist:
                continue
            acc[p] = min(acc.get(p, 1), 1)
            for a, d in anc_dist[p].items():
                acc[a] = min(acc.get(a, d + 1), d + 1)
        anc_dist[node] = acc

    return [(a, node, d) for node, accs in anc_dist.items() for a, d in accs.items() if a != node]


def build(conn: sqlite3.Connection) -> int:
    """Dựng lại bảng `closure` từ các cạnh `isa` hiện có."""
    rows = compute(conn)
    conn.execute("DELETE FROM closure")
    conn.executemany(
        "INSERT INTO closure (ancestor, descendant, min_dist) VALUES (?, ?, ?)",
        sorted(rows),
    )
    return len(rows)
