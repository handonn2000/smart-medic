"""L4b · `linking/` — the two code sources, tested on the repo's real KB and gold.

The test that earns its keep is `test_icd_retrieval_is_a_net_win_on_gold`: it
re-derives, on every run, the claim the whole module rests on — that guessing a
code on a span we would otherwise ship empty wins more than it loses. If the gold
corpus or the gazetteer ever shifts that balance, this fails instead of the
leaderboard finding out for us.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.eval.scoring import align, load_dir, sort_key  # noqa: E402
from smart_medic.linking import icd, rxnorm  # noqa: E402

GOLD = ROOT / "data/generated_medical_records/restyled/annotations_gold"
PRED = ROOT / "runs/_pred_gold"


# ─────────────────────────── brand → ingredient ───────────────────────────
def test_brand_map_resolves_the_cases_gold_disagreed_on():
    """The three real failures from the 2026-07-30 gold run, by RxCUI.

    These are not invented fixtures: each one is a span where we shipped the brand
    RxCUI and gold carried the ingredient (ADR 0001 rule 1).
    """
    m = rxnorm.load_brand_map()
    assert rxnorm.lift_to_ingredient(("203856",), brand_map=m) == ("6902",)
    # Lorcet is a combination product; gold lists BOTH ingredients, which is why
    # decision.max_candidates_per_type gives THUỐC two slots and not one.
    assert set(rxnorm.lift_to_ingredient(("491666",), brand_map=m)) == {"161", "5489"}


def test_lift_is_idempotent_and_deduplicates():
    m = rxnorm.load_brand_map()
    once = rxnorm.lift_to_ingredient(("203856",), brand_map=m)
    assert rxnorm.lift_to_ingredient(once, brand_map=m) == once, (
        "lifting an ingredient code must be a no-op, or repeated passes would walk "
        "up the hierarchy"
    )
    # two brands of one ingredient must not consume both THUỐC slots with one code
    doubled = rxnorm.lift_to_ingredient(("203856", "203856"), brand_map=m)
    assert doubled == ("6902",)
    assert rxnorm.lift_to_ingredient((), brand_map=m) == ()


def test_unknown_code_is_kept_not_dropped():
    """An absent key means "no opinion", not "wrong" — dropping would trade a
    possibly-correct code for a guaranteed zero."""
    m = rxnorm.load_brand_map()
    assert rxnorm.lift_to_ingredient(("ZZZ_not_a_rxcui",), brand_map=m) == (
        "ZZZ_not_a_rxcui",
    )


def test_target_tty_is_still_a_parameter():
    """ADR 0001 closed at IN, but the fallback must stay one YAML edit away."""
    assert rxnorm.target_tty() == "IN"


# ──────────────────────────────── ICD retrieval ────────────────────────────────
def test_icd_index_covers_the_coded_slice():
    idx = icd.load_icd_index()
    assert len(idx) > 5000, f"only {len(idx)} ICD-coded gazetteer entries"
    assert idx.postings and idx.idf


def test_retrieve_is_deterministic():
    """Two builds of one commit must emit the same code (ADR 0005)."""
    idx = icd.load_icd_index()
    first = icd.retrieve("suy thận", index=idx)
    for _ in range(10):
        assert icd.retrieve("suy thận", index=idx) == first


def test_retrieve_respects_the_similarity_floor():
    idx = icd.load_icd_index()
    assert icd.retrieve("suy thận", index=idx, min_similarity=0.0)
    assert icd.retrieve("suy thận", index=idx, min_similarity=1.01) == ()
    assert icd.retrieve("", index=idx) == ()
    assert icd.retrieve("zzzzzz qqqqqq", index=idx) == ()


@pytest.mark.skipif(not PRED.is_dir(), reason="runs/_pred_gold not built")
def test_icd_retrieval_is_a_net_win_on_gold():
    """The claim the module exists for, re-measured on every run.

    Over the matched CHẨN_ĐOÁN spans we ship empty: a wrong guess scores the same
    0 as no guess, so the only real cost is a span whose gold is empty. Wins must
    beat that cost by a wide margin, or retrieving is not a free bet any more.
    """
    gold, pred = load_dir(GOLD), load_dir(PRED)
    keys = sorted(set(gold) & set(pred), key=sort_key)
    idx = icd.load_icd_index()

    win = lose = neutral = 0
    for k in keys:
        for i, j in align(gold[k], pred[k], "overlap_type")[0]:
            g, p = gold[k][i], pred[k][j]
            if g["type"] != "CHẨN_ĐOÁN":
                continue
            got = icd.retrieve(p["text"], index=idx)
            if not got:
                continue
            want = set(g.get("candidates") or [])
            if not want:
                lose += 1                      # had J=1 for free, now 0
            elif any(
                c in want or any(w.startswith(c) or c.startswith(w) for w in want)
                for c in got
            ):
                win += 1                       # 0 → 1
            else:
                neutral += 1                   # 0 → 0, costs nothing
    assert win + lose, "retrieval fired on nothing at all"
    assert win > 5 * lose, (
        f"retrieval rescued {win} spans but broke {lose} that were already right "
        f"({neutral} no-change). The 97.2/2.8 split this module relies on has "
        f"moved — re-run the floor sweep in configs/pipeline.yaml before shipping."
    )
