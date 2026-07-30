#!/usr/bin/env python3
"""Sweep one lane-R knob at a time and score each setting on gold. MEASURE, DON'T GUESS.

Not on the path to `output.zip` — a bench, run by hand:

    PYTHONPATH=src python3 scripts/analysis/sweep_recall_floor.py --knob emit_p
    PYTHONPATH=src python3 scripts/analysis/sweep_recall_floor.py --knob merge

Prints `penalised/greedy_iou` (the official number), `penalised/overlap_type`
(the BLOCKING column — a change is only accepted if this does not fall by more
than 0.010) and `matched/greedy_iou` (degenerate; a ceiling, never a target),
plus missing/spurious separately, because a change that trades one for the other
looks identical in the headline number.

Acceptance bar for any delta: Δ > max(0.010 ; 1.96·SE_bootstrap) and CI95 must
exclude 0. The 0.010 floor is only valid for highly-correlated system pairs; two
systems that miss entities in DIFFERENT places are not separable below ~0.8
points (measured SE 0.415), so this script also reports a paired bootstrap.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.decision import emit  # noqa: E402
from smart_medic.eval.scoring import MetricConfig, score_corpus  # noqa: E402
from smart_medic.extract import RecallFloorReport, recall_floor  # noqa: E402
from smart_medic.io.corpus import load_gold  # noqa: E402
from smart_medic.layout.kv import split_units  # noqa: E402
from smart_medic.layout.lines import split_lines  # noqa: E402

#: Bootstrap resamples. Enough for a stable 95% interval on 162 documents.
RESAMPLES = 400


def propose(docs):
    """Lane R once per document. Reused across every setting of a knob."""
    report = RecallFloorReport()
    out = []
    for doc in docs:
        lines = split_lines(doc)
        units = split_units(doc, lines)
        out.append((doc, recall_floor(doc, lines, units, report)))
    return out, report


def score(docs, proposals, p: float):
    """Gate at `p`, then score. Returns the three readings and the counts."""
    triples = []
    for doc, spans in proposals:
        pred = [
            {
                "text": s.text(doc),
                "type": s.argmax_type(),
                "position": [s.start, s.end],
                "assertions": [],
                "candidates": [],
            }
            for s in spans
            if s.score >= p
        ]
        triples.append((doc.doc_id, list(doc.entities), pred))

    out = {}
    for name, cfg in (
        ("penalised/greedy_iou", MetricConfig()),
        ("penalised/overlap_type", MetricConfig(alignment="overlap_type")),
        ("matched/greedy_iou", MetricConfig(aggregation="matched")),
    ):
        r = score_corpus(triples, cfg)
        out[name] = r
    out["_triples"] = triples
    out["_n_pred"] = sum(len(p) for _, _, p in triples)
    return out


def bootstrap_delta(base, other, seed: int = 20260730) -> tuple[float, float, float]:
    """Paired bootstrap over documents: (mean Δ, lo, hi) of the /100 difference."""
    a = [d["text"] * 0.3 + d["assertions"] * 0.3 + d["candidates"] * 0.4
         for d in base["penalised/greedy_iou"]["per_doc"]]
    b = [d["text"] * 0.3 + d["assertions"] * 0.3 + d["candidates"] * 0.4
         for d in other["penalised/greedy_iou"]["per_doc"]]
    rng = random.Random(seed)
    n = len(a)
    deltas = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        deltas.append(
            100 * (statistics.mean(b[i] for i in idx) - statistics.mean(a[i] for i in idx))
        )
    deltas.sort()
    return (
        100 * (statistics.mean(b) - statistics.mean(a)),
        deltas[int(0.025 * RESAMPLES)],
        deltas[int(0.975 * RESAMPLES) - 1],
    )


def show(label, r, baseline=None) -> None:
    g = r["penalised/greedy_iou"]
    t = r["penalised/overlap_type"]
    m = r["matched/greedy_iou"]
    line = (
        f"{label:<22}{g['leaderboard']:>8.2f}{t['leaderboard']:>9.2f}"
        f"{m['leaderboard']:>9.2f}{g['missing']:>9}{g['spurious']:>10}"
        f"{r['_n_pred'] / g['n_docs']:>9.2f}"
    )
    if baseline is not None:
        d, lo, hi = bootstrap_delta(baseline, r)
        bar = max(0.010, 1.96 * ((hi - lo) / (2 * 1.96)))
        verdict = "ACCEPT" if (abs(d) > bar and lo * hi > 0) else "noise"
        line += f"   Δ{d:+7.2f}  CI95[{lo:+.2f},{hi:+.2f}] {verdict}"
    print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--knob", default="emit_p", choices=("emit_p",))
    ap.add_argument("--values", default="0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65")
    args = ap.parse_args(argv)

    docs = load_gold()
    proposals, report = propose(docs)
    print(f"lane R     : {report.summary()}")
    print(
        f"gate        : constant p from configs/pipeline.yaml = "
        f"{emit.select_threshold(report.density()).p}"
    )
    print()
    print(
        f"{'setting':<22}{'greedy':>8}{'ovl_type':>9}{'matched':>9}"
        f"{'missing':>9}{'spurious':>10}{'pred/file':>9}"
    )

    baseline = None
    for value in [float(v) for v in args.values.split(",")]:
        r = score(docs, proposals, value)
        show(f"emit_p={value:.2f}", r, baseline)
        if baseline is None:
            baseline = r
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
