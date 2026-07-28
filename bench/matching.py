"""Ghép mention pred ↔ gold.

Hai chiến lược, và chênh lệch giữa chúng là một đại lượng cần đo chứ không phải
chi tiết cài đặt:

* ``match_greedy`` — sắp IoU giảm dần rồi lấy tham lam. Đây là cách
  ``smart_medic.score`` làm và **nhiều khả năng là cách BTC làm**, nên nó là
  con số dùng để báo cáo.
* ``match_hungarian`` — cực đại hóa **tổng** IoU bằng thuật toán
  Kuhn–Munkres (shortest augmenting path, O(n³)). Đây là biên trên đúng nghĩa.

Greedy không tối ưu: gold ``[0,10]`` với pred ``[0,9]`` (IoU 0,90) và pred
``[0,10]`` (IoU 1,00) cùng gold thứ hai ``[0,9]`` — greedy lấy cặp 1,00 trước
rồi buộc gold hai ghép với ``[0,9]``… Trường hợp ngược lại làm greedy mất một
cặp hoàn hảo. Chênh lệch greedy↔Hungarian trên corpus thật là **thước đo mức
nhạy của điểm với cách ghép**; nếu nó lớn thì mọi kết luận A/B đều mong manh.
"""

from __future__ import annotations

Pair = tuple[int | None, int | None]


def iou(a: dict, b: dict) -> float:
    """IoU trên trục ký tự của hai ``position``."""
    (s1, e1), (s2, e2) = a["position"], b["position"]
    inter = max(0, min(e1, e2) - max(s1, s2))
    union = max(e1, e2) - min(s1, s2)
    return inter / union if union > 0 else 0.0


def _finish(gold_n: int, pred_n: int, pairs: list[Pair]) -> list[Pair]:
    """Bổ sung các mention lẻ (không ghép được) vào danh sách cặp."""
    used_g = {g for g, _ in pairs if g is not None}
    used_p = {p for _, p in pairs if p is not None}
    out = list(pairs)
    out.extend((i, None) for i in range(gold_n) if i not in used_g)
    out.extend((None, j) for j in range(pred_n) if j not in used_p)
    return out


def match_greedy(gold: list[dict], pred: list[dict], *, min_iou: float = 0.0) -> list[Pair]:
    """Tham lam theo IoU giảm dần — tương thích ``smart_medic.score``."""
    scored = sorted(
        (
            (iou(g, p), gi, pi)
            for gi, g in enumerate(gold)
            for pi, p in enumerate(pred)
        ),
        key=lambda x: (-x[0], x[1], x[2]),  # tie-break tất định
    )
    used_g: set[int] = set()
    used_p: set[int] = set()
    pairs: list[Pair] = []
    for value, gi, pi in scored:
        if value <= min_iou or gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        pairs.append((gi, pi))
    return _finish(len(gold), len(pred), pairs)


def match_hungarian(gold: list[dict], pred: list[dict], *, min_iou: float = 0.0) -> list[Pair]:
    """Cực đại hóa tổng IoU (Kuhn–Munkres, shortest augmenting path).

    Cài trên ma trận chữ nhật ``n_gold × n_pred`` với chi phí ``-IoU``; các cặp
    có IoU ≤ ``min_iou`` bị loại sau khi giải, vì ghép hai mention không chồng
    lấn nhau không có nghĩa gì về mặt bài toán.
    """
    n, m = len(gold), len(pred)
    if n == 0 or m == 0:
        return _finish(n, m, [])

    cost = [[-iou(g, p) for p in pred] for g in gold]
    transposed = n > m
    if transposed:  # thuật toán bên dưới yêu cầu n ≤ m
        cost = [[cost[i][j] for i in range(n)] for j in range(m)]
        n, m = m, n

    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)   # p[j] = hàng đang ghép với cột j
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    pairs: list[Pair] = []
    for j in range(1, m + 1):
        if p[j] == 0:
            continue
        gi, pi = (p[j] - 1, j - 1) if not transposed else (j - 1, p[j] - 1)
        if iou(gold[gi], pred[pi]) > min_iou:
            pairs.append((gi, pi))
    return _finish(len(gold), len(pred), pairs)


MATCHERS = {"greedy": match_greedy, "hungarian": match_hungarian}
