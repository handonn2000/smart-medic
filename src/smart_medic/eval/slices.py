"""The mandatory slice table — every slice carries its `n` and its MDE.

A slice score without `n` is not evidence, it is decoration. `pho_bien` and
`hoi_dap` hold 12 documents each; at n=30 the best-case MDE is already 0.238
points, so those slices **cannot resolve the 0.010 floor** and must never be
quoted as proof that a change helped or hurt.

Four axes, per plan-v4 tab 05 §A.3:

    thể loại × loại entity  ·  NFC / không  ·  có ***** / không

How MDE is obtained
-------------------
`MDE_ref` is the *best case*: 1.96·SE of a highly-correlated pair, measured on
this corpus (the isFamily mutation — smallest real perturbation available) and
scaled to the slice by √(N/n). It is a floor, not a promise: two systems that
miss entities in different places sit ~8× worse (SE 0.415 vs 0.053). Pass
`--baseline DIR` to replace it with the real paired MDE for the pair you are
actually comparing.

A type slice restricts **gold and prediction alike** to that type, so a
cross-type match cannot leak in or out — which also means the type slices do not
sum to the corpus score.

Usage
-----
    python3 -m smart_medic.eval.slices --pred runs/_pred_gold --gold GOLD
    python3 -m smart_medic.eval.slices --pred B --baseline A --gold GOLD --delta 0.4
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from math import sqrt
from pathlib import Path

from .bootstrap import FLOOR, doc_points, paired_bootstrap
from .scoring import TYPES, MetricConfig, load_dir, sort_key

#: Corpus genres, read off the filename suffix. Order is the plan's order.
GENRES = ("dan_y", "van_xuoi", "xuong_dong", "pho_bien", "hoi_dap")
#: The mask token the generator leaves behind where PHI was removed.
MASK = "*****"
#: Cheaper bootstrap for the reference SE — it feeds a floor, not a verdict.
REF_REPS = 4_000


def genre_of(stem: str) -> str:
    for g in GENRES:
        if stem.endswith("_" + g):
            return g
    return "?"


# ──────────────────────────────── slicing ────────────────────────────────
@dataclass(frozen=True)
class Slice:
    axis: str
    name: str
    keys: tuple[str, ...]


def build_slices(keys: list[str], texts: dict[str, str]) -> list[Slice]:
    """Every slice the plan mandates, in reporting order. Empty slices are dropped."""
    out: list[Slice] = [Slice("toàn corpus", "tất cả", tuple(keys))]

    by_genre = {g: tuple(k for k in keys if genre_of(k) == g) for g in GENRES}
    out += [Slice("thể loại", g, ks) for g, ks in by_genre.items() if ks]

    if texts:
        nfc = tuple(k for k in keys if k in texts
                    and unicodedata.is_normalized("NFC", texts[k]))
        non = tuple(k for k in keys if k in texts
                    and not unicodedata.is_normalized("NFC", texts[k]))
        out += [Slice("chuẩn hoá", "NFC", nfc), Slice("chuẩn hoá", "không-NFC", non)]
        clean = tuple(k for k in keys if k in texts and MASK not in texts[k])
        masked = tuple(k for k in keys if k in texts and MASK in texts[k])
        out += [Slice("che PHI", "sạch", clean), Slice("che PHI", "có *****", masked)]

    return [s for s in out if s.keys]


def restrict(entities: list[dict], etype: str | None) -> list[dict]:
    return entities if etype is None else [e for e in entities if e["type"] == etype]


# ─────────────────────────────── measurement ───────────────────────────────
def measure(
    gold: dict[str, list],
    pred: dict[str, list],
    keys: tuple[str, ...],
    etype: str | None,
    alignments: tuple[str, ...],
) -> dict:
    docs = [(k, restrict(gold[k], etype), restrict(pred[k], etype)) for k in keys]
    row = {
        "n_docs": len(keys),
        "n_gold": sum(len(g) for _, g, _ in docs),
        "n_pred": sum(len(p) for _, _, p in docs),
    }
    for al in alignments:
        pts = doc_points(docs, MetricConfig(alignment=al))
        row[al] = sum(pts) / len(pts) if pts else 0.0
    row["_docs"] = docs
    return row


def reference_se(gold: dict[str, list], keys: list[str], *, reps: int = REF_REPS) -> float:
    """Paired SE of the most correlated realistic pair on THIS corpus.

    The isFamily flag drop: same spans, same types, same codes, one assertion
    removed. Anything two real systems disagree about is looser than this, so
    the MDE it produces is a floor.
    """
    cfg = MetricConfig()
    base = [(k, gold[k], gold[k]) for k in keys]
    dropped = [
        (
            k,
            gold[k],
            [
                {**e, "assertions": [a for a in e.get("assertions", []) if a != "isFamily"]}
                for e in gold[k]
            ],
        )
        for k in keys
    ]
    return paired_bootstrap(doc_points(base, cfg), doc_points(dropped, cfg), reps=reps).se


def mde_ref(se_full: float, n_full: int, n: int) -> float:
    """Scale the corpus-level best-case SE down to a slice of n documents."""
    return 1.96 * se_full * sqrt(n_full / n) if n else float("inf")


# ──────────────────────────────── rendering ────────────────────────────────
def _u(text: str, on: bool, tty: bool) -> str:
    """Underline — literally, when we are on a terminal; a marker otherwise."""
    if not on:
        return text
    return f"\x1b[4m{text}\x1b[0m" if tty else text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--text", type=Path,
                    help="source .txt dir for the NFC / ***** axes "
                         "(default: <gold>/../text)")
    ap.add_argument("--baseline", type=Path,
                    help="second prediction dir — replaces MDE_ref with the real "
                         "paired MDE for that comparison")
    ap.add_argument("--delta", type=float, default=FLOOR,
                    help="the delta under test; slices with MDE > delta are underlined")
    ap.add_argument("--types", action="store_true",
                    help="also break every slice down by entity type (5× the rows)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    gold, pred = load_dir(args.gold), load_dir(args.pred)
    keys = sorted(set(gold) & set(pred), key=sort_key)
    if not keys:
        print("no document ids common to --pred and --gold", file=sys.stderr)
        return 1
    if len(keys) < len(gold):
        print(f"note: {len(keys)}/{len(gold)} gold documents have a prediction\n")

    text_dir = args.text or (args.gold.parent / "text")
    texts: dict[str, str] = {}
    if text_dir.is_dir():
        for k in keys:
            p = text_dir / f"{k}.txt"
            if p.exists():
                texts[k] = p.read_text(encoding="utf-8")
    if not texts:
        print(f"!! {text_dir} not readable — NFC and ***** axes SKIPPED\n")

    base = load_dir(args.baseline) if args.baseline else None
    if base is not None:
        keys = [k for k in keys if k in base]

    alignments = ("greedy_iou", "overlap_type", "exact")
    slices = build_slices(keys, texts)
    se_full = reference_se(gold, keys)
    tty = sys.stdout.isatty()

    print(f"\n── BẢNG LÁT CẮT ── pred={args.pred}  gold={args.gold}  "
          f"n={len(keys)} tài liệu")
    print(f"   penalised · Δ đang xét = {args.delta:.3f}")
    if base is None:
        print(f"   MDE_ref = 1,96·SE·√(N/n), SE={se_full:.3f} đo trên cặp tương quan cao "
              f"nhất có thật (bỏ cờ isFamily) tại N={len(keys)}.")
        print("   Đây là SÀN TỐT NHẤT. Hai hệ bỏ sót ở chỗ khác nhau rộng hơn ~8 lần.")
    else:
        print(f"   MDE = paired bootstrap thật, {args.baseline} → {args.pred}")

    header = (f"{'trục':<12}{'lát':<14}{'kiểu':<20}{'n_doc':>6}{'n_gold':>7}"
              f"{'greedy':>9}{'ovl_type':>10}{'exact':>8}{'MDE':>8}")
    rows_json = []
    n_underlined = 0
    axis_seen = None

    type_axis: list[str | None] = [None] + list(TYPES) if args.types else [None]

    print()
    print(header)
    print("─" * len(header))
    for sl in slices:
        if sl.axis != axis_seen:
            axis_seen = sl.axis
        for etype in type_axis:
            row = measure(gold, pred, sl.keys, etype, alignments)
            if row["n_gold"] == 0 and row["n_pred"] == 0:
                continue
            if base is not None:
                docs_b = [(k, restrict(gold[k], etype), restrict(base[k], etype))
                          for k in sl.keys]
                cfg = MetricConfig()
                mde = paired_bootstrap(
                    doc_points(docs_b, cfg), doc_points(row["_docs"], cfg), reps=REF_REPS
                ).mde
            else:
                mde = mde_ref(se_full, len(keys), row["n_docs"])
            weak = mde > args.delta
            n_underlined += weak
            label = (f"{sl.axis:<12}{sl.name:<14}{(etype or 'mọi loại'):<20}"
                     f"{row['n_docs']:>6}{row['n_gold']:>7}"
                     f"{row['greedy_iou']:>9.2f}{row['overlap_type']:>10.2f}"
                     f"{row['exact']:>8.2f}{mde:>8.3f}")
            print(_u(label, weak, tty) + ("  ‡" if weak else ""))
            rows_json.append({
                "axis": sl.axis, "slice": sl.name, "type": etype,
                "n_docs": row["n_docs"], "n_gold": row["n_gold"], "n_pred": row["n_pred"],
                **{a: round(row[a], 4) for a in alignments},
                "mde": round(mde, 4), "under_resolved": bool(weak),
            })

    print(f"\n  ‡ / gạch chân = MDE > Δ đang xét ({args.delta:.3f}) ⇒ lát này KHÔNG "
          f"phân giải được delta đó.")
    print(f"  {n_underlined}/{len(rows_json)} lát dưới ngưỡng phân giải.")
    small = [r for r in rows_json if r["n_docs"] <= 30 and r["type"] is None]
    if small:
        print("  Lát ≤30 tài liệu (đừng dùng làm bằng chứng so sánh): "
              + ", ".join(f"{r['slice']} n={r['n_docs']} MDE={r['mde']:.3f}"
                          for r in small))
    tiny = [r for r in rows_json if 0 < r["n_gold"] <= 40 and r["type"] is not None]
    if tiny:
        print(f"  {len(tiny)} lát × loại có ≤40 entity — dùng để phát hiện lỗi hệ thống, "
              "không dùng để so hai phiên bản.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"pred": str(args.pred), "gold": str(args.gold),
                        "n_docs": len(keys), "delta_under_test": args.delta,
                        "se_reference": round(se_full, 4),
                        "baseline": str(args.baseline) if args.baseline else None,
                        "rows": rows_json}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        print(f"\n  → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
