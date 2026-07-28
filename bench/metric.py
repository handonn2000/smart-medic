"""Metric của đề, kèm phân rã để biết điểm mất ở đâu.

    final = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score

Phần quan trọng nhất của module này **không** phải ``final`` mà là
:func:`decompose`. Với quy ước ``unmatched="zero"`` (đã được nhánh v4.1 xác nhận
bằng thực nghiệm: quét 12 cách hiểu công thức, ``zero`` lệch 8,2 điểm so với
leaderboard còn ``skip`` lệch 62,8), điểm có dạng tách được:

    final ≈ (0.3·q_text + 0.3·q_assert + 0.4·q_cand) · M / (G + P − M)
            └──────── chất lượng mỗi cặp khớp ────────┘   └─ độ phủ ─┘

Hai thừa số này chịu tác động của **hai nhóm kỹ thuật hoàn toàn khác nhau**:
thừa số phải là NER/recall, thừa số trái là linking/assertion. Báo cáo một con
số ``final`` mà không tách hai thừa số là lý do một đội có thể dành cả tuần tối
ưu retrieval trong khi 70% điểm đang nằm ở chỗ khác.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .matching import MATCHERS, iou

W_TEXT, W_ASSERT, W_CAND = 0.3, 0.3, 0.4


# ── số học cơ bản ─────────────────────────────────────────────────────────────


def wer(ref: str, hyp: str) -> float:
    """Word Error Rate = (thêm + bớt + thay) / số từ đáp án (Levenshtein mức từ)."""
    r, h = ref.split(), hyp.split()
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def jaccard(a, b) -> float:
    """Quy ước của đề: cả hai rỗng → J = 1."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


# ── kết quả ───────────────────────────────────────────────────────────────────


@dataclass
class ComponentScores:
    """Điểm một file, kèm đủ số liệu để phân rã ở mức corpus."""

    text: float
    assertions: float
    candidates: float
    n_gold: int
    n_pred: int
    n_matched: int
    #: chất lượng TRUNG BÌNH TRÊN CÁC CẶP KHỚP (không tính mention lẻ)
    q_text: float = 1.0
    q_assert: float = 1.0
    q_cand: float = 1.0
    #: IoU trung bình của các cặp khớp — đo độ chuẩn của biên span
    q_iou: float = 1.0
    file: str = ""

    @property
    def final(self) -> float:
        return W_TEXT * self.text + W_ASSERT * self.assertions + W_CAND * self.candidates

    @property
    def recall(self) -> float:
        return self.n_matched / self.n_gold if self.n_gold else 1.0

    @property
    def precision(self) -> float:
        return self.n_matched / self.n_pred if self.n_pred else 1.0


@dataclass
class CorpusScores:
    text: float
    assertions: float
    candidates: float
    per_file: list[ComponentScores] = field(default_factory=list)

    @property
    def final(self) -> float:
        return W_TEXT * self.text + W_ASSERT * self.assertions + W_CAND * self.candidates


# ── chấm ──────────────────────────────────────────────────────────────────────


def score_file(
    gold: list[dict],
    pred: list[dict],
    *,
    match: str = "greedy",
    unmatched: str = "zero",
    min_iou: float = 0.0,
    file: str = "",
) -> ComponentScores:
    pairs = MATCHERS[match](gold, pred, min_iou=min_iou)

    ts: list[float] = []
    as_: list[float] = []
    cs: list[float] = []
    qt: list[float] = []
    qa: list[float] = []
    qc: list[float] = []
    qi: list[float] = []

    for gi, pi in pairs:
        if gi is None or pi is None:
            if unmatched == "skip":
                continue
            ts.append(0.0)
            as_.append(0.0)
            cs.append(0.0)
            continue
        g, p = gold[gi], pred[pi]
        t = 1.0 - min(1.0, wer(g["text"], p["text"]))
        a = jaccard(g.get("assertions", []), p.get("assertions", []))
        c = jaccard(g.get("candidates", []), p.get("candidates", []))
        ts.append(t)
        as_.append(a)
        cs.append(c)
        qt.append(t)
        qa.append(a)
        qc.append(c)
        qi.append(iou(g, p))

    mean = lambda v: sum(v) / len(v) if v else 1.0  # noqa: E731
    return ComponentScores(
        text=mean(ts),
        assertions=mean(as_),
        candidates=mean(cs),
        n_gold=len(gold),
        n_pred=len(pred),
        n_matched=sum(1 for g, p in pairs if g is not None and p is not None),
        q_text=mean(qt),
        q_assert=mean(qa),
        q_cand=mean(qc),
        q_iou=mean(qi),
        file=file,
    )


def score_corpus(
    gold: dict[str, list[dict]],
    pred: dict[str, list[dict]],
    *,
    match: str = "greedy",
    unmatched: str = "zero",
    min_iou: float = 0.0,
    keys: list[str] | None = None,
) -> CorpusScores:
    """Trung bình macro theo file — đúng cách đề mô tả (``Σ_i … / len(test)``).

    File có trong gold mà pred thiếu được chấm như pred rỗng, **không** bị bỏ
    qua: bỏ qua sẽ thưởng cho hệ nào crash trên file khó.
    """
    keys = keys if keys is not None else sorted(gold, key=_numkey)
    per = [
        score_file(
            gold[k],
            pred.get(k, []),
            match=match,
            unmatched=unmatched,
            min_iou=min_iou,
            file=k,
        )
        for k in keys
    ]
    mean = lambda f: sum(f(x) for x in per) / len(per) if per else 0.0  # noqa: E731
    return CorpusScores(
        text=mean(lambda x: x.text),
        assertions=mean(lambda x: x.assertions),
        candidates=mean(lambda x: x.candidates),
        per_file=per,
    )


def _numkey(k: str):
    return (int(k), "") if k.isdigit() else (10**9, k)


# ── phân rã ───────────────────────────────────────────────────────────────────


def decompose(corpus: CorpusScores) -> dict[str, float]:
    """Tách ``final`` thành *chất lượng cặp khớp* × *độ phủ*.

    Trả thêm ``final_model`` — giá trị dự đoán bởi công thức xấp xỉ. Chênh lệch
    ``final − final_model`` là mức mà công thức xấp xỉ nói dối; nếu nó nhỏ
    (< 0,02) thì mọi suy luận biên dựa trên công thức đó dùng được, nếu lớn thì
    không.
    """
    per = corpus.per_file
    if not per:
        return {}
    n = len(per)
    G = sum(x.n_gold for x in per)
    P = sum(x.n_pred for x in per)
    M = sum(x.n_matched for x in per)

    matched_weight = sum(x.n_matched for x in per) or 1
    wmean = lambda f: sum(f(x) * x.n_matched for x in per) / matched_weight  # noqa: E731

    q_text = wmean(lambda x: x.q_text)
    q_assert = wmean(lambda x: x.q_assert)
    q_cand = wmean(lambda x: x.q_cand)
    q_pair = W_TEXT * q_text + W_ASSERT * q_assert + W_CAND * q_cand
    coverage = M / (G + P - M) if (G + P - M) else 1.0

    return {
        "final": corpus.final,
        "final_model": q_pair * coverage,
        "q_pair": q_pair,
        "q_text": q_text,
        "q_assert": q_assert,
        "q_cand": q_cand,
        "q_iou": wmean(lambda x: x.q_iou),
        "coverage": coverage,
        "recall": M / G if G else 1.0,
        "precision": M / P if P else 1.0,
        "n_gold": G,
        "n_pred": P,
        "n_matched": M,
        "n_files": n,
        "density_gold": G / n,
        "density_pred": P / n,
    }
