"""Chấm pipeline giải bài trên một bộ gold gán tay, có bảng theo nhánh + CI.

Đây là **cái thước** của kế hoạch v2 (`docs/synth-corpus-plan-v2.md` Phase 0).
Mọi cổng của mọi phase sau đều đọc số từ đây, nên module này phải đúng trước khi
bất cứ thứ gì khác được đo.

★ BA THỨ NÓ LÀM MÀ BỘ CHẤM CŨ KHÔNG LÀM
────────────────────────────────────────
1. **Bảng theo nhánh.** Chính đại lượng này lộ ra rằng ưu tiên của kế hoạch v1
   bị đảo ngược: nhánh XÉT NGHIỆM có trần +0,154 còn nhánh THUỐC — nơi v1 đầu tư
   nhiều nhất — chỉ +0,057 và đã đạt precision 0,942.
2. **Khoảng tin cậy bootstrap.** Xem `bootstrap.py`.
3. **Giữ điểm TỪNG FILE trong báo cáo.** Nhờ vậy `smk eval compare` so hai lần
   chạy theo cặp mà **không phải chạy lại pipeline** — và phép so là *paired*.

★ BA BỘ GOLD, BA CẤU TRÚC, KHÔNG ĐƯỢC GỘP
──────────────────────────────────────────
    data/probe/gold/         annotations_gold/  ·  regression guard
    data/probe/gold_real/    annotations_gold/  ·  ★ cổng duy nhất
    data/probe/gold_batch1/  annotations/       ·  khái quát hoá ngoài miền

`gold_batch1` để nhãn ở thư mục con khác — dò tự động, đừng đoán.

Báo cáo có khoá theo **tên bộ**, không có chỗ nào ghi số gộp. Đó là cách ép quy
tắc §5.2 ("không gộp ba bộ gold") vào chính định dạng dữ liệu, thay vì trông chờ
người đọc tự nhớ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from smart_medic.eval.bootstrap import B_DEFAULT, SEED, Interval, ci_mean, ci_paired_delta
from smart_medic.kb.query import KBStore
from smart_medic.stages.ner import Gazetteer
from smart_medic.stages.scoring import Entity, Report, TypeStats, score_document
from smart_medic.stages.solve import check_invariants, solve_document
from smart_medic.stages.textio import read_document

TEXT_SUBDIR = "text"
ANNOTATION_SUBDIRS = ("annotations_gold", "annotations")


def find_annotation_dir(gold_dir: Path) -> Path:
    """Thư mục nhãn của một bộ gold. Dò, không đoán (xem docstring module)."""
    for name in ANNOTATION_SUBDIRS:
        if (gold_dir / name).is_dir():
            return gold_dir / name
    raise FileNotFoundError(f"{gold_dir} không có thư mục nhãn nào trong {ANNOTATION_SUBDIRS}")


def load_gold(gold_dir: Path) -> dict[str, list[Entity]]:
    """Nhãn vàng theo tên file (không đuôi)."""
    ann = find_annotation_dir(gold_dir)
    out: dict[str, list[Entity]] = {}
    for f in sorted(ann.glob("*.json"), key=lambda p: (len(p.stem), p.stem)):
        raw = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = [Entity.from_dict(d) for d in raw]
    if not out:
        raise FileNotFoundError(f"không có .json nào trong {ann}")
    return out


@dataclass(slots=True)
class SetResult:
    """Kết quả trên MỘT bộ gold. Không bao giờ gộp hai đối tượng loại này."""

    name: str
    path: str
    report: Report
    ci_final: Interval
    invariant_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            **self.report.as_dict(),
            "ci_final": self.ci_final.as_dict(),
            "by_type": {t: s.as_dict() for t, s in _sorted_types(self.report.by_type())},
            "invariant_errors": self.invariant_errors,
            "documents": [d.as_dict() for d in self.report.docs],
        }


def _sorted_types(by_type: dict[str, TypeStats]) -> list[tuple[str, TypeStats]]:
    """Sắp theo số span vàng giảm dần — nhánh nặng ký nằm trên."""
    return sorted(by_type.items(), key=lambda kv: (-kv[1].gold, kv[0]))


def score_gold_set(
    gold_dir: Path,
    *,
    db: Path | None = None,
    b: int = B_DEFAULT,
    seed: int = SEED,
) -> SetResult:
    """Chạy pipeline trên `<gold_dir>/text/` rồi chấm với nhãn vàng.

    Không ghi file trung gian: gọi thẳng `solve.solve_document`, nên phép đo
    không bao giờ lệch pha với bài nộp thật vì một thư mục `out` cũ.
    """
    gold = load_gold(gold_dir)
    text_dir = gold_dir / TEXT_SUBDIR
    if not text_dir.is_dir():
        raise FileNotFoundError(f"thiếu {text_dir}")

    report = Report()
    errors: list[str] = []
    with KBStore(db) as store:
        gaz = Gazetteer.from_kb(store)
        for stem in gold:
            f = text_dir / f"{stem}.txt"
            if not f.is_file():
                raise FileNotFoundError(f"có nhãn {stem}.json nhưng thiếu {f}")
            text = read_document(f)  # newline='' — KHÔNG Path.read_text
            pred = solve_document(text, store, gaz)
            pred.sort(key=lambda e: (e.start, e.end))
            # Bất biến định dạng kiểm ngay ở đây: một span lệch offset làm hỏng
            # cả phép đo lẫn bài nộp, và im lặng ở cả hai chỗ.
            try:
                check_invariants(text, pred)
            except AssertionError as exc:
                errors.append(f"{stem}: {exc}")
            report.docs.append(score_document(gold[stem], pred, name=stem))

    return SetResult(
        name=gold_dir.name,
        path=str(gold_dir),
        report=report,
        ci_final=ci_mean([d.final for d in report.docs], b=b, seed=seed),
        invariant_errors=errors,
    )


def build_report(results: list[SetResult], *, db: Path | None = None) -> dict:
    """Gói nhiều bộ gold vào MỘT file, khoá theo tên bộ — không có ô nào để gộp."""
    from smart_medic.kb.config import KB_SQLITE

    artifact = db or KB_SQLITE
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "kb_artifact": {
            "path": str(artifact),
            "bytes": artifact.stat().st_size if artifact.is_file() else None,
        },
        "bootstrap": {"B": B_DEFAULT, "seed": SEED},
        "note": (
            "Báo cáo riêng từng bộ gold. gold_real là cổng duy nhất; "
            "gold là regression guard; gold_batch1 đo khái quát hoá ngoài miền. "
            "KHÔNG gộp ba bộ khi báo cáo (docs/synth-corpus-plan-v2.md §5.2)."
        ),
        "sets": {r.name: r.as_dict() for r in results},
    }


# ── So sánh hai báo cáo ───────────────────────────────────────────────────


def paired_finals(base_set: dict, new_set: dict) -> tuple[list[float], list[float], list[str]]:
    """Căn điểm từng file theo TÊN, trả hai dãy cùng thứ tự.

    Căn theo tên chứ không theo vị trí: hai lần chạy có thể khác thứ tự duyệt, và
    ghép lệch file sẽ cho ra một khoảng tin cậy trông rất đẹp mà hoàn toàn sai.
    """
    b = {d["name"]: d["final"] for d in base_set["documents"]}
    n = {d["name"]: d["final"] for d in new_set["documents"]}
    names = sorted(set(b) & set(n), key=lambda s: (len(s), s))
    if not names:
        raise ValueError("hai báo cáo không có file nào chung")
    return [b[k] for k in names], [n[k] for k in names], names


def compare_reports(base: dict, new: dict, *, b: int = B_DEFAULT, seed: int = SEED) -> dict:
    """Δ theo cặp cho MỌI bộ gold có ở cả hai báo cáo — riêng từng bộ."""
    out: dict[str, dict] = {}
    for name in sorted(set(base.get("sets", {})) & set(new.get("sets", {}))):
        bs, ns = base["sets"][name], new["sets"][name]
        bf, nf, names = paired_finals(bs, ns)
        delta = ci_paired_delta(bf, nf, b=b, seed=seed)
        out[name] = {
            "n_docs_paired": len(names),
            "base_final": bs["final"],
            "new_final": ns["final"],
            "delta_final": delta.as_dict(),
            "by_type_delta": {
                t: {
                    "recall": round(ns["by_type"].get(t, {}).get("recall", 0.0) - v["recall"], 4),
                    "precision": round(
                        ns["by_type"].get(t, {}).get("precision", 0.0) - v["precision"], 4
                    ),
                }
                for t, v in bs["by_type"].items()
            },
        }
    if not out:
        raise ValueError("hai báo cáo không có bộ gold nào chung")
    return {"bootstrap": {"B": b, "seed": seed}, "sets": out}


# ── In ra terminal ────────────────────────────────────────────────────────


def format_set(r: SetResult) -> str:
    ci = r.ci_final
    lines = [
        f"  {r.name}  ({len(r.report.docs)} file)",
        f"    final  {r.report.final:.4f}   CI 95% [{ci.lo:.4f}, {ci.hi:.4f}]",
        f"    text {r.report.text:.4f} · assertions {r.report.assertions:.4f} "
        f"· candidates {r.report.candidates:.4f}",
        f"    span   P {r.report.precision:.4f}  R {r.report.recall:.4f}  "
        f"F1 {r.report.f1:.4f}  type {r.report.type_accuracy:.4f}",
        "",
        f"    {'nhãn':24}{'vàng':>6}{'đoán':>6}{'khớp':>6}{'recall':>9}{'prec':>8}{'type':>8}",
    ]
    for t, s in _sorted_types(r.report.by_type()):
        lines.append(
            f"    {t:24}{s.gold:>6}{s.pred:>6}{s.matched_gold:>6}"
            f"{s.recall:>9.3f}{s.precision:>8.3f}{s.type_accuracy:>8.3f}"
        )
    if r.invariant_errors:
        lines.append("")
        lines.append(
            f"    ⚠ {len(r.invariant_errors)} vi phạm BẤT BIẾN — đây là BUG, không phải điểm:"
        )
        lines.extend(f"      {e}" for e in r.invariant_errors[:5])
    return "\n".join(lines)


def format_comparison(cmp: dict) -> str:
    lines = []
    for name, d in cmp["sets"].items():
        dl = d["delta_final"]
        verdict = "✓ vượt nhiễu" if dl["excludes_zero"] and dl["point"] > 0 else "— trong nhiễu"
        if dl["excludes_zero"] and dl["point"] < 0:
            verdict = "✗ TỤT, vượt nhiễu"
        lines.append(
            f"  {name}  ({d['n_docs_paired']} file ghép cặp)\n"
            f"    final  {d['base_final']:.4f} → {d['new_final']:.4f}   "
            f"Δ {dl['point']:+.4f}  CI 95% [{dl['lo']:+.4f}, {dl['hi']:+.4f}]  {verdict}"
        )
        rows = [
            (t, v["recall"], v["precision"])
            for t, v in d["by_type_delta"].items()
            if v["recall"] or v["precision"]
        ]
        if rows:
            lines.append(f"    {'nhãn':24}{'Δrecall':>10}{'Δprec':>10}")
            lines.extend(f"    {t:24}{r:>+10.3f}{p:>+10.3f}" for t, r, p in rows)
    return "\n".join(lines)
