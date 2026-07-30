"""W4 · the `text` term — a lab value ends after its unit, not before it.

`text = m · mean(1 − WER)` is 30% of the final score, and the second factor was
being given away on a mechanical error. Measured on 20 hand-annotated test
documents, of the 158 matched pairs whose text disagreed with gold, 26 were the
same shape: `130/75` where gold says `130/75mmHg`, `37` where gold says `37°C`.
Their combined WER is 14.75 across 450 matched pairs — 3.3 points of the factor.

`labvalues.py` already had the unit vocabulary; it used it to decide whether a
bare number was a measurement and then dropped it from the span. Both questions
have the same answer.

Run:  pytest tests/test_boundary_units.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.decision import emit  # noqa: E402
from smart_medic.extract import labvalues, recall_floor, tokenize  # noqa: E402
from smart_medic.io.document import Document  # noqa: E402
from smart_medic.layout.kv import split_units  # noqa: E402
from smart_medic.layout.lines import split_lines  # noqa: E402
from smart_medic.linking import icd  # noqa: E402


def _values(raw: str) -> list[str]:
    doc = Document(doc_id="t", raw=raw)
    lines = split_lines(doc)
    found = labvalues.spans(doc, tokenize(doc), split_units(doc, lines))
    return [
        s.text(doc) for s in found if s.argmax_type() == labvalues.VALUE_TYPE
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Huyết áp: 130/76 mmHg", "130/76 mmHg"),
        ("Nhiệt độ: 37°C", "37°C"),
        ("Natri: 141 mmol/l", "141 mmol/l"),
        ("Mạch: 93 l/p", "93 l/p"),
        ("Hồng cầu: 4,49 T/l", "4,49 T/l"),
        ("Bạch cầu: 14.99 G/L", "14.99 G/L"),
    ],
)
def test_value_span_includes_its_unit(raw, expected):
    assert expected in _values(raw)


def test_offsets_still_index_raw_exactly():
    raw = "Huyết áp: 130/76 mmHg\nNhiệt độ: 37°C\n"
    doc = Document(doc_id="t", raw=raw)
    lines = split_lines(doc)
    for s in labvalues.spans(doc, tokenize(doc), split_units(doc, lines)):
        assert raw[s.start : s.end] == s.text(doc)


def test_unit_match_stops_at_a_token_boundary():
    """The bug this guard exists for.

    The unit alternation is unanchored on its right, so a longer word beginning
    with a shorter unit was being cut in half: `93 l/p` matched the bare `l` and
    produced `93 l`, and `Tăng gánh` matched `g` and produced `Tăng g`. Both are
    worse than the bare number they replaced.
    """
    assert "93 l" not in _values("Mạch: 93 l/p")
    assert not any(v.endswith(" g") for v in _values("Chỉ số: 5 gánh nặng"))


def test_unit_is_not_taken_from_the_next_line():
    raw = "Kali: 5\nmmol/l là đơn vị\n"
    assert "5" in _values(raw)
    assert not any("mmol" in v for v in _values(raw))


# ───────────────── symptom codes come from ICD chapter XVIII ─────────────────
@pytest.mark.parametrize(
    "surface, wrong_without, right_with",
    [
        ("sốt", "A68", "R50"),      # relapsing fever → fever
        ("nôn", "Y53.7", "R11"),    # poisoning by emetics → nausea and vomiting
        ("chóng mặt", "A88.1", "R42"),  # epidemic vertigo → dizziness
    ],
)
def test_symptom_retrieval_prefers_chapter_r(surface, wrong_without, right_with):
    """Plain IDF-cosine picks a rare disease name over the plain symptom entry.

    A rare disease containing the symptom word carries far more IDF than the
    symptom itself, so "sốt" retrieves relapsing fever. Chapter XVIII (R00–R99)
    is titled "Symptoms, signs and abnormal clinical findings" — for a
    TRIỆU_CHỨNG span, that is the chapter the code belongs to.
    """
    plain = icd.retrieve(surface)
    boosted = icd.retrieve(surface, prefer_symptom_chapter=True)
    assert plain and plain[0].startswith(wrong_without[0])
    assert boosted and boosted[0].startswith(right_with)


def test_the_bonus_is_a_preference_not_a_filter():
    """A symptom whose best match is a real disease code keeps it."""
    boosted = icd.retrieve("ban đỏ", prefer_symptom_chapter=True)
    assert boosted and not boosted[0].startswith("R"), (
        "a large-margin non-R match should survive the bonus"
    )


def test_only_symptom_spans_ask_for_the_boost():
    """The flag must reach `retrieve` for TRIỆU_CHỨNG and for nothing else.

    Comparing `retrieve(x)` against `retrieve(x, prefer_symptom_chapter=False)`
    would prove nothing — both are the same default path. What can actually
    regress is `decision/emit.py` passing the flag for the wrong type, so this
    calls the real code and records what it asked for.
    """
    seen: dict[str, bool] = {}
    real = emit.icd.retrieve

    def spy(surface, **kw):
        seen[surface] = bool(kw.get("prefer_symptom_chapter"))
        return real(surface, **kw)

    # Real documents, not a fixture line: `retrieve` is only called when the
    # gazetteer found no code, so a hand-written sentence of well-known terms
    # never reaches this branch at all.
    by_type: dict[str, str] = {}
    emit.icd.retrieve = spy
    try:
        for doc_id in (str(n) for n in range(1, 11)):
            raw = (ROOT / "data" / "test" / f"{doc_id}.txt").open(
                encoding="utf-8", newline=""
            ).read()
            doc = Document(doc_id=doc_id, raw=raw)
            lines = split_lines(doc)
            spans = recall_floor(doc, lines, split_units(doc, lines))
            for record in emit.finalize(doc, spans, emit.select_threshold(10.0)):
                by_type[record["text"]] = record["type"]
    finally:
        emit.icd.retrieve = real

    asked = {t: flag for t, flag in seen.items() if t in by_type}
    assert asked, "no retrieval happened — the fixture no longer exercises this path"

    # Both branches must be present, or the test could pass by never reaching the
    # case it is about. Over documents 1–10: ~52 symptom retrievals and ~22
    # diagnosis retrievals.
    types_asked = {by_type[t] for t in asked}
    assert {"TRIỆU_CHỨNG", "CHẨN_ĐOÁN"} <= types_asked, (
        f"only {sorted(types_asked)} reached retrieval — this test cannot "
        f"distinguish the flag being right from it never being set"
    )

    for surface, boosted in asked.items():
        assert boosted == (by_type[surface] == "TRIỆU_CHỨNG"), (
            f"{surface!r} is {by_type[surface]} but asked for "
            f"prefer_symptom_chapter={boosted}"
        )


def test_retrieval_is_deterministic():
    """ADR 0005: two builds of one commit must produce the same bytes."""
    for _ in range(3):
        assert icd.retrieve("sốt", prefer_symptom_chapter=True) == icd.retrieve(
            "sốt", prefer_symptom_chapter=True
        )
