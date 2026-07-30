"""Internal scorer for the Viettel AI Race 2026 Vòng-1 metric.

    final = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score

The organisers have now published the full formula, so this module implements it
rather than guessing at it. Rewritten 2026-07-30 (see ADR 0002, "Đặc tả CHÍNH
THỨC"); the three switchable axes are kept, but the defaults are no longer a
choice — they are what the spec says.

    text_score       = Σ_i (1 − WER(i)) / len(test)
    assertions_score = Σ_i J_assertions(i) / len(test)
    candidates_score = Σ_i J_candidates(i)·W_i / Σ_i W_i
                       with  W_i = Σ_{k∈i} (len(ground_truth(k)) + 1)

`i` is a **sample (document)**, `k` a concept inside it. `J_X(i)` is the mean
per-concept Jaccard on field X, with the spec's empty conventions: 1 when gold
and prediction are both empty, 0 when gold is empty and the prediction is not.

Three corrections that cost 16.53 points of measurement error before this
rewrite, each one now pinned by a test:

1. **The `+1` is a per-DOCUMENT WEIGHT, not a denominator.** It never enters
   `J`, so it caps nothing: a perfect prediction scores 1.0 on candidates, not
   0.2501. The previous reading (`Σ|gt∩pred| / Σ(len(gt)+1)`) returned exactly
   0.00 whenever the prediction carried no codes — an intersection with the
   empty set — which is how a submission that really scored 41.68 on candidates
   was being reported as 0.00.

2. **Alignment compares `type`.** Spec: predicting the right text with the wrong
   type "counts twice, and scores 0 each time on all three metrics". So a type
   error costs double — the unmatched gold and the spurious prediction. That is
   `overlap_type` + `penalised`, and it is the DEFAULT. `greedy_iou` is kept
   only as a diagnostic: it ignores `type` entirely, so it can never show you
   what a type fix is worth.

3. **`1 − WER(i)` is NOT clamped at 0.** The spec has no `max(0, ·)`. WER is
   unbounded above, so a short gold span against a long prediction can push a
   document negative. `clamp_text=True` is available to quantify the difference;
   it is not the official reading.

The axes that remain genuinely switchable:

  ALIGNMENT     overlap_type (default, official) · greedy_iou · overlap · exact
  AGGREGATION   penalised (default, official) — unmatched gold and unmatched
                predictions each score 0 on all three fields.
                matched — scores aligned pairs only. DEGENERATE: dropping
                low-confidence predictions raises it. A ceiling, never a target.
                docbag — no alignment at all; one WER over concatenated text and
                one Jaccard over pooled multisets. A sanity check on
                over-generation.
  CAND_FORMULA  official (default, weighted by W_i) · plain (unweighted mean of
                the per-document J, to show how much the weighting moves)

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
    #: Defaults ARE the published spec. Changing one makes the number unofficial.
    alignment: str = "overlap_type"
    aggregation: str = "penalised"
    cand_formula: str = "official"
    clamp_text: bool = False
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

    texts, asserts, cands = [], [], []

    for i, j in pairs:
        g, p = gold[i], pred[j]
        w = wer(g["text"], p["text"])
        texts.append(max(0.0, 1 - w) if cfg.clamp_text else 1 - w)
        asserts.append(jaccard(g.get("assertions", []), p.get("assertions", [])))
        cands.append(jaccard(g.get("candidates", []), p.get("candidates", [])))

    if cfg.aggregation == "penalised":
        # Spec, closing note: a right-text/wrong-type concept "counts twice and
        # scores 0 each time on all three metrics". One zero for the gold concept
        # nobody matched, one for the prediction that matched nothing.
        for _ in range(len(miss) + len(spur)):
            texts.append(0.0)
            asserts.append(0.0)
            cands.append(0.0)

    # W_i = Σ_{k∈i}(len(ground_truth(k)) + 1). A per-document weight for the
    # corpus average — it is NOT inside J and caps nothing. Computed from GOLD
    # alone, so it is identical for every system scored against this gold, which
    # is what lets a paired bootstrap share it across both sides.
    weight = (
        float(sum(len(set(e.get("candidates") or [])) + 1 for e in gold))
        if cfg.cand_formula == "official"
        else 1.0
    )

    return {
        "text": statistics.mean(texts) if texts else 1.0,
        "assertions": statistics.mean(asserts) if asserts else 1.0,
        "candidates": statistics.mean(cands) if cands else 1.0,
        "cand_weight": weight,
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
    # text and assertions are plain means over documents; candidates is a
    # WEIGHTED mean, which is the one place the corpus score stops being linear
    # in the per-document values. eval/bootstrap.py resamples the weight too.
    wsum = sum(d.get("cand_weight", 1.0) for d in per)
    c = (
        sum(d["candidates"] * d.get("cand_weight", 1.0) for d in per) / wsum
        if wsum
        else 1.0
    )
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
        for al in (("overlap_type",) if agg == "docbag"
                   else ("overlap_type", "greedy_iou", "exact")):
            cfg = MetricConfig(alignment=al, aggregation=agg,
                               cand_formula=args.cand_formula)
            r = score_corpus(docs, cfg)
            results[f"{agg}/{al}"] = {k: v for k, v in r.items() if k != "per_doc"}
            flag = (
                "  <<< OFFICIAL" if (agg == "penalised" and al == "overlap_type")
                else "  (ignores type)" if al == "greedy_iou"
                else "  (offset alarm)" if al == "exact"
                else ""
            )
            print(f"{agg:<14}{al:<14}{r['text_score']:>8.4f}"
                  f"{r['assertions_score']:>9.4f}{r['candidates_score']:>8.4f}"
                  f"{r['final_score']:>9.4f}{r['leaderboard']:>8.2f}{flag}")

    primary = MetricConfig(cand_formula=args.cand_formula)
    r = score_corpus(docs, primary)
    print(f"\n  config hash {primary.hash()}   "
          f"missing={r['missing']}  spurious={r['spurious']}")
    if args.cand_formula == "official":
        alt = score_corpus(docs, MetricConfig(cand_formula="plain"))
        print(f"  candidates unweighted ('plain'): {alt['candidates_score']:.4f}  "
              f"→ the W_i weighting moves it "
              f"{r['candidates_score']-alt['candidates_score']:+.4f}")
    if not primary.clamp_text:
        clamped = score_corpus(docs, MetricConfig(cand_formula=args.cand_formula,
                                                 clamp_text=True))
        gap = clamped["text_score"] - r["text_score"]
        print(f"  text with 1−WER clamped at 0: {clamped['text_score']:.4f}  "
              f"→ documents pushed negative by unbounded WER cost {gap:+.4f}"
              + ("  (spec does NOT clamp)" if gap else ""))

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
