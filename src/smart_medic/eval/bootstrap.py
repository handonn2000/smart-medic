"""Paired bootstrap over documents — the only thing that turns a delta into a claim.

    Δ > max(0.010 ; 1.96·SE_bootstrap)   AND   CI95 excludes 0

Two systems that miss entities in *different places* are indistinguishable below
~0.8 points even when they miss the same fraction (measured SE 0.415). The 0.010
floor is only valid for a highly-correlated pair — same pipeline, one changed
post-processing step. This module is what tells the two cases apart.

Why it is fast, and why it is still exact
-----------------------------------------
Each document is scored **once**; the 10.000 replicates then resample four
precomputed per-document arrays. No re-scoring, and no approximation:

    leaderboard = 100 · [ 0.3·mean_i(text_i) + 0.3·mean_i(assert_i)
                        + 0.4·(Σ_i cand_i·W_i / Σ_i W_i) ]

Text and assertions are plain means, so their replicate deltas are means of the
per-document differences. Candidates is a **weighted** mean (the official W_i =
Σ_k(len(gt(k))+1)), so it is a ratio of sums and does *not* collapse that way —
an earlier version of this module treated it as if it did, and was wrong by
whatever the weight/score correlation happened to be.

What rescues it: **W_i depends on gold alone**, so the two systems in a paired
comparison share it exactly. The candidates delta is therefore still a single
ratio over the resampled documents:

    Δcand = Σ_i (cand_b,i − cand_a,i)·W_i / Σ_i W_i

Four sums per replicate, all exact. `test_doc_terms_reproduce_score_corpus`
pins the identity against `score_corpus` so this can never drift into being an
approximation unnoticed.

Usage
-----
    python3 -m smart_medic.eval.bootstrap --gold GOLD --a DIR_A --b DIR_B
    python3 -m smart_medic.eval.bootstrap --calibrate --gold GOLD
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from dataclasses import asdict, dataclass
from math import fsum
from pathlib import Path

from .scoring import (
    W_ASSERT,
    W_CAND,
    W_TEXT,
    MetricConfig,
    load_dir,
    score_corpus,
    score_document,
    sort_key,
)

#: B in the plan. Not a knob you should be turning per-run.
REPS = 10_000
#: Fixed so two people running the same comparison get the same CI.
SEED = 20260730
#: The correlated-pair floor from ADR 0002. Never the only condition.
FLOOR = 0.010


# ─────────────────────────── per-document terms ───────────────────────────
#: (text, assertions, candidates, candidate weight) for one document.
Terms = tuple[float, float, float, float]


def doc_terms(docs: list[tuple[str, list, list]], cfg: MetricConfig) -> list[Terms]:
    """Score every document once. `corpus_score(...)` reassembles the total."""
    out: list[Terms] = []
    for _, gold, pred in docs:
        d = score_document(gold, pred, cfg)
        out.append(
            (d["text"], d["assertions"], d["candidates"], d.get("cand_weight", 1.0))
        )
    return out


def corpus_score(terms: list[Terms]) -> float:
    """Leaderboard-scale total. Identical to `score_corpus(...)['leaderboard']`."""
    n = len(terms)
    if not n:
        return 0.0
    t = fsum(x[0] for x in terms) / n
    a = fsum(x[1] for x in terms) / n
    wsum = fsum(x[3] for x in terms)
    c = (fsum(x[2] * x[3] for x in terms) / wsum) if wsum else 1.0
    return 100 * (W_TEXT * t + W_ASSERT * a + W_CAND * c)


# ────────────────────────────────── result ──────────────────────────────────
@dataclass(frozen=True)
class Delta:
    """Everything needed to accept or reject a change. Print all of it."""

    n_docs: int
    reps: int
    mean_a: float
    mean_b: float
    delta: float
    se: float
    ci_lo: float
    ci_hi: float
    mde: float
    bar: float
    passes: bool

    def verdict(self) -> str:
        if self.passes:
            return "CẢI TIẾN THẬT" if self.delta > 0 else "SUY GIẢM THẬT"
        return "dưới sàn nhiễu"

    def line(self) -> str:
        return (
            f"Δ={self.delta:+.3f}  SE={self.se:.3f}  "
            f"CI95=[{self.ci_lo:+.3f}; {self.ci_hi:+.3f}]  "
            f"MDE={self.mde:.3f}  bar={self.bar:.3f}  → {self.verdict()}"
        )


def paired_bootstrap(
    a_terms: list[Terms],
    b_terms: list[Terms],
    *,
    reps: int = REPS,
    seed: int = SEED,
    floor: float = FLOOR,
) -> Delta:
    """Resample documents with replacement; B − A on every replicate."""
    if len(a_terms) != len(b_terms):
        raise ValueError(
            f"paired bootstrap needs the same documents on both sides: "
            f"{len(a_terms)} vs {len(b_terms)}"
        )
    n = len(a_terms)
    if n < 2:
        raise ValueError("need at least 2 documents to bootstrap")

    # W_i is a function of gold only, so both sides must agree on it. If they do
    # not, the two `docs` lists were built against different gold — the delta
    # would be meaningless and the ratio below silently wrong.
    for k, (a, b) in enumerate(zip(a_terms, b_terms)):
        if a[3] != b[3]:
            raise ValueError(
                f"document {k}: candidate weight differs between the two sides "
                f"({a[3]} vs {b[3]}) — they are not scored against the same gold"
            )

    d_text = [b[0] - a[0] for a, b in zip(a_terms, b_terms)]
    d_assert = [b[1] - a[1] for a, b in zip(a_terms, b_terms)]
    weight = [a[3] for a in a_terms]
    d_cand_w = [(b[2] - a[2]) * a[3] for a, b in zip(a_terms, b_terms)]

    def delta_over(idx) -> float:
        t = fsum(d_text[i] for i in idx) / len(idx)
        a = fsum(d_assert[i] for i in idx) / len(idx)
        wsum = fsum(weight[i] for i in idx)
        c = (fsum(d_cand_w[i] for i in idx) / wsum) if wsum else 0.0
        return 100 * (W_TEXT * t + W_ASSERT * a + W_CAND * c)

    observed = delta_over(range(n))

    rng = random.Random(seed)
    pool = range(n)
    reps_vals = [delta_over(rng.choices(pool, k=n)) for _ in range(reps)]
    reps_vals.sort()

    se = statistics.stdev(reps_vals)
    lo = reps_vals[int(0.025 * reps)]
    hi = reps_vals[min(reps - 1, int(0.975 * reps))]
    mde = 1.96 * se
    bar = max(floor, mde)
    return Delta(
        n_docs=n,
        reps=reps,
        mean_a=corpus_score(a_terms),
        mean_b=corpus_score(b_terms),
        delta=observed,
        se=se,
        ci_lo=lo,
        ci_hi=hi,
        mde=mde,
        bar=bar,
        # both conditions, never just one
        passes=abs(observed) > bar and not (lo <= 0.0 <= hi),
    )


def compare_dirs(
    gold_dir: Path,
    a_dir: Path,
    b_dir: Path,
    cfg: MetricConfig,
    *,
    reps: int = REPS,
    seed: int = SEED,
) -> Delta:
    """Score two prediction directories against one gold and bootstrap the delta."""
    gold, a, b = load_dir(gold_dir), load_dir(a_dir), load_dir(b_dir)
    common = sorted(set(gold) & set(a) & set(b), key=sort_key)
    if not common:
        raise SystemExit("no document ids common to --gold, --a and --b")
    docs_a = [(k, gold[k], a[k]) for k in common]
    docs_b = [(k, gold[k], b[k]) for k in common]
    return paired_bootstrap(
        doc_terms(docs_a, cfg), doc_terms(docs_b, cfg), reps=reps, seed=seed
    )


# ───────────────────────────── calibration cases ─────────────────────────────
# Four mutations, reimplemented here because eval/ may not import scripts/ (see
# tests/test_layer_boundaries.py). scripts/analysis/leverage_map.py holds the
# authoritative versions; `--calibrate` printing the reference Δ next to the
# measured Δ is what catches drift between the two copies.
#
# RE-BASELINED 2026-07-30, after scoring.py was corrected to the published spec.
# The plan-v4 tab 05 §A.4 figures were measured while candidates scored 0.00 for
# any prediction carrying no codes, so three of the four were understated: a
# missed entity now also costs its candidates, and a wrong code costs a real
# Jaccard instead of nothing. `bỏ cờ isFamily` is unchanged because it touches
# assertions only — which is exactly why it is the one row that validates the
# re-baseline rather than being invalidated by it.
#
#   row                       plan-v4 (obsolete)     corrected
#   bỏ cờ isFamily            −0.261  SE 0.052       −0.261  SE 0.053
#   sai 30% mã                −2.856  SE 0.123       −3.922  SE 0.196
#   bỏ 10% entity             −7.043  SE 0.287      −10.164  SE 0.378
#   bỏ 10%: seedA vs seedB    −0.105  SE 0.415       −0.067  SE 0.531
#
# The last row is the operational number: the noise floor between two systems
# that miss entities in DIFFERENT places is now ~1.04 points, not ~0.84.
CALIBRATION = {  # name -> (Δ, SE), measured under the corrected spec
    "bỏ cờ isFamily": (-0.261, 0.053),
    "sai 30% mã": (-3.922, 0.196),
    "bỏ 10% entity": (-10.164, 0.378),
    "bỏ 10%: seedA vs seedB": (-0.067, 0.531),
}


def _clone(ents: list[dict]) -> list[dict]:
    return json.loads(json.dumps(ents))


def _drop_flag(docs, flag):
    out = []
    for k, ents in docs:
        ents = _clone(ents)
        for e in ents:
            e["assertions"] = [a for a in e.get("assertions", []) if a != flag]
        out.append((k, ents))
    return out


def _wrong_codes(docs, frac, rng):
    pool = sorted({c for _, ents in docs for e in ents for c in e.get("candidates", [])})
    out = []
    for k, ents in docs:
        ents = _clone(ents)
        for e in ents:
            if e.get("candidates") and rng.random() < frac:
                e["candidates"] = [pool[rng.randrange(len(pool))]]
        out.append((k, ents))
    return out


def _drop_entities(docs, frac, rng):
    return [(k, [e for e in ents if rng.random() >= frac]) for k, ents in docs]


def calibrate(gold_dir: Path, *, reps: int = REPS, seed: int = SEED) -> dict:
    """Reproduce the four published calibration rows. Gold is its own prediction."""
    gold = load_dir(gold_dir)
    keys = sorted(gold, key=sort_key)
    base = [(k, gold[k]) for k in keys]
    cfg = MetricConfig()

    def points(pred_docs):
        return doc_terms([(k, gold[k], p) for k, p in pred_docs], cfg)

    perfect = points(base)
    cases = {
        "bỏ cờ isFamily": (perfect, points(_drop_flag(base, "isFamily"))),
        "sai 30% mã": (perfect, points(_wrong_codes(base, 0.30, random.Random(0)))),
        "bỏ 10% entity": (perfect, points(_drop_entities(base, 0.10, random.Random(0)))),
        "bỏ 10%: seedA vs seedB": (
            points(_drop_entities(base, 0.10, random.Random(0))),
            points(_drop_entities(base, 0.10, random.Random(1))),
        ),
    }
    return {
        name: paired_bootstrap(a, b, reps=reps, seed=seed)
        for name, (a, b) in cases.items()
    }


# ──────────────────────────────────── cli ────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--a", type=Path, help="baseline prediction directory")
    ap.add_argument("--b", type=Path, help="candidate prediction directory")
    ap.add_argument("--alignment", default="greedy_iou",
                    choices=("greedy_iou", "overlap", "overlap_type", "exact"))
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--calibrate", action="store_true",
                    help="reproduce the four published calibration rows")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    payload: dict = {"reps": args.reps, "seed": args.seed}

    if args.calibrate:
        print(f"\n── HIỆU CHUẨN BOOTSTRAP ── gold={args.gold}  B={args.reps:,}")
        print(f"{'so sánh':<26}{'Δ đo':>9}{'Δ plan':>9}{'SE đo':>8}{'SE plan':>9}"
              f"{'CI95':>22}{'MDE':>8}")
        rows = calibrate(args.gold, reps=args.reps, seed=args.seed)
        drift = []
        for name, d in rows.items():
            pd, pse = CALIBRATION[name]
            print(f"{name:<26}{d.delta:>9.3f}{pd:>9.3f}{d.se:>8.3f}{pse:>9.3f}"
                  f"{f'[{d.ci_lo:+.3f}; {d.ci_hi:+.3f}]':>22}{d.mde:>8.3f}")
            if abs(d.delta - pd) > 0.15 or abs(d.se - pse) > 0.08:
                drift.append(name)
        payload["calibration"] = {
            k: {**asdict(v), "plan_delta": CALIBRATION[k][0], "plan_se": CALIBRATION[k][1]}
            for k, v in rows.items()
        }
        if drift:
            print(f"\n  !! LỆCH so với plan ở: {', '.join(drift)}")
            print("     Gold hoặc bộ tạo nhiễu đã đổi — đối chiếu với "
                  "scripts/analysis/leverage_map.py trước khi tin bảng này.")
        else:
            print("\n  ✓ cả bốn ca khớp bảng plan-v4 tab 05 §A.4")
        print("\n  Hàng cuối là điều quan trọng nhất: hai hệ bỏ sót ở CHỖ KHÁC NHAU "
              f"không phân giải được dưới ~{rows['bỏ 10%: seedA vs seedB'].mde:.2f} điểm.")

    if args.a and args.b:
        cfg = MetricConfig(alignment=args.alignment)
        d = compare_dirs(args.gold, args.a, args.b, cfg, reps=args.reps, seed=args.seed)
        print(f"\n── PAIRED BOOTSTRAP ── {args.alignment} · penalised · "
              f"n={d.n_docs} tài liệu · B={args.reps:,}")
        print(f"  A = {args.a}   {d.mean_a:.3f}")
        print(f"  B = {args.b}   {d.mean_b:.3f}")
        print(f"  {d.line()}")
        if not d.passes and abs(d.delta) > FLOOR:
            print("     (Δ vượt sàn 0,010 nhưng KHÔNG vượt nhiễu — viết "
                  "'dưới sàn nhiễu', đừng viết 'cải thiện nhỏ'.)")
        payload["comparison"] = {"a": str(args.a), "b": str(args.b),
                                 "alignment": args.alignment, **asdict(d)}
    elif bool(args.a) != bool(args.b):
        print("--a and --b go together", file=sys.stderr)
        return 2
    elif not args.calibrate:
        print("nothing to do: pass --calibrate, or --a and --b", file=sys.stderr)
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
