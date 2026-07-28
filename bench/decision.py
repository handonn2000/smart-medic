"""Tầng quyết định suy ra TỪ metric, không phải từ F1.

Đây là phần có giá trị nhất của benchmark, vì nó cho ra **ngưỡng bằng số** thay
vì trực giác. Hai quyết định chi phối điểm — "có phát mention này không" và
"có gắn mã cho nó không" — đều có nghiệm giải tích dưới công thức của đề, và
nghiệm đó khác xa mặc định F1 mà ai cũng dùng.

──────────────────────────────────────────────────────────────────────────────
1. NGƯỠNG PHÁT MENTION
──────────────────────────────────────────────────────────────────────────────

Với ``unmatched="zero"``, điểm một file là ``S = N / D`` trong đó ``N`` là tổng
chất lượng các cặp khớp và ``D = G + P − M``. Thêm **một** mention dự đoán:

* khớp một gold còn trống (xác suất ``p``) → ``N += q̄`` và ``D`` **không đổi**
  (``P+1`` và ``M+1`` triệt tiêu nhau) ⇒ ``S' = S + q̄/D``;
* thừa (xác suất ``1−p``) → ``N`` không đổi, ``D += 1`` ⇒ ``S' = N/(D+1)``.

    E[ΔS] = p·q̄/D − (1−p)·S/(D+1)  >  0
    ⟺  p·q̄·(D+1) > (1−p)·S·D
    ⟺  p  >  S/(q̄ + S)          (khi D lớn)

**Hệ quả trái trực giác:** ngưỡng tối ưu *tăng theo điểm hiện tại*. Một hệ đang
ở 0,21 nên phát mọi mention mà nó tin ≥ **20%**; chính hệ đó khi lên 0,56 mới
nên nâng bar lên **40%**. Nói cách khác, "thà thiếu còn hơn thừa" là sai ở giai
đoạn đầu và chỉ đúng dần về sau. Đây là ngưỡng **điểm bất động**: phát thêm →
S tăng → ngưỡng tăng → bớt phát; :func:`emission_fixed_point` giải vòng lặp đó.

Đối chiếu: ngưỡng tối ưu F1 luôn là 0,5 bất kể điểm. Dùng 0,5 khi S = 0,21 là
tự bỏ mọi mention có độ tin 20–50% — đúng khoảng chứa phần đuôi dài.

──────────────────────────────────────────────────────────────────────────────
2. KÍCH THƯỚC TẬP CANDIDATES
──────────────────────────────────────────────────────────────────────────────

``candidates_score`` là Jaccard giữa tập dự đoán ``A`` và tập gold ``G``. Với
xác suất biên đã hiệu chuẩn ``p_i = P(mã i ∈ G)`` (giả thiết độc lập),
:func:`expected_jaccard` tính **chính xác** ``E[J]`` bằng quy hoạch động trên
hai phân phối Poisson-binomial (phần trong ``A`` và phần ngoài ``A``), rồi
:func:`best_candidate_set` quét ``k`` để cực đại hóa.

Đo trên ``data/dev_gold_consensus`` (689 mention): |G| ∈ {0, 1} — **không có
mention nào có 2 mã**. Khi gold luôn ≤ 1 phần tử, bài toán rút gọn:

    k = 0  →  E[J] = P(G = ∅)
    k = 1  →  E[J] = p₁
    k = 2  →  E[J] ≤ (p₁ + p₂)/2  <  p₁   (luôn thua k = 1)

⇒ **trả 2 mã là nước đi bị chi phối tuyệt đối**, kể cả lúc "lưỡng lự giữa K21.0
và K21.9". Và quyết định thu về một bất đẳng thức: *phát mã top-1 khi và chỉ
khi ``p₁ > P(gold rỗng)``* — mà ``P(gold rỗng)`` phụ thuộc **type**:

    CHẨN_ĐOÁN : 13/168 rỗng → phát mã khi p₁ > 0,077  (gần như luôn phát)
    THUỐC     : 50/66  rỗng → phát mã khi p₁ > 0,758  (rất khắt khe)

Cùng một pipeline nhưng hai nhánh phải chạy hai ngưỡng lệch nhau **10 lần**.
Một ngưỡng retrieval dùng chung cho cả hai nhánh là sai về nguyên tắc.

Cảnh báo: các con số trên đo trên gold do LLM sinh + đồng thuận, không phải
gold BTC. Hàm :func:`empty_rate_by_type` tính lại chúng từ *bất kỳ* gold nào
bạn đưa vào — đừng hard-code.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass


# ── 1. ngưỡng phát mention ────────────────────────────────────────────────────


def emission_threshold(current_score: float, q_pair: float = 0.85,
                       denominator: float | None = None) -> float:
    """``p*`` — xác suất khớp tối thiểu để việc phát mention có lợi kỳ vọng."""
    if q_pair <= 0:
        return 1.0
    if denominator is None or denominator <= 0:
        return current_score / (q_pair + current_score)
    d = denominator
    return current_score * d / (q_pair * (d + 1) + current_score * d)


def emission_fixed_point(q_pair: float, coverage_at: "callable", *,
                         iters: int = 40, start: float = 0.05) -> tuple[float, float]:
    """Giải điểm bất động ``p* = S(p*)/(q̄ + S(p*))``.

    ``coverage_at(tau)`` trả về ``S`` ước tính khi dùng ngưỡng ``tau`` — thường
    là hàm nội suy từ một lần quét trên dev. Trả ``(p*, S*)``.
    """
    tau = start
    score = coverage_at(tau)
    for _ in range(iters):
        new = emission_threshold(score, q_pair)
        if abs(new - tau) < 1e-6:
            break
        tau = 0.5 * tau + 0.5 * new  # giảm chấn để không dao động
        score = coverage_at(tau)
    return tau, score


# ── 2. tập candidates tối ưu ──────────────────────────────────────────────────


def _poisson_binomial(probs: list[float]) -> list[float]:
    """Phân phối tổng các Bernoulli độc lập. DP O(n²)."""
    dist = [1.0]
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for i, w in enumerate(dist):
            nxt[i] += w * (1.0 - p)
            nxt[i + 1] += w * p
        dist = nxt
    return dist


def expected_jaccard(probs: list[float], k: int) -> float:
    """``E[ |A∩G| / |A∪G| ]`` với ``A`` = top-``k``, ``G`` sinh từ ``probs``.

    Quy ước của đề được tôn trọng: cả hai rỗng → J = 1.
    """
    inside = _poisson_binomial(list(probs[:k]))
    outside = _poisson_binomial(list(probs[k:]))
    total = 0.0
    for a, pa in enumerate(inside):
        if pa == 0.0:
            continue
        for b, pb in enumerate(outside):
            if pb == 0.0:
                continue
            union = k + b
            total += pa * pb * (1.0 if union == 0 else a / union)
    return total


def best_candidate_set_singleton(p_top1: float, p_empty: float) -> tuple[int, float]:
    """Biến thể có RÀNG BUỘC ``|G| ≤ 1`` — đúng với gold đã đo trên dự án này.

    Mô hình độc lập trong :func:`expected_jaccard` cho phép ``|G| = 2`` nên đôi
    khi đề xuất ``k = 2``. Khi biết chắc gold không bao giờ có 2 mã thì chỉ còn
    hai nước:

        k = 0 → E[J] = P(G = ∅) = ``p_empty``
        k = 1 → E[J] = P(mã top-1 đúng) = ``p_top1``

    ⇒ phát mã khi và chỉ khi ``p_top1 > p_empty``. Không có trường hợp nào k = 2
    thắng. Dùng hàm này khi :func:`gold_set_sizes` cho thấy ``max = 1``.
    """
    return (1, p_top1) if p_top1 > p_empty else (0, p_empty)


def best_candidate_set(probs: list[float], *, max_k: int | None = None) -> tuple[int, float]:
    """Chọn ``k`` cực đại hóa ``E[J]``. Trả ``(k, E[J])``.

    ``probs`` phải được sắp giảm dần và **đã hiệu chuẩn** — dùng thẳng softmax
    của reranker mà chưa hiệu chuẩn (Platt/isotonic trên dev) sẽ cho ``k`` sai
    một cách hệ thống, vì softmax quá tự tin.
    """
    probs = sorted(probs, reverse=True)
    upper = len(probs) if max_k is None else min(max_k, len(probs))
    best = (0, expected_jaccard(probs, 0))
    for k in range(1, upper + 1):
        value = expected_jaccard(probs, k)
        if value > best[1] + 1e-12:
            best = (k, value)
    return best


# ── 3. tỉ lệ gold rỗng theo type (đo từ gold thật) ────────────────────────────


@dataclass
class TypePolicy:
    type: str
    n: int
    n_empty: int

    @property
    def empty_rate(self) -> float:
        return self.n_empty / self.n if self.n else 1.0

    @property
    def emit_threshold(self) -> float:
        """Phát mã top-1 khi ``p₁`` vượt ngưỡng này (đúng khi |G| ≤ 1)."""
        return self.empty_rate

    def __str__(self) -> str:
        return (f"{self.type:<22} n={self.n:>4}  gold rỗng {self.n_empty:>4} "
                f"({self.empty_rate:6.1%})  → phát mã khi p₁ > {self.emit_threshold:.3f}")


def empty_rate_by_type(gold: dict[str, list[dict]]) -> dict[str, TypePolicy]:
    """Tính tỉ lệ ``candidates`` rỗng cho từng type, từ gold được cấp."""
    n: dict[str, int] = collections.Counter()
    empty: dict[str, int] = collections.Counter()
    for mentions in gold.values():
        for m in mentions:
            n[m["type"]] += 1
            if not m.get("candidates"):
                empty[m["type"]] += 1
    return {t: TypePolicy(t, n[t], empty[t]) for t in n}


def gold_set_sizes(gold: dict[str, list[dict]]) -> dict[int, int]:
    """Phân phối |G| — nếu chỉ có {0, 1} thì mọi k ≥ 2 đều bị chi phối."""
    out: dict[int, int] = collections.Counter()
    for mentions in gold.values():
        for m in mentions:
            out[len(m.get("candidates") or [])] += 1
    return dict(sorted(out.items()))
