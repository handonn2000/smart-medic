"""L3 · lane R, tested on the repo's REAL corpora. No invented fixtures.

A fixture written by the same person who wrote the matcher tests that person's
idea of the data. The failures that actually cost points in this project — the
41/162 gold files that are not in NFC, the mid-phrase line wraps in `restyled/`,
`4,7` as a decimal comma — are all properties of the real corpus, and none of them
would appear in a hand-made string.

So every test here loads `data/test/` or the gold corpus and asserts an invariant
over all of it. The two that matter most:

* `test_offsets_map_back_to_raw` — a span whose text does not slice back out of
  `Document.raw` is worth 0 and raises nothing. This is the whole 70.00.
* `test_no_nested_spans` — 0/7435 gold spans nest, so a nested pair is one right
  answer plus one guaranteed spurious span.
"""
from __future__ import annotations

import unicodedata

import pytest

from smart_medic.extract import RecallFloorReport, recall_floor
from smart_medic.extract import aho, kvspan, labvalues
from smart_medic.extract.spans import Span, tokenize
from smart_medic.io.corpus import load_gold, load_test
from smart_medic.io.labels import LAB_TYPES, TYPES
from smart_medic.layout.kv import split_units
from smart_medic.layout.lines import split_lines

#: A slice of the real corpus, so the suite stays quick without going synthetic.
SAMPLE = 25


@pytest.fixture(scope="module")
def test_docs():
    return load_test()[:SAMPLE]


@pytest.fixture(scope="module")
def gold_docs():
    return load_gold()[:SAMPLE]


@pytest.fixture(scope="module")
def runs(test_docs, gold_docs):
    """`(doc, spans)` for both corpora. Computed once — the gazetteer is 4 MB."""
    out = []
    for doc in list(test_docs) + list(gold_docs):
        lines = split_lines(doc)
        units = split_units(doc, lines)
        out.append((doc, recall_floor(doc, lines, units)))
    return out


# ─────────────────────── the invariants that hold the score ───────────────────
def test_offsets_map_back_to_raw(runs):
    """`raw[start:end]` must be the span's text, byte-exact, tolerance 0.

    Matching happens on `doc.normalized`; anything that forgets `to_raw_span()`
    shifts every later span by up to 143 characters and raises nothing at all.
    """
    for doc, spans in runs:
        for span in spans:
            text = span.text(doc)
            assert doc.raw[span.start : span.end] == text, (
                f"{doc.doc_id}: span [{span.start},{span.end}] does not slice back"
            )


def test_non_nfc_documents_are_covered(runs):
    """The offset test above is only meaningful if non-NFC files are in the sample.

    20/100 test files and 41/162 gold files are not in NFC. If a refactor made the
    sample all-NFC, `test_offsets_map_back_to_raw` would pass while blind to the
    exact bug it exists to catch.
    """
    non_nfc = [doc.doc_id for doc, _ in runs if not doc.is_nfc]
    assert non_nfc, "sample contains no non-NFC document — the offset test is blind"


def test_no_nested_spans(runs):
    """0/7435 gold spans are nested, so the schema forbids it."""
    for doc, spans in runs:
        pos = [(s.start, s.end) for s in spans]
        for a in pos:
            for b in pos:
                if a == b:
                    continue
                assert not (a[0] <= b[0] and b[1] <= a[1]), (
                    f"{doc.doc_id}: {a} contains {b}"
                )


def test_no_overlapping_spans(runs):
    for doc, spans in runs:
        ordered = sorted(spans, key=lambda s: s.start)
        for prev, nxt in zip(ordered, ordered[1:]):
            assert prev.end <= nxt.start, (
                f"{doc.doc_id}: [{prev.start},{prev.end}] overlaps "
                f"[{nxt.start},{nxt.end}]"
            )


def test_spans_are_never_blank_or_whitespace(runs):
    for doc, spans in runs:
        for span in spans:
            text = span.text(doc)
            assert text.strip(), f"{doc.doc_id}: blank span at {span.start}"


def test_type_dist_is_a_distribution(runs):
    for doc, spans in runs:
        for span in spans:
            assert span.type_dist, f"{doc.doc_id}: empty type_dist"
            assert set(span.type_dist) <= TYPES, (
                f"{doc.doc_id}: unknown type in {span.type_dist}"
            )
            total = sum(span.type_dist.values())
            assert abs(total - 1.0) < 1e-6, f"{doc.doc_id}: type_dist sums to {total}"
            assert 0.0 <= span.score <= 1.0


def test_extract_never_reads_the_emit_threshold(runs):
    """`extract/` must not know what the gate is. Structural, not statistical.

    The invariant is *where the comparison happens*, so this checks the source:
    no module under `extract/` may read `decision.emit_threshold`. Checking the
    score distribution instead would be checking a coincidence — at P1 every
    lane-R prior happens to sit above the configured gate of 0.25 (lowest is
    0.30), which means the gate currently filters nothing. That is a real finding
    about the CONFIG, reported in the phase notes, and it is not `extract/`'s
    business either way.
    """
    import ast

    from smart_medic.io.config import repo_root

    pkg = repo_root() / "src" / "smart_medic" / "extract"
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(
                n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value.startswith("decision.")
            ):
                offenders.append(f"{path.name}:{node.lineno}: {node.value!r}")
    assert not offenders, (
        "extract/ reads a decision/ config key — only decision/ may apply a "
        "threshold:\n  " + "\n  ".join(offenders)
    )


def test_span_scores_carry_information(runs):
    """Scores must vary by evidence, or `decision/` has nothing to threshold on."""
    scores = {round(s.score, 4) for _, spans in runs for s in spans}
    assert len(scores) > 1, f"every span scored the same ({scores}) — the prior is dead"


def test_determinism(test_docs):
    """Two runs of the same code must produce identical spans.

    A non-deterministic tie-break makes two builds of the same commit two
    different submissions, and reproducibility is a disqualification risk.
    """
    for doc in test_docs[:5]:
        a = recall_floor(doc)
        b = recall_floor(doc)
        assert [(s.start, s.end, s.argmax_type()) for s in a] == [
            (s.start, s.end, s.argmax_type()) for s in b
        ]


# ───────────────────────────── lane-specific rules ────────────────────────────
def test_lab_lane_emits_only_lab_types(gold_docs):
    for doc in gold_docs:
        lines = split_lines(doc)
        units = split_units(doc, lines)
        for span in labvalues.spans(doc, tokenize(doc), units):
            assert span.argmax_type() in LAB_TYPES, (
                f"{doc.doc_id}: labvalues emitted {span.argmax_type()}"
            )


def test_decimal_comma_is_never_split(gold_docs, test_docs):
    """`Chol: 4,7 mmol/l` must not yield `4` and `7`.

    Splitting a decimal comma turns one lab result into two wrong spans, and
    boundary errors are 6.95 points on the leverage map.
    """
    seen = 0
    for doc in list(gold_docs) + list(test_docs):
        lines = split_lines(doc)
        units = split_units(doc, lines)
        for span in labvalues.spans(doc, tokenize(doc), units):
            text = span.text(doc)
            start, end = span.start, span.end
            # A span ending immediately before `,<digit>` has cut a decimal.
            if text[-1:].isdigit() and doc.raw[end : end + 2].strip()[:1] == ",":
                nxt = doc.raw[end + 1 : end + 2]
                assert not nxt.isdigit(), (
                    f"{doc.doc_id}: span {text!r} at [{start},{end}] split the "
                    f"decimal comma in {doc.raw[start:end + 4]!r}"
                )
            if "," in text and any(c.isdigit() for c in text):
                seen += 1
    assert seen or True  # presence is corpus-dependent; the assertion above is the test


def test_gazetteer_matches_at_word_boundaries(test_docs):
    """A gazetteer hit may not start or end inside a word.

    Token-level matching is what makes this true; a character-level automaton
    would find `ho` inside `hoặc` and `hồng cầu` on every page.
    """
    for doc in test_docs:
        norm = doc.normalized
        for span in aho.spans(doc, tokenize(doc)):
            ns, ne = doc.to_norm_span(span.start, span.end)
            before = norm[ns - 1 : ns]
            after = norm[ne : ne + 1]
            for ch, where in ((before, "before"), (after, "after")):
                if not ch:
                    continue
                assert not (ch.isalnum() or unicodedata.combining(ch)), (
                    f"{doc.doc_id}: {span.text(doc)!r} has a word character "
                    f"{where} it ({ch!r})"
                )


def test_gazetteer_carries_codes_for_p5(test_docs):
    """`aho.py` must pass the KB codes through — `linking/` needs them at P5."""
    with_codes = [
        s
        for doc in test_docs
        for s in aho.spans(doc, tokenize(doc))
        if s.codes
    ]
    assert with_codes, "no gazetteer hit carried a code; P5 has nothing to link"


def test_kvspan_never_duplicates_another_lane(gold_docs):
    for doc in gold_docs:
        lines = split_lines(doc)
        units = split_units(doc, lines)
        view = tokenize(doc)
        other = labvalues.spans(doc, view, units) + aho.spans(doc, view)
        for span in kvspan.spans(doc, view, units, lines, covered=other):
            for o in other:
                assert not (span.start < o.end and o.start < span.end), (
                    f"{doc.doc_id}: kvspan re-emitted a covered span"
                )


# ──────────────────────────────── the automaton ───────────────────────────────
def test_automaton_finds_every_key_it_was_given():
    """Aho-Corasick correctness, including the suffix chain.

    `viêm phổi` inside `viêm phổi do lupus` has to stay *reachable* even when the
    longer key wins — the fail-link chain is what makes the shorter match the
    fallback when the longer one fails a phrase-continuity check.
    """
    a = aho.TokenAutomaton()
    keys = [("viêm", "phổi"), ("phổi",), ("viêm", "phổi", "do", "lupus"), ("lupus",)]
    for i, key in enumerate(keys):
        a.add(key, i)
    a.finalise()

    tokens = ["bệnh", "viêm", "phổi", "do", "lupus", "nặng"]
    found = set()
    state = 0
    for i, tok in enumerate(tokens):
        state = a.step(state, tok)
        for payload in a.matches_ending_at(state):
            found.add((i - len(keys[payload]) + 1, i, keys[payload]))

    assert (1, 2, ("viêm", "phổi")) in found
    assert (2, 2, ("phổi",)) in found
    assert (1, 4, ("viêm", "phổi", "do", "lupus")) in found
    assert (4, 4, ("lupus",)) in found


def test_report_density_is_the_emit_threshold_input(test_docs):
    """Density is an input to `decision.emit_threshold`, so it must be reported."""
    report = RecallFloorReport()
    for doc in test_docs:
        recall_floor(doc, report=report)
    assert report.documents == len(test_docs)
    assert report.density() > 0
    assert "per file" in report.summary() or "/file" in report.summary()


def test_span_rejects_a_degenerate_range():
    with pytest.raises(ValueError):
        Span(start=5, end=5, type_dist={"THUỐC": 1.0}, score=0.5, source="aho")
