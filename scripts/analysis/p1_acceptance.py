#!/usr/bin/env python3
"""The P1 acceptance criteria, each one printed with the number that decides it.

    PYTHONPATH=src python3 scripts/analysis/p1_acceptance.py

Not on the path to `output.zip`. It exists so the phase gate is a command rather
than a claim: every line prints PASS/FAIL next to the measured value, and a
criterion that is missed prints the real figure rather than a rounded one.

The gate that is hard: `penalised/greedy_iou` >= 14.5 on gold. Below that, P2 and
P3 do not start.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.eval.scoring import MetricConfig, align, score_corpus  # noqa: E402
from smart_medic.extract import RecallFloorReport, recall_floor  # noqa: E402
from smart_medic.io.corpus import load_gold  # noqa: E402
from smart_medic.io.labels import LAB_TYPES  # noqa: E402
from smart_medic.layout.kv import split_units  # noqa: E402
from smart_medic.layout.lines import split_lines  # noqa: E402
from smart_medic.validate import offsets, schema  # noqa: E402

PASS, FAIL = "\x1b[32m[PASS]\x1b[0m", "\x1b[31m[FAIL]\x1b[0m"


def gate(ok: bool, label: str, detail: str) -> bool:
    print(f"  {PASS if ok else FAIL} {label:<52} {detail}")
    return ok


def prf(tp: int, n_pred: int, n_gold: int) -> tuple[float, float]:
    return (tp / n_pred if n_pred else 0.0, tp / n_gold if n_gold else 0.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--p", type=float, default=None, help="override the emit gate")
    args = ap.parse_args(argv)

    from smart_medic.decision import emit

    docs = load_gold()
    report = RecallFloorReport()
    t0 = time.perf_counter()
    proposals = []
    for doc in docs:
        lines = split_lines(doc)
        units = split_units(doc, lines)
        proposals.append((doc, recall_floor(doc, lines, units, report)))
    elapsed = time.perf_counter() - t0

    p = args.p if args.p is not None else emit.select_threshold(report.density()).p
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
        triples.append((doc, list(doc.entities), pred))

    scored = [(d.doc_id, g, pr) for d, g, pr in triples]
    primary = score_corpus(scored, MetricConfig())
    blocking = score_corpus(scored, MetricConfig(alignment="overlap_type"))
    exact = score_corpus(scored, MetricConfig(alignment="exact"))
    ceiling = score_corpus(scored, MetricConfig(aggregation="matched"))
    n_pred = sum(len(pr) for _, _, pr in scored)
    density = n_pred / len(scored)

    print(f"\nlane R  : {report.summary()}")
    print(f"gate    : p={p}\n")
    print("── THREE ALIGNMENTS ──────────────────────────────────────────────")
    print(f"  greedy_iou   (OFFICIAL)   {primary['leaderboard']:>7.2f}/100")
    print(f"  overlap_type (BLOCKING)   {blocking['leaderboard']:>7.2f}/100")
    print(f"  exact        (OFFSET BUG) {exact['leaderboard']:>7.2f}/100")
    print(f"  matched      (ceiling)    {ceiling['leaderboard']:>7.2f}/100")
    print(
        f"\n  missing {primary['missing']}   spurious {primary['spurious']}   "
        f"density {density:.2f} entities/file (gold 45.9, ratio {density / 45.9:.3f})"
    )

    print("\n── ACCEPTANCE ────────────────────────────────────────────────────")
    ok = True

    # 1 · the two lab types, recall >= 0.70 and precision >= 0.80
    tp = n_p = n_g = 0
    for _, gold, pred in scored:
        g = [e for e in gold if e["type"] in LAB_TYPES]
        pr = [e for e in pred if e["type"] in LAB_TYPES]
        n_g += len(g)
        n_p += len(pr)
        pairs, _, _ = align(g, pr, "overlap_type")
        tp += len(pairs)
    prec, rec = prf(tp, n_p, n_g)
    ok &= gate(
        rec >= 0.70 and prec >= 0.80,
        "lab types: recall >= 0.70 and precision >= 0.80",
        f"recall {rec:.3f}  precision {prec:.3f}  (gold {n_g}, pred {n_p})",
    )

    # 2 · aho span recall on its own
    aho_tp = 0
    for doc, gold, _ in triples:
        spans = [s for s in dict(proposals)[doc] if s.source == "aho"]
        pr = [{"position": [s.start, s.end], "type": s.argmax_type()} for s in spans]
        pairs, _, _ = align(gold, pr, "greedy_iou")
        aho_tp += len(pairs)
    n_gold_all = sum(len(g) for _, g, _ in scored)
    aho_recall = aho_tp / n_gold_all
    ok &= gate(
        aho_recall >= 0.30,
        "aho.py span recall alone >= 0.30",
        f"{aho_recall:.3f}  ({aho_tp}/{n_gold_all})",
    )

    # 3 · the hard gate
    ok &= gate(
        primary["leaderboard"] >= 14.5,
        "gold penalised/greedy_iou >= 14.5   << HARD GATE",
        f"{primary['leaderboard']:.2f}",
    )

    # 4 · no nested spans
    nested = 0
    for _, _, pred in scored:
        pos = [tuple(e["position"]) for e in pred]
        for a in pos:
            for b in pos:
                if a != b and a[0] <= b[0] and b[1] <= a[1]:
                    nested += 1
    ok &= gate(nested == 0, "0 nested spans in output", f"{nested} found")

    # 5 · offsets exact against the ORIGINAL, un-normalised string
    bad = 0
    for doc, _, pred in triples:
        bad += len(offsets.check(doc.raw, pred, doc.doc_id))
    ok &= gate(bad == 0, "raw[s:e] == text on every span", f"{bad} violations")

    # 6 · schema, including the 11.59-point assertions constraint
    codes = schema.load_code_index()
    errs: list[str] = []
    for doc, _, pred in triples:
        errs += schema.check(pred, doc.raw, codes, doc.doc_id)
    ok &= gate(not errs, "schema clean (incl. lab assertions empty)", f"{len(errs)} errors")

    print(f"\n  lane R wall clock on 162 gold files: {elapsed:.1f}s, no checkpoint")
    print(f"\n{'ALL CRITERIA MET' if ok else 'SOME CRITERIA NOT MET — see FAIL above'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
