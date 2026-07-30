"""L5 · the emit gate — the one place a threshold may be applied.

The tests that earn their keep here are the ones that fail when someone
reintroduces a magic number, or when P1's single-row constant quietly grows into
the P6 schedule without P6's measurements behind it.
"""
from __future__ import annotations

import ast

import pytest

from smart_medic.decision import emit
from smart_medic.extract import recall_floor
from smart_medic.extract.spans import Span
from smart_medic.io.config import ConfigError, load_pipeline, repo_root, require
from smart_medic.io.corpus import load_test
from smart_medic.io.labels import CODEABLE_TYPES, LAB_TYPES


def _span(score: float, etype: str = "CHẨN_ĐOÁN", start: int = 0, end: int = 4) -> Span:
    return Span(
        start=start, end=end, type_dist={etype: 1.0}, score=score, source="aho"
    )


def test_no_threshold_literal_in_decision_source():
    """No float literal may appear in executable code under `decision/`.

    A threshold baked into Python is a threshold nobody can review. The numbers
    live in `configs/pipeline.yaml`, whose sha256 goes into every run manifest.

    `decision/README.md` states this check as `grep -rn "0\\.[0-9]"`, but a plain
    grep also hits docstrings — and this module's docstring is *made of* measured
    numbers, which is the reviewable form the rule is asking for. So the check
    walks the AST and looks at real `float` constants only.
    """
    offenders = []
    for path in sorted((repo_root() / "src" / "smart_medic" / "decision").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, float)
                and id(node) not in docstrings
            ):
                offenders.append(f"{path.name}:{node.lineno}: {node.value}")
    assert not offenders, (
        "float literal(s) in executable code under decision/ — thresholds belong "
        "in configs/pipeline.yaml:\n  " + "\n  ".join(offenders)
    )


def test_threshold_is_one_swept_constant_not_a_density_schedule():
    """The gate must not move with the run's own density.

    It used to: a three-tier table keyed by `density / gold_density_per_file`.
    W5 removed it because the sweep contradicted its premise. Swept end to end on
    20 hand-annotated test documents, p = 0.10/0.20/0.25 all score 44.10, and
    0.30 drops to 38.55 — no crossover anywhere in the measured range, so "dense
    run ⇒ tighten" is false here. Recall is still 0.622 at 29 entities/file.

    Restoring a schedule needs a sweep that actually shows a crossover. This test
    is what fails if one is reintroduced without one.
    """
    configured = float(require(load_pipeline(), "decision.emit_threshold"))
    seen = {emit.select_threshold(d).p for d in (1.0, 15.8, 29.1, 45.9, 90.0)}
    assert seen == {configured}, (
        f"threshold varied with density: {sorted(seen)} — the gate is a measured "
        f"constant, and a run-dependent gate makes every earlier score "
        f"incomparable"
    )


def test_density_outside_the_swept_range_is_flagged_not_hidden():
    """`p` still applies, but the run says nothing was measured out there.

    The threshold was swept at ratios 0.5–1.2 (the shipped run sits at 0.80). A
    density far outside that usually means a lane changed rather than the corpus,
    which is a finding, not something to swallow.
    """
    gold = float(require(load_pipeline(), "decision.gold_density_per_file"))
    inside = emit.select_threshold(gold * 0.8)
    assert inside.regime_matches and inside.warning() == ""

    outside = emit.select_threshold(gold * 3.0)
    assert not outside.regime_matches
    assert "OUTSIDE THE SWEPT RANGE" in outside.warning()
    assert f"{outside.density_ratio:.3f}" in outside.warning()
    assert outside.p == inside.p, "the flag reports; it must not change the gate"


def test_gate_drops_below_and_keeps_at_threshold():
    doc = load_test()[0]
    choice = emit.select_threshold(10.0)
    p = choice.p
    spans = [
        _span(p - 0.01, start=0, end=4),
        _span(p, start=10, end=14),
        _span(p + 0.5, start=20, end=24),
    ]
    out = emit.finalize(doc, spans, choice)
    assert len(out) == 2, "the gate is not inclusive at exactly p, or leaked one below"


def test_emitted_records_are_schema_legal():
    """No assertions yet (P4); candidates now flow through, under a measured cap.

    Empty `assertions` is REQUIRED for the two lab types — 11.59 points. Elsewhere
    it scores the same 0 a wrong flag would, so guessing buys nothing before P4.

    `candidates` used to be asserted empty here. That assertion encoded a reading
    of the metric that has since been disproven: the `+1` in the official
    denominator is a per-document WEIGHT, not a cap, and discarding the gazetteer
    codes was costing 5.11 points (ADR 0002, "Đặc tả CHÍNH THỨC"). What the test
    pins now is the contract that replaced it — cardinality per type comes from
    `configs/pipeline.yaml`, never from this module.
    """
    caps = require(load_pipeline(), "decision.max_candidates_per_type")
    doc = load_test()[0]
    choice = emit.select_threshold(10.0)
    spans = recall_floor(doc)
    records = emit.finalize(doc, spans, choice)
    assert records, "no records emitted for the first test document"
    coded = 0
    for r in records:
        assert doc.raw[r["position"][0] : r["position"][1]] == r["text"]
        # `assertions` stopped being unconditionally empty when assertion/ landed
        # (W2). What is still absolute is the schema constraint below: the two lab
        # types must never carry one. Everything else is checked in
        # tests/test_assertion.py, including the rate band.
        assert set(r["assertions"]) <= {"isNegated", "isFamily", "isHistorical"}
        if r["type"] in LAB_TYPES:
            assert not r["assertions"]
        if r["type"] not in CODEABLE_TYPES:
            assert not r["candidates"], (
                f"{r['type']} is not codeable but carries {r['candidates']} — the "
                f"cap table and the schema constraint have diverged"
            )
        assert len(r["candidates"]) <= int(caps.get(r["type"], 0))
        assert len(set(r["candidates"])) == len(r["candidates"]), "duplicate code"
        coded += bool(r["candidates"])
    assert coded, (
        "not one record carried a code, on a document where the gazetteer has "
        "hits — decision/emit.py is discarding Span.codes again"
    )


def test_code_pick_is_deterministic_and_shortest_first():
    """Two builds of one commit must emit the same codes (ADR 0005).

    `shortest_first` prefers the 3-character ICD block (I48.0 → I48), which the
    task permits and which measured +0.033 against a plain ascending sort.
    """
    caps = {"CHẨN_ĐOÁN": 1, "THUỐC": 2}
    codes = ("I48.0", "I48", "I48.1")
    first = emit._pick_codes(codes, "CHẨN_ĐOÁN", caps, "shortest_first")
    assert first == ("I48",)
    for _ in range(10):
        assert emit._pick_codes(codes, "CHẨN_ĐOÁN", caps, "shortest_first") == first
    assert emit._pick_codes(codes, "THUỐC", caps, "shortest_first") == ("I48", "I48.0")
    assert emit._pick_codes(codes, "TRIỆU_CHỨNG", caps, "shortest_first") == ()
    assert emit._pick_codes((), "CHẨN_ĐOÁN", caps, "shortest_first") == ()
    with pytest.raises(ConfigError):
        emit._pick_codes(codes, "CHẨN_ĐOÁN", caps, "whatever")


def test_type_is_argmax_never_hedged():
    """Emitting two types for one span costs 1.29 under BOTH alignments."""
    doc = load_test()[0]
    choice = emit.select_threshold(10.0)
    span = Span(
        start=0,
        end=4,
        type_dist={"CHẨN_ĐOÁN": 0.51, "TRIỆU_CHỨNG": 0.49},
        score=0.9,
        source="aho",
    )
    out = emit.finalize(doc, [span], choice)
    assert len(out) == 1
    assert out[0]["type"] == "CHẨN_ĐOÁN"


def test_records_are_position_sorted_and_unique():
    doc = load_test()[0]
    choice = emit.select_threshold(10.0)
    records = emit.finalize(doc, recall_floor(doc), choice)
    keys = [tuple(r["position"]) for r in records]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))


def test_threshold_config_is_a_scalar_in_range():
    """`decision.emit_threshold` is one number since W5, not a list of rows.

    The density-keyed table (and the range-spec parser that read it) was removed
    when the sweep showed no crossover — see
    test_threshold_is_one_swept_constant_not_a_density_schedule.
    """
    p = require(load_pipeline(), "decision.emit_threshold")
    assert isinstance(p, (int, float)) and not isinstance(p, bool), (
        f"emit_threshold is {type(p).__name__}; a density-keyed schedule was "
        f"removed in W5 and needs a sweep showing a crossover to come back"
    )
    assert 0.0 <= float(p) <= 1.0


def test_swept_range_is_configured_and_ordered():
    lo, hi = (float(x) for x in require(load_pipeline(), "decision.swept_density_ratio"))
    assert 0.0 < lo < hi


def test_a_bad_threshold_is_rejected_rather_than_clamped(monkeypatch):
    from smart_medic.io.config import ConfigError

    monkeypatch.setattr(emit, "_decision_cfg", lambda: {
        "gold_density_per_file": 36.2,
        "emit_threshold": 1.7,
        "swept_density_ratio": [0.5, 1.2],
    })
    with pytest.raises(ConfigError):
        emit.select_threshold(29.0)
