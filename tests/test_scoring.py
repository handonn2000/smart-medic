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


def test_official_plus_one_caps_candidates_below_one():
    """A *perfect* prediction still cannot reach 1.0 on candidates."""
    docs = _load_real()
    official = score_corpus(docs, MetricConfig(cand_formula="official"))
    plain = score_corpus(docs, MetricConfig(cand_formula="plain"))
    assert plain["candidates_score"] == pytest.approx(1.0)
    assert official["candidates_score"] < 0.75, (
        "the +1 in the official denominator should cap a perfect prediction "
        f"well below 1.0; got {official['candidates_score']:.4f}"
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
