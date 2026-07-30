"""`overlap_type` is the blocking column. This file makes that a build error.

`greedy_iou` — the primary internal number — does not compare `type` anywhere.
So the official number can **never** reward fixing a type, and a change that
trades type accuracy for span recall shows up as an improvement. Under
`overlap_type` that same trade costs 12.35 points at a 10% type-error rate.

The rule (plan-v4 tab 05 §B): a change is accepted only if it does not drop
`overlap_type` by more than 0.010. `check_parity` is that rule; the tests below
prove it accepts a real improvement and **blocks a change known in advance to be
bad**, because a guard nobody has watched fail is a guard nobody knows works.

Everything here runs on the repo's real corpus. No invented fixtures.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.eval.bootstrap import corpus_score, doc_terms  # noqa: E402
from smart_medic.eval.probe import variant_a, variant_a_prime  # noqa: E402
from smart_medic.eval.scoring import (  # noqa: E402
    TYPES,
    MetricConfig,
    load_dir,
    score_corpus,
    sort_key,
)

GOLD_DIR = ROOT / "data/generated_medical_records/restyled/annotations_gold"
PRED_GOLD = ROOT / "runs/_pred_gold"

#: A change may cost at most this much on the blocking column. ADR 0002.
BLOCKING_FLOOR = 0.010


# ─────────────────────────────── the gate ───────────────────────────────
def leaderboard(docs, alignment: str) -> float:
    return score_corpus(docs, MetricConfig(alignment=alignment))["leaderboard"]


def check_parity(
    gold: dict[str, list],
    before: dict[str, list],
    after: dict[str, list],
    *,
    floor: float = BLOCKING_FLOOR,
) -> str | None:
    """None when the change may be accepted, else why it must not be.

    Wider than "greedy up while overlap_type down": the blocking-column rule
    rejects *any* change that costs more than `floor` on `overlap_type`. The
    greedy-up case gets its own wording because it is the one that looks like
    progress on the dashboard.
    """
    keys = sorted(set(gold) & set(before) & set(after), key=sort_key)
    if not keys:
        raise ValueError("no documents common to gold, before and after")

    d_before = [(k, gold[k], before[k]) for k in keys]
    d_after = [(k, gold[k], after[k]) for k in keys]

    g_delta = leaderboard(d_after, "greedy_iou") - leaderboard(d_before, "greedy_iou")
    o_delta = leaderboard(d_after, "overlap_type") - leaderboard(d_before, "overlap_type")
    e_after = leaderboard(d_after, "exact")

    if o_delta < -floor:
        if g_delta >= 0:
            return (
                f"ĐÁNH ĐỔI TYPE LẤY SPAN: greedy_iou {g_delta:+.3f} nhưng "
                f"overlap_type {o_delta:+.3f} (sàn {floor:.3f}). Số chính thức "
                f"không so type, nên nó không thấy giá này — 12,35 điểm ở mức sai "
                f"type 10%."
            )
        return (
            f"overlap_type giảm {o_delta:+.3f}, quá sàn {floor:.3f} — cột chặn."
        )
    if e_after < 1.0 and g_delta > -floor:
        return (
            f"exact sụt về {e_after:.3f} trong khi greedy_iou {g_delta:+.3f}: "
            f"đèn báo BUG OFFSET, không phải khoảng trống mô hình."
        )
    return None


# ───────────────────────────── corpus fixtures ─────────────────────────────
@pytest.fixture(scope="module")
def gold() -> dict[str, list]:
    if not GOLD_DIR.is_dir():
        pytest.skip(f"{GOLD_DIR} missing")
    return load_dir(GOLD_DIR)


def _clone(records: dict[str, list]) -> dict[str, list]:
    return json.loads(json.dumps(records))


def drop(records: dict[str, list], frac: float, seed: int) -> dict[str, list]:
    rng = random.Random(seed)
    return {k: [e for e in v if rng.random() >= frac] for k, v in records.items()}


def restore_with_wrong_types(
    gold: dict[str, list], kept: dict[str, list]
) -> dict[str, list]:
    """Put every dropped entity back — correct span, deliberately wrong type.

    This is the failure mode the guard exists for, built on purpose: span recall
    goes up, and every recovered entity is unusable to anyone who compares type.
    """
    out = _clone(kept)
    for key, entities in gold.items():
        present = {tuple(e["position"]) for e in out.get(key, [])}
        for e in entities:
            if tuple(e["position"]) in present:
                continue
            bad = dict(json.loads(json.dumps(e)))
            i = TYPES.index(bad["type"]) if bad["type"] in TYPES else 0
            bad["type"] = TYPES[(i + 2) % len(TYPES)]
            out.setdefault(key, []).append(bad)
    return out


def wrong_types(records: dict[str, list], frac: float, seed: int) -> dict[str, list]:
    rng = random.Random(seed)
    out = _clone(records)
    for entities in out.values():
        for e in entities:
            if rng.random() < frac:
                others = [t for t in TYPES if t != e["type"]]
                e["type"] = others[rng.randrange(len(others))]
    return out


# ──────────────────────────── the guard's own tests ────────────────────────────
def test_parity_gate_accepts_a_real_improvement(gold):
    """Fewer missed entities, types untouched: both columns rise, gate is silent."""
    before = drop(gold, 0.20, seed=7)
    after = drop(gold, 0.10, seed=7)
    docs_b = [(k, gold[k], before[k]) for k in sorted(gold, key=sort_key)]
    docs_a = [(k, gold[k], after[k]) for k in sorted(gold, key=sort_key)]
    assert leaderboard(docs_a, "greedy_iou") > leaderboard(docs_b, "greedy_iou")
    assert leaderboard(docs_a, "overlap_type") > leaderboard(docs_b, "overlap_type")
    assert check_parity(gold, before, after) is None


def test_parity_gate_blocks_a_known_bad_change(gold):
    """The proof the guard works: a change that WINS on the official number.

    Recovering 25% more spans with the wrong type raises `greedy_iou` — which
    would be shipped by anyone reading only the primary number — while
    `overlap_type` falls. The gate must refuse it.
    """
    before = drop(gold, 0.25, seed=11)
    after = restore_with_wrong_types(gold, before)

    keys = sorted(gold, key=sort_key)
    docs_b = [(k, gold[k], before[k]) for k in keys]
    docs_a = [(k, gold[k], after[k]) for k in keys]
    g_delta = leaderboard(docs_a, "greedy_iou") - leaderboard(docs_b, "greedy_iou")
    o_delta = leaderboard(docs_a, "overlap_type") - leaderboard(docs_b, "overlap_type")

    # the change really is seductive under the official number, and really is bad
    assert g_delta > 1.0, f"fixture stopped being a span improvement: {g_delta:+.3f}"
    assert o_delta < -BLOCKING_FLOOR, f"fixture stopped being harmful: {o_delta:+.3f}"

    reason = check_parity(gold, before, after)
    assert reason is not None, "GUARD DID NOT FIRE on a change known to be bad"
    assert "ĐÁNH ĐỔI TYPE LẤY SPAN" in reason


def test_parity_gate_blocks_pure_type_corruption(gold):
    """No span moves at all — 10% of types corrupted. `greedy_iou` reports 0.00."""
    after = wrong_types(gold, 0.10, seed=3)
    keys = sorted(gold, key=sort_key)
    g_delta = (
        leaderboard([(k, gold[k], after[k]) for k in keys], "greedy_iou")
        - leaderboard([(k, gold[k], gold[k]) for k in keys], "greedy_iou")
    )
    assert abs(g_delta) < 1e-9, (
        f"greedy_iou moved by {g_delta:+.4f} on a type-only change — it is not "
        f"supposed to look at type at all"
    )
    assert check_parity(gold, gold, after) is not None


def test_probe_a_prime_is_exactly_the_type_only_change(gold):
    """A′ must differ from A in `type` and in nothing else — the whole design."""
    a = {k: variant_a(v) for k, v in gold.items()}
    ap = {k: variant_a_prime(v) for k, v in gold.items()}
    for key in gold:
        assert [e["position"] for e in a[key]] == [e["position"] for e in ap[key]]
        assert [e["text"] for e in a[key]] == [e["text"] for e in ap[key]]
        assert all(x["type"] != y["type"] for x, y in zip(a[key], ap[key]))
        assert all(not e["assertions"] and not e["candidates"] for e in ap[key])
    # and the gate must reject it, because A′ IS the worst case of the trade
    assert check_parity(gold, a, ap) is not None


# ───────────────────── real-data guards on the live run ─────────────────────
@pytest.mark.skipif(not PRED_GOLD.is_dir(), reason="runs/_pred_gold not built")
def test_exact_column_has_not_collapsed(gold):
    """`exact` near zero while the other two are normal ⇒ offset bug, not a gap."""
    pred = load_dir(PRED_GOLD)
    keys = sorted(set(gold) & set(pred), key=sort_key)
    assert keys, "no overlap between gold and runs/_pred_gold"
    docs = [(k, gold[k], pred[k]) for k in keys]
    g = leaderboard(docs, "greedy_iou")
    e = leaderboard(docs, "exact")
    assert g > 1.0, f"greedy_iou is {g:.2f} — nothing is matching at all"
    assert e > 0.25 * g, (
        f"exact={e:.2f} is under a quarter of greedy_iou={g:.2f}: spans are "
        f"systematically off by a character or two. Stop and fix offsets — a "
        f"score computed on drifted offsets is worse than no score."
    )


def test_doc_terms_reproduce_score_corpus(gold):
    """Pins the bootstrap shortcut: `corpus_score(doc_terms(...))` IS the leaderboard.

    `paired_bootstrap` resamples four precomputed per-document arrays instead of
    re-scoring. Text and assertions are plain means, but candidates is weighted
    by W_i — a ratio of sums, not a mean. An earlier version resampled it as if
    it were a mean; if this identity ever drifts again, every CI in the project
    is wrong and silently so.
    """
    keys = sorted(gold, key=sort_key)
    docs = [(k, gold[k], drop(gold, 0.15, seed=5)[k]) for k in keys]
    for alignment in ("greedy_iou", "overlap_type", "exact"):
        for cand in ("official", "plain"):
            cfg = MetricConfig(alignment=alignment, cand_formula=cand)
            assert corpus_score(doc_terms(docs, cfg)) == pytest.approx(
                score_corpus(docs, cfg)["leaderboard"], abs=1e-9
            ), f"{alignment}/{cand}: bootstrap shortcut no longer exact"


def test_candidate_weight_is_gold_only(gold):
    """W_i must not depend on the prediction, or the paired bootstrap is invalid.

    `paired_bootstrap` shares one weight array between both systems. That is
    only legitimate because W_i = Σ_k(len(gold_codes(k))+1) reads gold alone.
    """
    keys = sorted(gold, key=sort_key)
    cfg = MetricConfig()
    perfect = doc_terms([(k, gold[k], gold[k]) for k in keys], cfg)
    stripped = doc_terms(
        [(k, gold[k], [{**e, "candidates": []} for e in gold[k]]) for k in keys], cfg
    )
    assert [t[3] for t in perfect] == [t[3] for t in stripped]
    assert any(t[3] > 1.0 for t in perfect), "no document carries any gold code"
