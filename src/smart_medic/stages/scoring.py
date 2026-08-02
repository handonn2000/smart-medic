"""Bộ chấm điểm nội bộ theo PRD §6.

PRD §5 gọi thứ này là *"quan trọng ngang với model"*: không có nó thì mọi thay đổi
ở pipeline giải bài chỉ là "sửa rồi hy vọng" — đúng cái bẫy mà Phase 3 và Phase 5
của KB đã tránh được nhờ có thước đo trước.

    final = 0,3·text_score + 0,3·assertions_score + 0,4·candidates_score

★ HAI CHỖ ĐỀ BÀI KHÔNG NÓI RÕ — VÀ GIẢ ĐỊNH Ở ĐÂY
──────────────────────────────────────────────────
PRD tự ghi chú rằng công thức `candidates_score` được **trích từ ảnh đề**, chưa
đối chiếu công bố chính thức. Ngoài ra đề **không nói cách ghép** entity dự đoán
với entity vàng — mà không ghép được thì không tính được WER trên từng cặp.

Giả định ở đây, khai báo tường minh để đổi được khi BTC làm rõ:

1. **Ghép theo chồng lấn ký tự**, tham lam từ cặp chồng lấn nhiều nhất. Đây là
   quy ước chuẩn của đánh giá NER. Entity vàng không ghép được tính là trượt
   hoàn toàn (`WER = 1`, `J = 0`); entity thừa do model sinh ra cũng bị tính
   một lượt 0 — nếu không thì rải entity bừa sẽ không bị phạt.

2. **Điểm của một file = trung bình trên hợp của (cặp ghép được ∪ vàng lẻ ∪
   thừa lẻ)**, rồi điểm toàn tập là trung bình trên các file — khớp với dạng
   `Σᵢ … / len(test)` của đề.

Vì lớp giả định này, **con số tuyệt đối ở đây không phải điểm thi**. Nó dùng để
so sánh giữa hai phiên bản của chính ta. Kèm thêm P/R/F1 chuẩn — đại lượng
KHÔNG phụ thuộc giả định nào — để chẩn đoán khi hai chỉ số lệch nhau.

★ BẢNG THEO NHÁNH — ngữ nghĩa chính xác
────────────────────────────────────────
`Report.by_type()` trả P/R/F1 **theo từng nhãn**. Đây là đại lượng đã lộ ra rằng
ưu tiên của kế hoạch v1 bị đảo ngược (`docs/synth-corpus-plan-v2.md` §0.2), nên
định nghĩa phải rõ để không ai đọc nhầm:

    recall[t]     = (cặp ghép được có nhãn VÀNG = t) / (số entity vàng nhãn t)
    precision[t]  = (cặp ghép được có nhãn DỰ ĐOÁN = t) / (số entity dự đoán nhãn t)

Tức đây là **P/R của việc PHÁT HIỆN span**, tính theo nhãn — một cặp ghép được
nhưng gán sai nhãn vẫn được tính là "phát hiện đúng" ở cả hai vế. Phần gán nhãn
đo riêng bằng `type_accuracy[t]`. Tách hai thứ ra là có chủ đích: trần điểm của
mỗi nhánh bị chặn bởi *phát hiện*, không phải bởi *phân loại* — trộn chúng vào
một con số sẽ giấu mất điều đó.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Trọng số ở PRD §6.
W_TEXT = 0.3
W_ASSERTIONS = 0.3
W_CANDIDATES = 0.4

# Chỉ hai nhãn này được gán mã.
TYPES_WITH_CANDIDATES = frozenset({"CHẨN_ĐOÁN", "THUỐC"})

_WORD = re.compile(r"\S+")


@dataclass(slots=True)
class Entity:
    """Một khái niệm y tế — dạng chuẩn hoá của dict trong file JSON."""

    text: str
    type: str
    start: int
    end: int
    candidates: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict) -> Entity:
        pos = d.get("position") or [0, 0]
        return cls(
            text=d.get("text", ""),
            type=d.get("type", ""),
            start=int(pos[0]),
            end=int(pos[1]),
            candidates=tuple(str(c) for c in (d.get("candidates") or [])),
            assertions=tuple(str(a) for a in (d.get("assertions") or [])),
        )

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "type": self.type,
            "candidates": list(self.candidates),
            "assertions": list(self.assertions),
            "position": [self.start, self.end],
        }

    def overlap(self, other: Entity) -> int:
        """Số ký tự chồng lấn với entity khác. 0 nếu rời nhau."""
        return max(0, min(self.end, other.end) - max(self.start, other.start))


def words(text: str) -> list[str]:
    """Cắt từ để tính WER.

    NFC hoá và hạ chữ thường **chỉ ở đây** — đây là bản sao dùng để so khớp, chưa
    bao giờ là chuỗi dùng tính offset (xem `textio.py`).
    """
    return _WORD.findall(unicodedata.normalize("NFC", text).lower())


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate — khoảng cách Levenshtein mức TỪ, chia số từ đáp án.

    Không chặn trên tại 1,0: đoán dài lê thê so với đáp án ngắn thì WER > 1 là
    đúng bản chất. Việc chặn để lấy điểm được làm ở `text_score`.

    >>> wer("ho đờm xanh", "ho đờm")
    0.3333333333333333
    >>> wer("ho", "ho")
    0.0
    >>> wer("", "")
    0.0
    """
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


def text_score(reference: str, hypothesis: str) -> float:
    """`1 − WER`, kẹp về [0, 1] để một entity sai thảm không kéo âm cả file."""
    return max(0.0, 1.0 - wer(reference, hypothesis))


def jaccard(gold: tuple[str, ...], pred: tuple[str, ...]) -> float:
    """|A∩B| / |A∪B|, quy ước **cả hai rỗng ⇒ 1,0** (PRD §6).

    Quy ước đó là lý do "mặc định rỗng" là nước đi an toàn cho assertion.

    >>> jaccard((), ())
    1.0
    >>> jaccard(("K21.0", "K21.9"), ("K21.0",))
    0.5
    >>> jaccard(("A",), ("B",))
    0.0
    """
    a, b = set(gold), set(pred)
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def align(
    gold: list[Entity], pred: list[Entity]
) -> tuple[list[tuple[Entity, Entity]], list[Entity], list[Entity]]:
    """Ghép entity vàng với entity dự đoán theo chồng lấn ký tự, tham lam.

    Trả `(cặp đã ghép, vàng lẻ, thừa lẻ)`. Mỗi entity ghép nhiều nhất một lần.

    Tham lam theo chồng lấn giảm dần là đủ và tất định; tie-break bằng vị trí để
    kết quả không phụ thuộc thứ tự đầu vào.
    """
    pairs_by_overlap = sorted(
        (
            (g.overlap(p), -abs(g.start - p.start), gi, pi)
            for gi, g in enumerate(gold)
            for pi, p in enumerate(pred)
            if g.overlap(p) > 0
        ),
        reverse=True,
    )
    used_g: set[int] = set()
    used_p: set[int] = set()
    matched: list[tuple[Entity, Entity]] = []
    for _ov, _tie, gi, pi in pairs_by_overlap:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matched.append((gold[gi], pred[pi]))
    return (
        matched,
        [g for i, g in enumerate(gold) if i not in used_g],
        [p for i, p in enumerate(pred) if i not in used_p],
    )


@dataclass(slots=True)
class TypeStats:
    """Đếm thô theo một nhãn. Mọi tỉ lệ suy ra từ đây, không lưu tỉ lệ."""

    gold: int = 0
    pred: int = 0
    matched_gold: int = 0  # cặp ghép được, đếm theo nhãn của entity VÀNG
    matched_pred: int = 0  # cặp ghép được, đếm theo nhãn của entity DỰ ĐOÁN
    type_ok: int = 0  # cặp ghép được và hai nhãn trùng nhau

    def add(self, other: TypeStats) -> None:
        self.gold += other.gold
        self.pred += other.pred
        self.matched_gold += other.matched_gold
        self.matched_pred += other.matched_pred
        self.type_ok += other.type_ok

    @property
    def recall(self) -> float:
        return self.matched_gold / self.gold if self.gold else 0.0

    @property
    def precision(self) -> float:
        return self.matched_pred / self.pred if self.pred else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def type_accuracy(self) -> float:
        return self.type_ok / self.matched_gold if self.matched_gold else 0.0

    def as_dict(self) -> dict:
        return {
            "gold": self.gold,
            "pred": self.pred,
            "matched": self.matched_gold,
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "f1": round(self.f1, 4),
            "type_accuracy": round(self.type_accuracy, 4),
        }


@dataclass(slots=True)
class DocScore:
    text: float = 0.0
    assertions: float = 0.0
    candidates: float = 0.0
    n_gold: int = 0
    n_pred: int = 0
    n_matched: int = 0
    n_type_ok: int = 0
    by_type: dict[str, TypeStats] = field(default_factory=dict)
    name: str = ""

    @property
    def final(self) -> float:
        return W_TEXT * self.text + W_ASSERTIONS * self.assertions + W_CANDIDATES * self.candidates

    def as_dict(self) -> dict:
        """Điểm từng file — `bootstrap` cần đúng ba thành phần này để lấy mẫu lại."""
        return {
            "name": self.name,
            "text": round(self.text, 6),
            "assertions": round(self.assertions, 6),
            "candidates": round(self.candidates, 6),
            "final": round(self.final, 6),
            "n_gold": self.n_gold,
            "n_pred": self.n_pred,
            "n_matched": self.n_matched,
        }


def _tally_types(
    gold: list[Entity], pred: list[Entity], matched: list[tuple[Entity, Entity]]
) -> dict[str, TypeStats]:
    """Đếm thô theo nhãn. Ngữ nghĩa ở docstring module, mục "BẢNG THEO NHÁNH"."""
    by: dict[str, TypeStats] = {}

    def slot(t: str) -> TypeStats:
        return by.setdefault(t, TypeStats())

    for e in gold:
        slot(e.type).gold += 1
    for e in pred:
        slot(e.type).pred += 1
    for g, p in matched:
        slot(g.type).matched_gold += 1
        slot(p.type).matched_pred += 1
        if g.type == p.type:
            slot(g.type).type_ok += 1
    return by


def score_document(gold: list[Entity], pred: list[Entity], *, name: str = "") -> DocScore:
    """Chấm một file. Xem phần giả định ở docstring module."""
    matched, missed, spurious = align(gold, pred)
    by_type = _tally_types(gold, pred, matched)
    n = len(matched) + len(missed) + len(spurious)
    if n == 0:
        return DocScore(text=1.0, assertions=1.0, candidates=1.0, by_type=by_type, name=name)

    t = a = c = 0.0
    type_ok = 0
    for g, p in matched:
        same_type = g.type == p.type
        type_ok += same_type
        t += text_score(g.text, p.text)
        # Nhãn sai thì assertion/candidate của nó cũng vô nghĩa — không cho điểm.
        a += jaccard(g.assertions, p.assertions) if same_type else 0.0
        c += jaccard(g.candidates, p.candidates) if same_type else 0.0
    # `missed` và `spurious` đóng góp 0 vào cả ba thành phần.

    return DocScore(
        text=t / n,
        assertions=a / n,
        candidates=c / n,
        n_gold=len(gold),
        n_pred=len(pred),
        n_matched=len(matched),
        n_type_ok=type_ok,
        by_type=by_type,
        name=name,
    )


@dataclass(slots=True)
class Report:
    docs: list[DocScore] = field(default_factory=list)

    def _mean(self, attr: str) -> float:
        return sum(getattr(d, attr) for d in self.docs) / len(self.docs) if self.docs else 0.0

    @property
    def text(self) -> float:
        return self._mean("text")

    @property
    def assertions(self) -> float:
        return self._mean("assertions")

    @property
    def candidates(self) -> float:
        return self._mean("candidates")

    @property
    def final(self) -> float:
        return W_TEXT * self.text + W_ASSERTIONS * self.assertions + W_CANDIDATES * self.candidates

    # ── P/R/F1: KHÔNG phụ thuộc giả định ghép/trọng số ────────────────────

    @property
    def precision(self) -> float:
        n = sum(d.n_pred for d in self.docs)
        return sum(d.n_matched for d in self.docs) / n if n else 0.0

    @property
    def recall(self) -> float:
        n = sum(d.n_gold for d in self.docs)
        return sum(d.n_matched for d in self.docs) / n if n else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def type_accuracy(self) -> float:
        """Trong số entity ghép được, bao nhiêu phần trăm đúng nhãn."""
        n = sum(d.n_matched for d in self.docs)
        return sum(d.n_type_ok for d in self.docs) / n if n else 0.0

    def by_type(self) -> dict[str, TypeStats]:
        """Gộp đếm thô theo nhãn trên mọi file. Xem docstring module."""
        out: dict[str, TypeStats] = {}
        for d in self.docs:
            for t, s in d.by_type.items():
                out.setdefault(t, TypeStats()).add(s)
        return out

    def as_dict(self) -> dict:
        return {
            "n_docs": len(self.docs),
            "final": round(self.final, 4),
            "text": round(self.text, 4),
            "assertions": round(self.assertions, 4),
            "candidates": round(self.candidates, 4),
            "span_precision": round(self.precision, 4),
            "span_recall": round(self.recall, 4),
            "span_f1": round(self.f1, 4),
            "type_accuracy": round(self.type_accuracy, 4),
        }
