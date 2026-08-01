"""Bộ đo năng lực truy hồi trên probe set.

Đây là hạ tầng mà PRD §5 gọi là "quan trọng ngang với model": không có nó thì
Phase 3 (enrichment) chỉ là "thêm dữ liệu rồi hy vọng" — nạp thêm bao giờ cũng
"thành công" về mặt kỹ thuật, câu hỏi thật là *có tốt lên không*.

Đo bốn số cho mỗi lát cắt:
    Recall@1   tỉ lệ mention có mã đúng ở ngay hạng 1
    Recall@5   … trong top-5
    Recall@20  … trong top-20  (trần của bước truy hồi; re-rank chỉ lọc từ đây)
    MRR        nghịch đảo hạng của mã đúng đầu tiên, trung bình

Lát cắt: tổng thể · theo `kind` (disease/drug) · theo `hard`.
Trong đó **Recall@1 là cổng chống đầu độc precision** ở §P3.7 — enrichment được
phép không tăng recall, nhưng không được làm tụt Recall@1.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from smart_medic.kb import config
from smart_medic.kb.query import KBStore, search_lexical

DEFAULT_PROBE = config.DATA_DIR / "probe" / "retrieval_probe.yaml"

VOCAB_OF_KIND = {"disease": "icd10", "drug": "rxnorm"}
CUTOFFS = (1, 5, 20)


@dataclass(slots=True)
class Case:
    mention: str
    kind: str
    gold: tuple[str, ...]
    hard: bool = False
    note: str = ""
    rank: int | None = None  # hạng của mã đúng đầu tiên, None nếu trượt
    top: tuple[str, ...] = ()

    @property
    def vocab(self) -> str:
        return VOCAB_OF_KIND[self.kind]


@dataclass(slots=True)
class Slice:
    name: str
    cases: list[Case] = field(default_factory=list)

    def recall_at(self, k: int) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.rank and c.rank <= k) / len(self.cases)

    def mrr(self) -> float:
        if not self.cases:
            return 0.0
        return statistics.fmean(1.0 / c.rank if c.rank else 0.0 for c in self.cases)

    def as_dict(self) -> dict:
        return {
            "n": len(self.cases),
            **{f"recall@{k}": round(self.recall_at(k), 4) for k in CUTOFFS},
            "mrr": round(self.mrr(), 4),
        }


def load_probe(path: Path | None = None) -> list[Case]:
    path = path or DEFAULT_PROBE
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        Case(
            mention=e["mention"],
            kind=e["kind"],
            gold=tuple(str(g) for g in e["gold"]),
            hard=bool(e.get("hard")),
            note=e.get("note", ""),
        )
        for e in raw
    ]


def run_cases(
    store: KBStore,
    cases: list[Case],
    *,
    tiers: tuple[str, ...] | None = None,
    top_k: int = max(CUTOFFS),
) -> list[Case]:
    for c in cases:
        hits = search_lexical(store, c.mention, vocab=c.vocab, tiers=tiers, top_k=top_k)
        codes = [h.code for h in hits]
        c.top = tuple(codes[:5])
        c.rank = next((i + 1 for i, code in enumerate(codes) if code in c.gold), None)
    return cases


def slices_of(cases: list[Case]) -> list[Slice]:
    out = [Slice("TỔNG THỂ", list(cases))]
    for kind, label in (("disease", "chẩn đoán → ICD"), ("drug", "thuốc → RxNorm")):
        out.append(Slice(label, [c for c in cases if c.kind == kind]))
    out.append(Slice("ca thường", [c for c in cases if not c.hard]))
    out.append(Slice("ca KHÓ", [c for c in cases if c.hard]))
    return out


# ── in ấn ────────────────────────────────────────────────────────────────


def _fmt_table(slices: list[Slice], baseline: dict | None = None) -> str:
    head = f"  {'lát cắt':<20}{'n':>5}{'R@1':>9}{'R@5':>9}{'R@20':>9}{'MRR':>9}"
    lines = [head, "  " + "─" * (len(head) - 2)]
    for s in slices:
        row = f"  {s.name:<20}{len(s.cases):>5}"
        for metric in (*(s.recall_at(k) for k in CUTOFFS), s.mrr()):
            row += f"{metric:>9.3f}"
        if baseline and s.name in baseline:
            d = s.recall_at(5) - baseline[s.name]["recall@5"]
            if abs(d) >= 0.0005:
                row += f"   ΔR@5 {d:+.3f}"
        lines.append(row)
    return "\n".join(lines)


def _fmt_misses(cases: list[Case], limit: int = 15) -> str:
    missed = [c for c in cases if c.rank is None]
    if not missed:
        return "\n  ✓ Không có ca nào trượt hoàn toàn."
    lines = [f"\n  ── {len(missed)} ca trượt khỏi top-{max(CUTOFFS)} ──"]
    for c in missed[:limit]:
        mark = "KHÓ" if c.hard else "   "
        lines.append(
            f"    [{mark}] {c.mention[:38]:<40} mong {list(c.gold)}  được {list(c.top[:3])}"
        )
    if len(missed) > limit:
        lines.append(f"    … và {len(missed) - limit} ca nữa")
    return "\n".join(lines)


def run(
    *,
    db: Path | None = None,
    probe: Path | None = None,
    tiers: tuple[str, ...] | None = None,
    save: Path | None = None,
    compare: Path | None = None,
) -> int:
    cases = load_probe(probe)
    if not cases:
        print("✗ Probe set rỗng.")
        return 1

    with KBStore(db) as store:
        run_cases(store, cases, tiers=tiers)

    sl = slices_of(cases)
    base = None
    if compare and compare.is_file():
        base = json.loads(compare.read_text(encoding="utf-8"))["slices"]

    print(f"\n── Probe set: {len(cases)} cặp ", "─" * 40)
    if tiers:
        print(f"  (chỉ dùng term tier ∈ {list(tiers)})")
    print(_fmt_table(sl, base))
    print(_fmt_misses(cases))

    if save:
        payload = {
            "n_cases": len(cases),
            "tiers": list(tiers) if tiers else None,
            "slices": {s.name: s.as_dict() for s in sl},
            "misses": [c.mention for c in cases if c.rank is None],
        }
        save.parent.mkdir(parents=True, exist_ok=True)
        save.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  → đã lưu {save}")
    return 0
