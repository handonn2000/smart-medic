"""Internal scorer for the Viettel AI Race 2026 Vòng-1 metric.

    final = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score

The official statement leaves three things undefined. This module makes each an
explicit, switchable axis instead of an assumption, and reports every
combination so you can see when a change only "wins" under one reading.

1. ENTITY ALIGNMENT — how a predicted entity is paired with a gold one before
   per-entity scores are computed. The spec gives no rule.
       greedy_iou (default) · overlap · overlap_type · exact

2. AGGREGATION — what happens to unmatched entities.
       A "matched"   score only aligned pairs. The literal reading, and
                     DEGENERATE: dropping low-confidence predictions raises it.
                     Keep as a ceiling; never optimise against it.
       B "penalised" unmatched gold and unmatched predictions each score 0.
                     The only reading that penalises over- and under-generation
                     monotonically. >>> Use this as the primary number. <<<
       C "docbag"    no alignment: one WER over the concatenated texts, one
                     Jaccard over the pooled assertion/code multisets.

3. CANDIDATES FORMULA — the official denominator carries a `+1`:
       Σ_k |gt(k) ∩ pred(k)|  /  Σ_k (len(gt(k)) + 1)
   which caps the term well below 1 (≈0.45 on our measured cardinality mix).
   `--cand-formula plain` swaps in an ordinary mean Jaccard so you can see how
   much of your score the `+1` is eating.

Usage
-----
    python -m smart_medic.eval.scoring --pred data/output --gold data/dev_gold
    python -m smart_medic.eval.scoring --pred data/output --describe     # no gold
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

RECORD = re.compile(r"^\d+$")
TYPES = ("TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC")
CODEABLE = {"CHẨN_ĐOÁN", "THUỐC"}
W_TEXT, W_ASSERT, W_CAND = 0.3, 0.3, 0.4


# ────────────────────────────── primitives ──────────────────────────────
def wer(ref: str, hyp: str) -> float:
    """Word Error Rate. Unbounded above — the caller decides about clamping."""
    r, h = ref.split(), hyp.split()
    if not r:
        return 0.0 if not h else float(len(h))
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def jaccard(gold: Iterable, pred: Iterable) -> float:
    """Official convention: 1 when both empty, 0 when gold empty but pred is not."""
    g, p = set(gold), set(pred)
    if not g and not p:
        return 1.0
    if not (g | p):
        return 1.0
    return len(g & p) / len(g | p)


def iou(a: Sequence[int], b: Sequence[int]) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0, hi - lo)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


@dataclass(frozen=True)
class MetricConfig:
    alignment: str = "greedy_iou"
    aggregation: str = "penalised"
    cand_formula: str = "official"
    clamp_text: bool = True
    doc_aggregation: str = "macro"

    def hash(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()[:12]


# ─────────────────────────────── alignment ───────────────────────────────
def align(gold: list[dict], pred: list[dict], mode: str) -> tuple[list, list, list]:
    """Return (pairs, unmatched_gold_idx, unmatched_pred_idx). Deterministic."""
    pairs: list[tuple[int, int]] = []
    gused: set[int] = set()
    pused: set[int] = set()

    if mode == "exact":
        index: dict[tuple, int] = {}
        for j, p in enumerate(pred):
            index.setdefault((tuple(p["position"]), p["type"]), j)
        for i, g in enumerate(gold):
            j = index.get((tuple(g["position"]), g["type"]))
            if j is not None and j not in pused:
                pairs.append((i, j))
                gused.add(i)
                pused.add(j)
    else:
        cands = []
        for i, g in enumerate(gold):
            for j, p in enumerate(pred):
                ov = iou(g["position"], p["position"])
                if ov <= 0:
                    continue
                if mode == "overlap_type" and g["type"] != p["type"]:
                    continue
                cands.append((-ov, i, j))
        cands.sort()  # by -iou, then gold idx, then pred idx: fully deterministic
        for _, i, j in cands:
            if i in gused or j in pused:
                continue
            pairs.append((i, j))
            gused.add(i)
            pused.add(j)

    return (
        pairs,
        [i for i in range(len(gold)) if i not in gused],
        [j for j in range(len(pred)) if j not in pused],
    )


# ──────────────────────────── per-document score ─────────────────────────
def score_document(gold: list[dict], pred: list[dict], cfg: MetricConfig) -> dict:
    if cfg.aggregation == "docbag":
        gt_txt = " ".join(e["text"] for e in gold)
        pr_txt = " ".join(e["text"] for e in pred)
        w = wer(gt_txt, pr_txt)
        t = max(0.0, 1 - w) if cfg.clamp_text else 1 - w
        # pooled sets, position-independent
        a = jaccard(
            [x for e in gold for x in e.get("assertions", [])],
            [x for e in pred for x in e.get("assertions", [])],
        )
        c = jaccard(
            [x for e in gold for x in e.get("candidates", [])],
            [x for e in pred for x in e.get("candidates", [])],
        )
        return {"text": t, "assertions": a, "candidates": c, "n_pairs": len(gold)}

    pairs, miss, spur = align(gold, pred, cfg.alignment)

    texts, asserts = [], []
    cand_num = 0.0
    cand_den = 0.0

    for i, j in pairs:
        g, p = gold[i], pred[j]
        w = wer(g["text"], p["text"])
        texts.append(max(0.0, 1 - w) if cfg.clamp_text else 1 - w)
        asserts.append(jaccard(g.get("assertions", []), p.get("assertions", [])))
        gc, pc = set(g.get("candidates", [])), set(p.get("candidates", []))
        if cfg.cand_formula == "official":
            cand_num += len(gc & pc)
            cand_den += len(gc) + 1
        else:
            cand_num += jaccard(gc, pc)
            cand_den += 1

    if cfg.aggregation == "penalised":
        for i in miss:
            texts.append(0.0)
            asserts.append(0.0)
            if cfg.cand_formula == "official":
                cand_den += len(set(gold[i].get("candidates", []))) + 1
            else:
                cand_den += 1
        for _ in spur:
            texts.append(0.0)
            asserts.append(0.0)
            cand_den += 1

    return {
        "text": statistics.mean(texts) if texts else 1.0,
        "assertions": statistics.mean(asserts) if asserts else 1.0,
        "candidates": (cand_num / cand_den) if cand_den else 1.0,
        "n_pairs": len(pairs),
        "n_missing": len(miss),
        "n_spurious": len(spur),
    }


def score_corpus(docs: list[tuple[str, list, list]], cfg: MetricConfig) -> dict:
    per = [score_document(g, p, cfg) for _, g, p in docs]
    if not per:
        return {}
    t = statistics.mean(d["text"] for d in per)
    a = statistics.mean(d["assertions"] for d in per)
    c = statistics.mean(d["candidates"] for d in per)
    return {
        "text_score": t,
        "assertions_score": a,
        "candidates_score": c,
        "final_score": W_TEXT * t + W_ASSERT * a + W_CAND * c,
        "leaderboard": 100 * (W_TEXT * t + W_ASSERT * a + W_CAND * c),
        "n_docs": len(per),
        "missing": sum(d.get("n_missing", 0) for d in per),
        "spurious": sum(d.get("n_spurious", 0) for d in per),
        "per_doc": per,
    }


# ───────────────────────────── diagnostics ──────────────────────────────
def diagnostics(docs: list[tuple[str, list, list]]) -> dict:
    strict = Counter()
    relaxed = Counter()
    gold_n = Counter()
    pred_n = Counter()
    boundary = Counter()
    deltas: list[int] = []
    a_tp = Counter()
    a_fp = Counter()
    a_fn = Counter()
    code_hit = code_tot = 0
    type_conf = Counter()

    for _, gold, pred in docs:
        for e in gold:
            gold_n[e["type"]] += 1
        for e in pred:
            pred_n[e["type"]] += 1

        pairs, _, _ = align(gold, pred, "greedy_iou")
        for i, j in pairs:
            g, p = gold[i], pred[j]
            same_span = tuple(g["position"]) == tuple(p["position"])
            same_type = g["type"] == p["type"]
            if same_span and same_type:
                strict[g["type"]] += 1
            if same_span:
                relaxed[g["type"]] += 1
            if not same_type:
                type_conf[(g["type"], p["type"])] += 1

            ds, de = p["position"][0] - g["position"][0], p["position"][1] - g["position"][1]
            if (ds, de) != (0, 0):
                deltas += [ds, de]
                tag = (
                    "left-extended" if ds < 0 and de == 0
                    else "right-extended" if ds == 0 and de > 0
                    else "left-truncated" if ds > 0 and de == 0
                    else "right-truncated" if ds == 0 and de < 0
                    else "both-extended" if ds < 0 and de > 0
                    else "both-truncated" if ds > 0 and de < 0
                    else "shifted"
                )
                boundary[tag] += 1

            ga, pa = set(g.get("assertions", [])), set(p.get("assertions", []))
            for lab in ("isNegated", "isFamily", "isHistorical"):
                if lab in ga and lab in pa:
                    a_tp[lab] += 1
                elif lab in pa:
                    a_fp[lab] += 1
                elif lab in ga:
                    a_fn[lab] += 1

            if g["type"] in CODEABLE and g.get("candidates"):
                code_tot += 1
                if set(g["candidates"]) & set(p.get("candidates", [])):
                    code_hit += 1

    def prf(tp, npred, ngold):
        p = tp / npred if npred else 0.0
        r = tp / ngold if ngold else 0.0
        return p, r, (2 * p * r / (p + r) if p + r else 0.0)

    return {
        "per_type": {
            t: {
                "gold": gold_n[t],
                "pred": pred_n[t],
                "strict_f1": prf(strict[t], pred_n[t], gold_n[t])[2],
                "relaxed_f1": prf(relaxed[t], pred_n[t], gold_n[t])[2],
            }
            for t in TYPES
        },
        "boundary_errors": dict(boundary.most_common()),
        "boundary_delta_median": statistics.median(deltas) if deltas else 0,
        "assertions": {
            lab: {
                "tp": a_tp[lab],
                "fp": a_fp[lab],
                "fn": a_fn[lab],
                "f1": prf(a_tp[lab], a_tp[lab] + a_fp[lab], a_tp[lab] + a_fn[lab])[2],
            }
            for lab in ("isNegated", "isFamily", "isHistorical")
        },
        "code_accuracy": (code_hit / code_tot) if code_tot else None,
        "code_scored": code_tot,
        "type_confusions": {f"{a}->{b}": n for (a, b), n in type_conf.most_common(8)},
    }


# ────────────────────────────────── io ───────────────────────────────────
def load_dir(d: Path) -> dict[str, list]:
    """Load every annotation file in a directory, keyed by filename stem.

    Accepts both submission dirs (`1.json`) and corpus dirs
    (`mtsamples_cardio_0001_dan_y.json`). Non-record sidecars such as
    `run_manifest.json` are skipped by shape: a record is a JSON *list*.
    """
    out = {}
    for p in sorted(d.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  !! {p.name}: invalid JSON — {exc}", file=sys.stderr)
            continue
        if isinstance(obj, list):
            out[p.stem] = obj
    return out


def sort_key(k: str):
    return (0, int(k)) if RECORD.match(k) else (1, k)


def describe(pred: dict[str, list]) -> None:
    types = Counter()
    spans: list[int] = []
    ncand = Counter()
    nass = Counter()
    for ents in pred.values():
        for e in ents:
            types[e.get("type")] += 1
            spans.append(len((e.get("text") or "").split()))
            if e.get("type") in CODEABLE:
                ncand[min(len(e.get("candidates") or []), 3)] += 1
            nass[len(e.get("assertions") or [])] += 1
    tot = sum(types.values())
    print(f"  documents            {len(pred)}")
    print(f"  entities             {tot}  ({tot/max(1,len(pred)):.1f} per doc)")
    print("  type distribution")
    for t, n in types.most_common():
        print(f"      {t:<22} {n:>6}  {n/tot:6.1%}")
    if spans:
        spans.sort()
        print(f"  span length (words)  median {spans[len(spans)//2]}  "
              f"mean {statistics.mean(spans):.2f}  max {max(spans)}")
    print(f"  codes/entity (CĐ+thuốc) {dict(sorted(ncand.items()))}")
    print(f"  assertions/entity       {dict(sorted(nass.items()))}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", default="data/output", type=Path)
    ap.add_argument("--gold", type=Path, help="directory of gold N.json files")
    ap.add_argument("--describe", action="store_true",
                    help="structural summary only, no gold needed")
    ap.add_argument("--cand-formula", choices=("official", "plain"), default="official")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    pred = load_dir(args.pred)
    if not pred:
        print(f"no numbered predictions found in {args.pred}", file=sys.stderr)
        return 1

    if args.describe or not args.gold:
        print(f"\n── STRUCTURE of {args.pred} ──")
        describe(pred)
        if not args.gold:
            print("\n(no --gold given, so no score. Hand-label a dev set and pass --gold.)")
        return 0

    gold = load_dir(args.gold)
    common = sorted(set(gold) & set(pred), key=sort_key)
    if not common:
        print("no overlapping record ids between --pred and --gold", file=sys.stderr)
        return 1
    if len(common) < len(gold):
        print(f"note: scoring {len(common)}/{len(gold)} gold documents "
              f"(rest have no prediction)\n")

    docs = [(k, gold[k], pred[k]) for k in common]
    results = {}

    print(f"\n── OFFICIAL SCORE, all three readings ── n={len(docs)} documents")
    print(f"{'aggregation':<14}{'align':<14}{'text':>8}{'assert':>9}"
          f"{'cand':>8}{'final':>9}{'/100':>8}")
    for agg in ("matched", "penalised", "docbag"):
        for al in (("greedy_iou",) if agg == "docbag" else ("greedy_iou", "overlap_type")):
            cfg = MetricConfig(alignment=al, aggregation=agg,
                               cand_formula=args.cand_formula)
            r = score_corpus(docs, cfg)
            results[f"{agg}/{al}"] = {k: v for k, v in r.items() if k != "per_doc"}
            flag = "  <<< primary" if (agg == "penalised" and al == "greedy_iou") else ""
            print(f"{agg:<14}{al:<14}{r['text_score']:>8.4f}"
                  f"{r['assertions_score']:>9.4f}{r['candidates_score']:>8.4f}"
                  f"{r['final_score']:>9.4f}{r['leaderboard']:>8.2f}{flag}")

    primary = MetricConfig(cand_formula=args.cand_formula)
    r = score_corpus(docs, primary)
    print(f"\n  config hash {primary.hash()}   "
          f"missing={r['missing']}  spurious={r['spurious']}")
    if args.cand_formula == "official":
        alt = score_corpus(docs, MetricConfig(cand_formula="plain"))
        print(f"  candidates under 'plain' Jaccard (no +1): "
              f"{alt['candidates_score']:.4f}  "
              f"→ the +1 costs {alt['candidates_score']-r['candidates_score']:+.4f}")

    d = diagnostics(docs)
    print("\n── DIAGNOSTICS ──")
    print(f"{'type':<24}{'gold':>6}{'pred':>6}{'strictF1':>10}{'relaxF1':>9}")
    for t, v in d["per_type"].items():
        print(f"{t:<24}{v['gold']:>6}{v['pred']:>6}"
              f"{v['strict_f1']:>10.3f}{v['relaxed_f1']:>9.3f}")
    if d["boundary_errors"]:
        print(f"\n  boundary errors (median char delta {d['boundary_delta_median']}):")
        for k, n in d["boundary_errors"].items():
            print(f"      {k:<18} {n}")
    print("\n  assertions (on aligned pairs only)")
    for lab, v in d["assertions"].items():
        print(f"      {lab:<14} tp={v['tp']:<5} fp={v['fp']:<5} fn={v['fn']:<5} "
              f"F1={v['f1']:.3f}")
    if d["code_accuracy"] is not None:
        print(f"\n  code hit-rate on {d['code_scored']} codeable gold entities: "
              f"{d['code_accuracy']:.3f}")
    if d["type_confusions"]:
        print("  type confusions (gold->pred):", d["type_confusions"])

    if args.json:
        Path("data/output/metric_internal.json").write_text(
            json.dumps({"config": asdict(primary), "hash": primary.hash(),
                        "results": results, "diagnostics": d},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n  wrote data/output/metric_internal.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
