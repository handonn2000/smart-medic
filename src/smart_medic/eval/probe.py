"""Probe variants — one submission, one variable, one black box opened.

Three things the internal scorer can never tell us, because they live in the
organisers' code: which alignment rule they use, what `c_i` counts, and what the
real entity density of the hidden test set is. Each is worth more than any
extractor improvement we could make in the same time, and each costs exactly one
of five daily submissions.

    A   span + type only — `assertions` and `candidates` emptied everywhere
    A′  A with every type rotated to a different one, spans BYTE-IDENTICAL
    B   A + IN-level RxCUI on THUỐC, exact surface match against the gazetteer
    C   A + assertions grafted from a prediction set that has them (needs P4)

A′ is the whole design in one line: it changes *only* the field `greedy_iou`
never looks at. If the leaderboard does not move, type is free and we stop
paying for it. If it collapses, type is worth 12.35 points at a 10% error rate.
There is no middle reading — which is why the variant rotates 100% of types
rather than a sample.

This module writes prediction directories. It does not build archives and it
does not submit: `scripts/submit/package_submission.py --pred <dir> --probe <v>`
does the first, and a human does the second.

Usage
-----
    python3 -m smart_medic.eval.probe --pred data/output --variant A  --out runs/p2/A
    python3 -m smart_medic.eval.probe --pred data/output --variant A' --out runs/p2/Ap
    python3 -m smart_medic.eval.probe --pred data/output --variant B  --out runs/p2/B
    python3 -m smart_medic.eval.probe --expect --gold GOLD --pred runs/_pred_gold
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bootstrap import doc_points, paired_bootstrap
from .scoring import TYPES, MetricConfig, load_dir, score_corpus, sort_key

#: Where the build-time gazetteer lands. Already filtered to tty ∈ {IN,PIN,MIN}
#: by scripts/build_gazetteer.py — that filter IS the "IN level" of ADR 0001.
GAZETTEER = Path("data/artifacts/gazetteer.json")
#: configs/pipeline.yaml `max_candidates`. Repeated, not imported: eval/ reads
#: JSON off disk and imports no layer (tests/test_layer_boundaries.py).
MAX_CODES = 2

VARIANTS = ("A", "A'", "Aprime", "B", "C")
#: `A'` needs shell quoting everywhere it appears. `Aprime` is the same variant
#: spelled so a command line, a directory name and a manifest field can share it.
ALIASES = {"Aprime": "A'", "A-prime": "A'", "AP": "A'"}


def canonical(variant: str) -> str:
    return ALIASES.get(variant, variant)


def _clone(entities: list[dict]) -> list[dict]:
    return json.loads(json.dumps(entities))


# ──────────────────────────────── variants ────────────────────────────────
def variant_a(entities: list[dict]) -> list[dict]:
    """Span + type. Every other scored field emptied, positions untouched."""
    out = _clone(entities)
    for e in out:
        e["assertions"] = []
        e["candidates"] = []
    return out


def variant_a_prime(entities: list[dict]) -> list[dict]:
    """A with EVERY type rotated one step. Spans byte-identical to A.

    A fixed rotation rather than a random relabel: the delta has to be readable
    as "type changed / nothing else changed", and a random draw would make the
    two submissions differ in one more way than intended.
    """
    out = variant_a(entities)
    for e in out:
        i = TYPES.index(e["type"]) if e["type"] in TYPES else 0
        e["type"] = TYPES[(i + 1) % len(TYPES)]
    return out


def load_drug_codes(path: Path = GAZETTEER, *, max_codes: int = MAX_CODES) -> dict[str, list[str]]:
    """surface (casefolded) -> RxCUI list, ingredient level, deterministic order."""
    if not path.exists():
        raise SystemExit(
            f"{path} not found — Probe B needs the gazetteer. Build it with\n"
            f"    python3 scripts/build_gazetteer.py --out {path}"
        )
    blob = json.loads(path.read_text(encoding="utf-8"))
    table: dict[str, set[str]] = {}
    for row in blob.get("entries", []):
        if "THUỐC" not in row.get("t", {}) or not row.get("c"):
            continue
        table.setdefault(row["k"].casefold(), set()).update(str(c) for c in row["c"])
    return {k: sorted(v)[:max_codes] for k, v in table.items()}


def variant_b(entities: list[dict], codes: dict[str, list[str]]) -> list[dict]:
    """A + ingredient-level codes on THUỐC, exact surface match only.

    Exact match on purpose: Probe B asks "is the organisers' gold at IN level",
    not "how good is our linker". Fuzzy matching would put linker recall into a
    delta that is supposed to carry one variable.
    """
    out = variant_a(entities)
    for e in out:
        if e["type"] == "THUỐC":
            e["candidates"] = codes.get(e["text"].strip().casefold(), [])
    return out


def variant_c(entities: list[dict], donor: list[dict]) -> list[dict]:
    """A + assertions copied from a donor prediction, matched on exact position.

    P4 does not exist yet, so there is no rule file to read. When it lands, run
    the pipeline with assertions on and point `--assertions-from` at its output:
    the graft keeps A's spans exactly, so C − A stays a one-variable delta.
    """
    by_pos = {tuple(d["position"]): d.get("assertions", []) for d in donor}
    out = variant_a(entities)
    for e in out:
        e["assertions"] = list(by_pos.get(tuple(e["position"]), []))
    return out


# ──────────────────────────────── building ────────────────────────────────
def build(pred: dict[str, list], variant: str, *, donor: dict[str, list] | None = None,
          max_codes: int = MAX_CODES) -> tuple[dict[str, list], dict]:
    """Apply a variant to every record. Returns (records, what-changed stats)."""
    variant = canonical(variant)
    codes = load_drug_codes(max_codes=max_codes) if variant == "B" else {}
    out: dict[str, list] = {}
    stats = {"variant": variant, "documents": len(pred), "entities": 0,
             "types_rotated": 0, "drugs": 0, "drugs_coded": 0, "codes_emitted": 0,
             "assertions_grafted": 0}

    for key, entities in pred.items():
        if variant == "A":
            new = variant_a(entities)
        elif variant == "A'":
            new = variant_a_prime(entities)
            stats["types_rotated"] += len(new)
        elif variant == "B":
            new = variant_b(entities, codes)
            for e in new:
                if e["type"] == "THUỐC":
                    stats["drugs"] += 1
                    stats["drugs_coded"] += bool(e["candidates"])
                    stats["codes_emitted"] += len(e["candidates"])
        elif variant == "C":
            if donor is None:
                raise SystemExit(
                    "Probe C needs --assertions-from DIR: a prediction set that "
                    "already carries assertions. P4 (assertion/) does not exist "
                    "yet, so there is nothing to graft — C is NOT buildable today."
                )
            new = variant_c(entities, donor.get(key, []))
            stats["assertions_grafted"] += sum(1 for e in new if e["assertions"])
        else:
            raise SystemExit(f"unknown variant {variant!r}; pick one of {VARIANTS}")
        stats["entities"] += len(new)
        out[key] = new

    stats["density_per_file"] = round(stats["entities"] / max(1, stats["documents"]), 4)
    return out, stats


def write(records: dict[str, list], out_dir: Path) -> None:
    """Plain JSON dump. `package_submission.py` re-emits through the hard gate,
    so this writer is deliberately not the schema authority."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, entities in records.items():
        (out_dir / f"{key}.json").write_text(
            json.dumps(entities, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )


def positions_identical(a: dict[str, list], b: dict[str, list]) -> list[str]:
    """Every probe must leave spans byte-identical to A. Anything else is a bug."""
    bad = []
    for key in sorted(set(a) | set(b), key=sort_key):
        pa = [tuple(e["position"]) for e in a.get(key, [])]
        pb = [tuple(e["position"]) for e in b.get(key, [])]
        if pa != pb:
            bad.append(key)
    return bad


# ───────────────────────── internal expected deltas ─────────────────────────
def expected(gold_dir: Path, pred_dir: Path | None, *, max_codes: int = MAX_CODES) -> dict:
    """Score every variant internally, so the submission has a prediction to fail.

    Runs on gold as its own prediction when `--pred` is omitted: that is the
    ceiling case, and it is where the plan's A′−A range (0.00 greedy vs
    −20.19…−51.81 overlap_type) comes from.
    """
    gold = load_dir(gold_dir)
    pred = load_dir(pred_dir) if pred_dir else gold
    keys = sorted(set(gold) & set(pred), key=sort_key)
    if not keys:
        raise SystemExit("no document ids common to --gold and --pred")
    base = {k: pred[k] for k in keys}

    rows: dict[str, dict] = {}
    built = {}
    for v in ("A", "A'", "B"):
        recs, stats = build(base, v, max_codes=max_codes)
        built[v] = recs
        docs = [(k, gold[k], recs[k]) for k in keys]
        rows[v] = {"stats": stats}
        for al in ("greedy_iou", "overlap_type", "exact"):
            rows[v][al] = score_corpus(docs, MetricConfig(alignment=al))["leaderboard"]

    cfg = MetricConfig()
    a_pts = doc_points([(k, gold[k], built["A"][k]) for k in keys], cfg)
    for v in ("A'", "B"):
        d = paired_bootstrap(
            a_pts, doc_points([(k, gold[k], built[v][k]) for k in keys], cfg)
        )
        rows[v]["bootstrap_vs_A"] = {
            "delta": d.delta, "se": d.se, "ci95": [d.ci_lo, d.ci_hi],
            "mde": d.mde, "passes_bar": d.passes,
        }
    rows["_meta"] = {"n_docs": len(keys), "gold": str(gold_dir),
                     "pred": str(pred_dir) if pred_dir else str(gold_dir)}
    return rows


# ──────────────────────────────────── cli ────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", type=Path, help="source prediction directory")
    ap.add_argument("--variant", choices=VARIANTS)
    ap.add_argument("--out", type=Path, help="where to write the probe records")
    ap.add_argument("--assertions-from", type=Path,
                    help="Probe C donor: a prediction dir that carries assertions")
    ap.add_argument("--max-codes", type=int, default=MAX_CODES)
    ap.add_argument("--expect", action="store_true",
                    help="internal expected deltas for A / A' / B, needs --gold")
    ap.add_argument("--gold", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    payload: dict = {}

    if args.expect:
        if not args.gold:
            print("--expect needs --gold", file=sys.stderr)
            return 2
        rows = expected(args.gold, args.pred, max_codes=args.max_codes)
        meta = rows["_meta"]
        print(f"\n── DELTA KỲ VỌNG (NỘI BỘ) ── gold={meta['gold']}  "
              f"pred={meta['pred']}  n={meta['n_docs']}")
        print(f"{'biến thể':<10}{'greedy_iou':>12}{'overlap_type':>14}{'exact':>9}"
              f"{'Δ vs A (greedy)':>18}{'Δ vs A (ovl_type)':>20}")
        a = rows["A"]
        print(f"{'A':<10}{a['greedy_iou']:>12.2f}{a['overlap_type']:>14.2f}"
              f"{a['exact']:>9.2f}{'—':>18}{'—':>20}")
        for v in ("A'", "B"):
            r = rows[v]
            print(f"{v:<10}{r['greedy_iou']:>12.2f}{r['overlap_type']:>14.2f}"
                  f"{r['exact']:>9.2f}"
                  f"{r['greedy_iou'] - a['greedy_iou']:>+18.2f}"
                  f"{r['overlap_type'] - a['overlap_type']:>+20.2f}")
        for v in ("A'", "B"):
            b = rows[v]["bootstrap_vs_A"]
            print(f"  {v} vs A (greedy_iou, paired B=10.000): Δ={b['delta']:+.3f}  "
                  f"SE={b['se']:.3f}  CI95=[{b['ci95'][0]:+.3f}; {b['ci95'][1]:+.3f}]")
        bstat = rows["B"]["stats"]
        print(f"  B mã hoá {bstat['drugs_coded']}/{bstat['drugs']} span THUỐC "
              f"({bstat['drugs_coded'] / max(1, bstat['drugs']):.1%}), "
              f"{bstat['codes_emitted']} mã")
        payload["expected"] = {
            k: {kk: vv for kk, vv in r.items()} for k, r in rows.items()
        }

    if args.variant:
        if not (args.pred and args.out):
            print("--variant needs --pred and --out", file=sys.stderr)
            return 2
        pred = load_dir(args.pred)
        if not pred:
            print(f"no records in {args.pred}", file=sys.stderr)
            return 1
        donor = load_dir(args.assertions_from) if args.assertions_from else None
        variant = canonical(args.variant)
        records, stats = build(pred, variant, donor=donor, max_codes=args.max_codes)

        drift = positions_identical(pred, records)
        if drift:
            print(f"!! probe moved spans in {len(drift)} document(s): {drift[:5]} — "
                  f"a probe must change ONE field, never a position", file=sys.stderr)
            return 1

        write(records, args.out)
        print(f"\n── PROBE {variant} ── {args.pred} → {args.out}")
        print(f"  {stats['documents']} tài liệu · {stats['entities']} entity · "
              f"mật độ {stats['density_per_file']}/file")
        if variant == "A'":
            print(f"  type đảo: {stats['types_rotated']}/{stats['entities']} "
                  f"(100% — spans byte-identical với A)")
        if variant == "B":
            print(f"  THUỐC có mã: {stats['drugs_coded']}/{stats['drugs']} "
                  f"({stats['drugs_coded'] / max(1, stats['drugs']):.1%}) · "
                  f"{stats['codes_emitted']} mã mức IN")
        if variant == "C":
            print(f"  assertions ghép: {stats['assertions_grafted']} entity")
        print(f"\n  Đóng gói:  python3 scripts/submit/package_submission.py "
              f"--pred {args.out} --probe {args.variant}")
        print("  KHÔNG tự nộp. Nộp bài là quyết định của con người.")
        payload["build"] = stats

    if not args.variant and not args.expect:
        print("nothing to do: pass --variant, or --expect --gold", file=sys.stderr)
        return 2

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"\n  → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
