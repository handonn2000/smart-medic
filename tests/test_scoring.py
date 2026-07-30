"""Scorer self-tests.

The important ones are `test_matched_aggregation_is_degenerate_*`: they prove,
on real data, that the most literal reading of the official formula rewards
deleting your own predictions. That is why `penalised` is the primary number.
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.eval.scoring import (  # noqa: E402
    MetricConfig,
    align,
    jaccard,
    load_dir,
    score_corpus,
    wer,
)

OUTPUT = ROOT / "data" / "output"


# ───────────────────────────── primitives ─────────────────────────────
def test_wer_basics():
    assert wer("a b c", "a b c") == 0.0
    assert wer("a b c", "a b") == pytest.approx(1 / 3)
    assert wer("amlodipine 10 mg po daily", "amlodipine") == pytest.approx(0.8)
    # unbounded above: over-generation on a short gold is punished brutally
    assert wer("sốt", "bệnh nhân có sốt cao") == pytest.approx(4.0)


def test_jaccard_conventions():
    assert jaccard([], []) == 1.0            # both empty → 1
    assert jaccard([], ["x"]) == 0.0         # gold empty, pred not → 0
    assert jaccard(["x"], []) == 0.0
    assert jaccard(["a", "b"], ["a"]) == pytest.approx(0.5)


def test_alignment_is_deterministic():
    gold = [{"position": [0, 5], "type": "THUỐC", "text": "a"},
            {"position": [6, 9], "type": "THUỐC", "text": "b"}]
    pred = [{"position": [6, 9], "type": "THUỐC", "text": "b"},
            {"position": [0, 5], "type": "THUỐC", "text": "a"}]
    first = align(gold, pred, "greedy_iou")
    for _ in range(20):
        assert align(gold, pred, "greedy_iou") == first
    pairs, miss, spur = first
    assert sorted(pairs) == [(0, 1), (1, 0)] and not miss and not spur


# ─────────────────────── behaviour on real predictions ───────────────────
def _load_real():
    if not OUTPUT.is_dir():
        pytest.skip("data/output/ not present")
    docs = []
    for p in sorted(OUTPUT.glob("*.json")):
        if not p.stem.isdigit():
            continue
        ents = json.loads(p.read_text(encoding="utf-8"))
        if ents:
            docs.append((p.stem, ents, copy.deepcopy(ents)))
    if not docs:
        pytest.skip("no non-empty predictions")
    return docs


def test_identity_is_perfect_on_text_and_assertions():
    docs = _load_real()
    r = score_corpus(docs, MetricConfig(aggregation="penalised"))
    assert r["text_score"] == pytest.approx(1.0)
    assert r["assertions_score"] == pytest.approx(1.0)
    assert r["missing"] == 0 and r["spurious"] == 0


def test_plus_one_is_a_weight_and_caps_nothing():
    """A perfect prediction reaches 1.0 on candidates. The `+1` weights, not caps.

    This test replaces `test_official_plus_one_caps_candidates_below_one`, which
    asserted the opposite and was wrong. The published spec puts the `+1` only in
    the per-document weight `W_i = Σ_k(len(gt(k))+1)`:

        candidates_score = Σ_i J_cand(i)·W_i / Σ_i W_i

    It never enters `J`, so it cannot bound the term. Under the old reading a
    submission carrying no codes scored exactly 0.00 on candidates — an
    intersection with the empty set — while the organisers scored the same
    submission 11.03. See ADR 0002, "Đặc tả CHÍNH THỨC".

    Run on the gold corpus, not `data/output`: today's predictions carry no codes
    at all, so they cannot tell a weighted average from an unweighted one.
    """
    gold = load_dir(ROOT / "data/generated_medical_records/restyled/annotations_gold")
    if not gold:
        pytest.skip("gold corpus not present")
    docs = [(k, v, v) for k, v in sorted(gold.items())]

    for cand in ("official", "plain"):
        r = score_corpus(docs, MetricConfig(cand_formula=cand))
        assert r["candidates_score"] == pytest.approx(1.0), (
            f"cand_formula={cand}: a perfect prediction must score 1.0, got "
            f"{r['candidates_score']:.4f}"
        )
        assert r["leaderboard"] == pytest.approx(100.0, abs=1e-6)

    # And the weighting is live: strip every code and the two formulas diverge,
    # because documents rich in gold codes now carry more of the average.
    stripped = [
        (k, v, [{**e, "candidates": []} for e in v]) for k, v in sorted(gold.items())
    ]
    w = score_corpus(stripped, MetricConfig(cand_formula="official"))
    u = score_corpus(stripped, MetricConfig(cand_formula="plain"))
    assert w["candidates_score"] != pytest.approx(u["candidates_score"], abs=1e-6), (
        "weighted and unweighted candidates came out identical — W_i is not "
        "reaching the corpus average"
    )
    assert 0.0 < w["candidates_score"] < 1.0


def test_empty_prediction_still_scores_candidates():
    """The regression that cost 16.53 points of measurement error.

    Predicting no codes at all must NOT score 0: every concept whose gold also
    has no codes is a correct empty, worth 1 by the spec's own convention.
    """
    gold = load_dir(ROOT / "data/generated_medical_records/restyled/annotations_gold")
    if not gold:
        pytest.skip("gold corpus not present")
    docs = [
        (k, v, [{**e, "candidates": []} for e in v]) for k, v in sorted(gold.items())
    ]
    r = score_corpus(docs, MetricConfig())
    assert r["candidates_score"] > 0.5, (
        f"candidates collapsed to {r['candidates_score']:.4f} on a prediction that "
        f"is perfect apart from carrying no codes — the `+1` is being used as a "
        f"denominator again"
    )


def test_type_error_is_punished_twice():
    """Spec closing note: right text, wrong type ⇒ counted twice, 0 each time.

    This is why `overlap_type` is the default alignment and `greedy_iou` is only
    a diagnostic — `greedy_iou` never compares `type`, so it reports 0.00 cost.
    """
    gold = load_dir(ROOT / "data/generated_medical_records/restyled/annotations_gold")
    if not gold:
        pytest.skip("gold corpus not present")
    keys = sorted(gold)
    rng = random.Random(3)
    types = ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"]
    wrong = []
    for k in keys:
        out = []
        for e in gold[k]:
            e = dict(e)
            if rng.random() < 0.10:
                others = [t for t in types if t != e["type"]]
                e["type"] = others[rng.randrange(len(others))]
            out.append(e)
        wrong.append((k, gold[k], out))

    official = score_corpus(wrong, MetricConfig())
    blind = score_corpus(wrong, MetricConfig(alignment="greedy_iou"))
    assert official["leaderboard"] < 90.0, (
        f"10% type errors cost only {100 - official['leaderboard']:.2f} points "
        f"under the official alignment — type is not being compared"
    )
    assert blind["leaderboard"] == pytest.approx(100.0, abs=1e-6), (
        "greedy_iou is supposed to be blind to type; it moved"
    )
    assert official["missing"] == official["spurious"] > 0, (
        "a type error must produce one unmatched gold AND one unmatched "
        "prediction — the 'counted twice' rule"
    )


def test_matched_aggregation_is_degenerate_under_deletion():
    """Dropping 30% of your own predictions must NOT raise the score."""
    docs = _load_real()
    rng = random.Random(0)
    dropped = [
        (k, g, [e for e in p if rng.random() > 0.30]) for k, g, p in docs
    ]
    matched = score_corpus(dropped, MetricConfig(aggregation="matched"))
    penalised = score_corpus(dropped, MetricConfig(aggregation="penalised"))

    assert matched["text_score"] == pytest.approx(1.0, abs=1e-9), (
        "under 'matched' aggregation, deleting predictions leaves text at a "
        "perfect 1.0 — this is the documented degeneracy"
    )
    assert penalised["text_score"] < 0.85, (
        "'penalised' must actually punish the deletion; got "
        f"{penalised['text_score']:.4f}"
    )
    assert penalised["final_score"] < matched["final_score"]


def test_penalised_punishes_spurious_entities():
    docs = _load_real()
    inflated = []
    for k, g, p in docs:
        extra = [
            {"text": "zzz", "type": "TRIỆU_CHỨNG", "position": [10_000, 10_003],
             "assertions": [], "candidates": []}
        ]
        inflated.append((k, g, p + extra))
    base = score_corpus(docs, MetricConfig(aggregation="penalised"))
    worse = score_corpus(inflated, MetricConfig(aggregation="penalised"))
    assert worse["final_score"] < base["final_score"]
    assert worse["spurious"] == len(docs)


def test_boundary_drift_costs_text_score():
    """A uniform +1-word right extension should visibly cost text_score."""
    docs = _load_real()
    drifted = []
    for k, g, p in docs:
        q = copy.deepcopy(p)
        for e in q:
            e["text"] = e["text"] + " xxx"
        drifted.append((k, g, q))
    r = score_corpus(drifted, MetricConfig(aggregation="penalised"))
    assert r["text_score"] < 0.85, (
        f"one extra word per span should hurt; got {r['text_score']:.4f}"
    )
