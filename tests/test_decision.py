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
from smart_medic.io.config import load_pipeline, repo_root, require
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


def test_p1_uses_the_constant_row_regardless_of_density():
    """P1 implements ONE row. Reading the table by density is P6's job.

    This is the test that fails if someone "helpfully" makes `select_threshold`
    interpolate the schedule: the three-tier table needs the P6 measurements
    behind it, and a lookup that silently changes the gate between two runs makes
    every earlier score incomparable.
    """
    table = require(load_pipeline(), "decision.emit_threshold")
    constant = next(
        float(r["p"]) for r in table if str(r["density_ratio"]) == emit.P1_BRANCH
    )
    for density in (1.0, 15.8, 33.6, 45.9, 90.0):
        choice = emit.select_threshold(density)
        assert choice.p == constant
        assert choice.branch == emit.P1_BRANCH


def test_regime_mismatch_is_reported_not_hidden():
    """When measured density leaves the P1 branch, the run must say so.

    Lane R measures ~49/file on gold and ~34/file on test, both well outside the
    `<0.50` ratio the plan assumed from the 15.8/file baseline. That contradiction
    is a finding; a gate that swallowed it would let the plan's premise rot
    silently.
    """
    low = emit.select_threshold(10.0)
    assert low.regime_matches and low.warning() == ""

    high = emit.select_threshold(49.0)
    assert not high.regime_matches
    assert "REGIME MISMATCH" in high.warning()
    assert f"{high.density_ratio:.3f}" in high.warning()


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
    """P1 emits no assertions and no candidates, and that is the right answer.

    Empty `assertions` is REQUIRED for the two lab types — 11.59 points. Elsewhere
    it scores the same 0 a wrong flag would, so guessing buys nothing before P4.
    """
    doc = load_test()[0]
    choice = emit.select_threshold(10.0)
    spans = recall_floor(doc)
    records = emit.finalize(doc, spans, choice)
    assert records, "no records emitted for the first test document"
    for r in records:
        assert doc.raw[r["position"][0] : r["position"][1]] == r["text"]
        assert r["assertions"] == []
        assert r["candidates"] == []
        if r["type"] in LAB_TYPES:
            assert not r["assertions"]
        if r["type"] not in CODEABLE_TYPES:
            assert not r["candidates"]


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


@pytest.mark.parametrize(
    "spec,ratio,expected",
    [
        ("<0.50", 0.34, True),
        ("<0.50", 0.60, False),
        ("0.50-0.80", 0.73, True),
        ("0.50-0.80", 0.34, False),
        (">0.80", 1.08, True),
        (">0.80", 0.73, False),
    ],
)
def test_density_ratio_specs_parse(spec, ratio, expected):
    assert emit._matches(spec, ratio) is expected


def test_unparseable_density_spec_raises():
    from smart_medic.io.config import ConfigError

    with pytest.raises(ConfigError):
        emit._matches("about half", 0.5)
