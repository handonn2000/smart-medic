#!/usr/bin/env python3
"""Regenerate the leverage map: what each failure mode actually costs.

Method: take gold AS the prediction, inject exactly one kind of noise, re-score
with the repo's own scorer. Nothing here is estimated from the task weights.

    python3 scripts/analysis/leverage_map.py                 # table to stdout
    python3 scripts/analysis/leverage_map.py --json out.json # machine-readable

Random modes are averaged over `--seeds` independent runs (default 8) and the
standard deviation is reported, because the seed-to-seed spread is larger than
the difference between several of the failure modes. An earlier version of this
map re-seeded inside the per-document loop, which made "drop 10%" actually drop
15.4% and inflated two cells by ~50%; `Random(seed)` per run is the fix.

Run from the repo root.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.eval.scoring import MetricConfig, score_corpus  # noqa: E402

GOLD_DIR = ROOT / "data/generated_medical_records/restyled/annotations_gold"
TYPES = ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"]
NO_ASSERT = {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}
CODEABLE = {"CHẨN_ĐOÁN", "THUỐC"}
FLAGS = ["isNegated", "isHistorical", "isFamily"]


def load_gold() -> list[tuple[str, list[dict]]]:
    out = []
    for p in sorted(glob.glob(str(GOLD_DIR / "*.json"))):
        with open(p, encoding="utf-8") as fh:
            out.append((os.path.basename(p), json.load(fh)))
    return out


def clone(docs):
    return [(k, json.loads(json.dumps(ents))) for k, ents in docs]


# ───────────────────────── noise injectors ─────────────────────────
# Each takes (docs, rng) and returns a mutated *copy*. `rng is None` marks a
# deterministic mode.


def drop_entities(frac):
    def f(docs, rng):
        out = []
        for k, ents in docs:
            out.append((k, [e for e in ents if rng.random() >= frac]))
        return out

    return f


def spurious_spans(frac):
    def f(docs, rng):
        out = []
        for k, ents in docs:
            new = list(ents)
            for _ in range(round(len(ents) * frac)):
                if not ents:
                    break
                src = ents[rng.randrange(len(ents))]
                s, e = src["position"]
                shift = rng.choice([-40, -25, 25, 40, 60])
                new.append(
                    {
                        "text": src["text"],
                        "type": TYPES[rng.randrange(5)],
                        "position": [max(0, s + shift), max(1, e + shift)],
                        "assertions": [],
                        "candidates": [],
                    }
                )
            out.append((k, new))
        return out

    return f


def wrong_codes(frac):
    pool = None

    def f(docs, rng):
        nonlocal pool
        if pool is None:
            pool = sorted(
                {c for _, ents in docs for e in ents for c in e.get("candidates", [])}
            )
        out = clone(docs)
        for _, ents in out:
            for e in ents:
                if e.get("candidates") and rng.random() < frac:
                    e["candidates"] = [pool[rng.randrange(len(pool))]]
        return out

    return f


def wrong_types(frac):
    def f(docs, rng):
        out = clone(docs)
        for _, ents in out:
            for e in ents:
                if rng.random() < frac:
                    others = [t for t in TYPES if t != e["type"]]
                    e["type"] = others[rng.randrange(len(others))]
        return out

    return f


def _det(fn):
    """Wrap a deterministic mutation so it has the (docs, rng) signature."""

    def f(docs, rng=None):
        return fn(clone(docs))

    return f


def _empty_candidates(docs):
    for _, ents in docs:
        for e in ents:
            e["candidates"] = []
    return docs


def _empty_assertions(docs):
    for _, ents in docs:
        for e in ents:
            e["assertions"] = []
    return docs


def _drop_flag(flag):
    def g(docs):
        for _, ents in docs:
            for e in ents:
                e["assertions"] = [a for a in e.get("assertions", []) if a != flag]
        return docs

    return g


def _leak_assertions_to_labs(docs):
    """The 165-violation failure mode: lab types carrying isNegated."""
    for _, ents in docs:
        for e in ents:
            if e["type"] in NO_ASSERT:
                e["assertions"] = ["isNegated"]
    return docs


def _trim_last_word(docs):
    for _, ents in docs:
        for e in ents:
            txt = e["text"]
            cut = txt.rstrip().rfind(" ")
            if cut > 0:
                e["text"] = txt[:cut]
                e["position"] = [e["position"][0], e["position"][0] + cut]
    return docs


def _shift_one_char(docs):
    for _, ents in docs:
        for e in ents:
            s, en = e["position"]
            e["position"] = [s + 1, en + 1]
    return docs


def _extend_right_one(docs):
    for _, ents in docs:
        for e in ents:
            s, en = e["position"]
            e["position"] = [s, en + 1]
    return docs


def _junk_codes(n):
    def g(docs):
        for _, ents in docs:
            for e in ents:
                if e["type"] in CODEABLE:
                    e["candidates"] = list(e.get("candidates", [])) + [
                        f"ZZ{i}" for i in range(n)
                    ]
        return docs

    return g


MODES: list[tuple[str, object, bool]] = [
    ("perfect (trần)", _det(lambda d: d), False),
    ("bỏ 5% entity", drop_entities(0.05), True),
    ("bỏ 10% entity", drop_entities(0.10), True),
    ("bỏ 20% entity", drop_entities(0.20), True),
    ("bỏ 30% entity", drop_entities(0.30), True),
    ("bỏ 50% entity", drop_entities(0.50), True),
    ("bỏ 60% entity", drop_entities(0.60), True),
    ("bỏ 65% entity", drop_entities(0.65), True),
    ("bỏ 70% entity", drop_entities(0.70), True),
    ("thêm 5% span rác", spurious_spans(0.05), True),
    ("thêm 10% span rác", spurious_spans(0.10), True),
    ("thêm 20% span rác", spurious_spans(0.20), True),
    ("thêm 30% span rác", spurious_spans(0.30), True),
    ("sai 10% mã", wrong_codes(0.10), True),
    ("sai 20% mã", wrong_codes(0.20), True),
    ("sai 30% mã", wrong_codes(0.30), True),
    ("sai 50% mã", wrong_codes(0.50), True),
    ("sai type 2%", wrong_types(0.02), True),
    ("sai type 5%", wrong_types(0.05), True),
    ("sai type 10%", wrong_types(0.10), True),
    ("sai type 20%", wrong_types(0.20), True),
    ("candidates rỗng hết", _det(_empty_candidates), False),
    ("assertions rỗng hết", _det(_empty_assertions), False),
    ("bỏ cờ isNegated", _det(_drop_flag("isNegated")), False),
    ("bỏ cờ isHistorical", _det(_drop_flag("isHistorical")), False),
    ("bỏ cờ isFamily", _det(_drop_flag("isFamily")), False),
    ("rò isNegated sang 2 loại XN", _det(_leak_assertions_to_labs), False),
    ("cắt 1 từ cuối mọi span", _det(_trim_last_word), False),
    ("lệch span 1 ký tự", _det(_shift_one_char), False),
    ("nới span phải 1 ký tự", _det(_extend_right_one), False),
    ("thêm 1 mã rác/entity", _det(_junk_codes(1)), False),
    ("thêm 4 mã rác/entity", _det(_junk_codes(4)), False),
    ("thêm 9 mã rác/entity", _det(_junk_codes(9)), False),
]

ALIGNMENTS = ["greedy_iou", "overlap_type", "exact"]


def leaderboard(gold, pred, alignment, aggregation="penalised", cand="official"):
    cfg = MetricConfig(
        alignment=alignment, aggregation=aggregation, cand_formula=cand
    )
    docs = [(k, g, p) for (k, g), (_, p) in zip(gold, pred)]
    return score_corpus(docs, cfg)["leaderboard"]


def _probe_a(docs):
    """Probe A: span + type only, every other field emptied."""
    out = clone(docs)
    for _, ents in out:
        for e in ents:
            e["assertions"] = []
            e["candidates"] = []
    return out


def extras(gold, seeds: int) -> dict:
    """The two claims the plan hangs its operational decisions on."""
    res = {}

    # (1) Probe A is linear in span recall — the only bridge from leaderboard to
    #     real recall on the hidden test set.
    pts = []
    for r in (1.00, 0.85, 0.70, 0.55, 0.40, 0.25):
        vals = []
        for s in range(seeds):
            rng = random.Random(1000 + s)
            kept = drop_entities(1 - r)(gold, rng)
            vals.append(leaderboard(gold, _probe_a(kept), "greedy_iou"))
        score = statistics.fmean(vals)
        pts.append((r, round(score, 2), round(score / r, 2)))
    coeffs = [c for _, _, c in pts]
    res["probe_a"] = {
        "points": pts,  # (recall, score, score/recall)
        "coefficient": round(statistics.fmean(coeffs), 2),
        "sd": round(statistics.stdev(coeffs), 2),
    }

    # (2) "Recall at any cost" is wrong: adding junk on top of a gap is worse
    #     than the gap alone.
    combo = {}
    for d, sp in ((0.30, 0.00), (0.30, 0.20), (0.30, 0.30), (0.40, 0.00)):
        vals = []
        for s in range(seeds):
            rng = random.Random(2000 + s)
            cur = drop_entities(d)(gold, rng)
            if sp:
                cur = spurious_spans(sp)(cur, rng)
            vals.append(leaderboard(gold, cur, "greedy_iou"))
        combo[f"drop{int(d * 100)}+spur{int(sp * 100)}"] = round(
            statistics.fmean(vals), 2
        )
    res["recall_at_any_cost"] = combo
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--alignment", default=None, help="only this alignment mode")
    ap.add_argument("--extras", action="store_true", help="probe-A calibration + combined modes")
    args = ap.parse_args(argv)

    gold = load_gold()
    n_ent = sum(len(e) for _, e in gold)
    aligns = [args.alignment] if args.alignment else ALIGNMENTS

    ceiling = leaderboard(gold, gold, "greedy_iou")
    print(
        f"gold: {len(gold)} tài liệu · {n_ent} entity "
        f"({n_ent / len(gold):.1f}/file) · trần = {ceiling:.2f}"
    )
    print(f"cấu hình: penalised / official · seeds={args.seeds}\n")

    head = f"{'chế độ hỏng':<30}" + "".join(f"{a:>16}" for a in aligns) + "   mất"
    print(head)
    print("─" * len(head))

    rows = {}
    for name, fn, is_random in MODES:
        cells, sds = [], []
        for al in aligns:
            if is_random:
                vals = [
                    leaderboard(gold, fn(gold, random.Random(s)), al)
                    for s in range(args.seeds)
                ]
                cells.append(statistics.fmean(vals))
                sds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
            else:
                cells.append(leaderboard(gold, fn(gold), al))
                sds.append(0.0)
        loss = ceiling - cells[0]
        rows[name] = {
            "random": is_random,
            "scores": {a: round(c, 2) for a, c in zip(aligns, cells)},
            "sd": {a: round(s, 2) for a, s in zip(aligns, sds)},
            "loss_vs_ceiling": round(loss, 2),
        }
        cellstr = "".join(
            f"{c:>11.2f}{('±' + format(s, '.2f')):>5}" if s else f"{c:>16.2f}"
            for c, s in zip(cells, sds)
        )
        print(f"{name:<30}{cellstr}   {loss:>6.2f}")

    ex = {}
    if args.extras:
        ex = extras(gold, args.seeds)
        print("\nPROBE A — span+type, mọi trường khác rỗng")
        print(f"{'recall':>8}{'điểm':>10}{'điểm/recall':>14}")
        for r, sc, c in ex["probe_a"]["points"]:
            print(f"{r:>8.2f}{sc:>10.2f}{c:>14.2f}")
        print(
            f"  ⇒ recall ≈ điểm / {ex['probe_a']['coefficient']:.2f} "
            f"(sd {ex['probe_a']['sd']:.2f})"
        )
        print("\nKIỂM 'recall bằng mọi giá'")
        for k, v in ex["recall_at_any_cost"].items():
            print(f"  {k:<18}{v:>8.2f}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "gold_docs": len(gold),
                    "gold_entities": n_ent,
                    "entities_per_file": round(n_ent / len(gold), 2),
                    "ceiling": round(ceiling, 2),
                    "config": "penalised/official",
                    "seeds": args.seeds,
                    "modes": rows,
                    **({"extras": ex} if ex else {}),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n→ {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
