"""L1 · the offset invariant, measured on all 262 real documents.

`tests/test_offsets.py` checks that the *predictions we wrote* slice back correctly.
This file checks the *mechanism* they depend on: that `Document` never mutates
`raw`, that the NFC view is exactly mapped, and that `to_raw` / `to_norm` are
inverses on every character of every document in the repo.

20/100 test files and 41/162 gold files are not in NFC. Those 61 files are the
whole reason this module exists — a normalisation applied one line too early shifts
later spans by up to 143 characters and raises nothing.

No hand-written fixtures for the corpus checks. Real files or nothing.
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.io import (  # noqa: E402
    AnnotatedDocument,
    Document,
    LoadReport,
    OffsetError,
    gold_dir,
    load_gold,
    load_silver,
    load_test,
    read_raw,
)
# Aliased on import: pytest collects any module-level name starting with `test_`,
# so importing `test_dir` under its own name turns a path helper into a fake test.
from smart_medic.io import test_dir as corpus_test_dir  # noqa: E402
from smart_medic.io.labels import LAB_TYPES  # noqa: E402

#: Known corpus facts. If one of these changes, a corpus changed — stop and look.
N_TEST = 100
N_GOLD = 162
N_SILVER = 543
NON_NFC_TEST = 20
NON_NFC_GOLD = 41
SILVER_SCHEMA_VIOLATIONS = 165


@pytest.fixture(scope="module")
def all_docs() -> list[Document]:
    """The 262 documents the round-trip criterion is stated over."""
    return load_test() + load_gold()


# ─────────────────────────── corpus shape ───────────────────────────
def test_corpus_sizes(all_docs):
    assert len(load_test()) == N_TEST
    assert len(load_gold()) == N_GOLD
    assert len(all_docs) == N_TEST + N_GOLD == 262


def test_non_nfc_counts():
    """The documented counts, re-measured. These drive every warning in the docs."""
    assert sum(1 for d in load_test() if not d.is_nfc) == NON_NFC_TEST
    assert sum(1 for d in load_gold() if not d.is_nfc) == NON_NFC_GOLD


# ─────────────────────── raw is never modified ───────────────────────
def test_raw_is_byte_identical_to_the_file():
    """`Document.raw` must equal the file's decoded bytes, with nothing rewritten."""
    for path in sorted(corpus_test_dir().glob("*.txt")):
        raw = path.read_bytes().decode("utf-8")
        doc = Document.from_path(path)
        assert doc.raw == raw, f"{path.name}: raw differs from the file's own bytes"


def test_newline_is_not_translated(tmp_path):
    """`newline=""` is the whole defence against a CRLF file shifting every offset."""
    p = tmp_path / "crlf.txt"
    p.write_bytes("dòng một\r\ndòng hai\r\n".encode("utf-8"))
    doc = Document.from_path(p)
    assert "\r\n" in doc.raw
    assert doc.raw.count("\n") == 2
    assert len(doc.raw) == len("dòng một\r\ndòng hai\r\n")
    # the position of the second line must survive the read
    assert doc.slice(10, 18) == "dòng hai"


def test_document_is_frozen():
    doc = load_test()[0]
    with pytest.raises(Exception):
        doc.raw = "tampered"  # type: ignore[misc]


# ─────────────────── the NFC/NFD round trip · 262 files ───────────────────
def test_normalized_is_exactly_nfc(all_docs):
    for doc in all_docs:
        assert doc.nfc_map_exact, (
            f"{doc.doc_id}: chunk-wise NFC did not reproduce NFC(raw); the loader "
            f"fell back to the identity map"
        )
        assert doc.normalized == unicodedata.normalize("NFC", doc.raw), doc.doc_id
        assert len(doc.char_map) == len(doc.normalized), doc.doc_id


def test_round_trip_norm_raw_norm(all_docs):
    """`to_norm(to_raw(k)) == k` for EVERY index of EVERY document. Tolerance 0."""
    checked = 0
    for doc in all_docs:
        for k in range(len(doc.normalized) + 1):
            raw_idx = doc.to_raw(k)
            assert doc.to_norm(raw_idx) == k, (
                f"{doc.doc_id}: normalized index {k} -> raw {raw_idx} -> "
                f"{doc.to_norm(raw_idx)}"
            )
            checked += 1
    assert checked > 200_000, f"only {checked} indices checked — corpus shrank?"


def test_mapped_span_slices_back_to_the_same_text(all_docs):
    """A span found on `.normalized` must slice out equal text from `.raw`.

    This is the operation every gazetteer match performs, and the one that goes
    wrong silently. On an NFD document the two strings differ byte for byte, so the
    comparison is made under NFC — which is precisely why the *offsets* must come
    from `raw` and the *matching* from `normalized`.
    """
    step = 97  # a prime, so the sample is not aligned to line structure
    for doc in all_docs:
        n = doc.normalized
        for start in range(0, max(1, len(n) - 12), step):
            end = min(start + 12, len(n))
            r_start, r_end = doc.to_raw_span(start, end)
            assert unicodedata.normalize("NFC", doc.slice(r_start, r_end)) == (
                unicodedata.normalize("NFC", n[start:end])
            ), f"{doc.doc_id}: normalized[{start}:{end}] does not map back"


def test_nfd_document_round_trips():
    """An explicitly decomposed document: raw stays NFD, offsets stay on raw."""
    nfc = "Chẩn đoán: viêm phổi"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    doc = Document(doc_id="nfd", raw=nfd)
    assert doc.raw == nfd and not doc.is_nfc
    assert doc.normalized == nfc

    start = nfc.index("viêm phổi")
    r_start, r_end = doc.to_raw_span(start, start + len("viêm phổi"))
    assert doc.slice(r_start, r_end) == nfd[r_start:r_end]
    assert unicodedata.normalize("NFC", doc.slice(r_start, r_end)) == "viêm phổi"
    # and the raw span is LONGER than the NFC one — this is the 143-char drift
    assert (r_end - r_start) > len("viêm phổi")


def test_out_of_range_slice_is_loud():
    doc = load_test()[0]
    with pytest.raises(OffsetError):
        doc.slice(0, len(doc.raw) + 1)
    with pytest.raises(OffsetError):
        doc.to_raw(len(doc.normalized) + 1)
    with pytest.raises(OffsetError):
        doc.to_norm(len(doc.raw) + 1)


# ───────────────────────── corpus loading ─────────────────────────
def test_gold_entities_slice_back_exactly():
    for doc in load_gold():
        for e in doc.entities:
            start, end = e["position"]
            assert doc.slice(start, end) == e["text"], f"{doc.doc_id}: {e}"


def test_silver_schema_violations_are_filtered_at_load():
    """The 165 illegal lab assertions are cleared as the corpus loads.

    Policy from `data/README.md`: filter on load, do NOT regenerate the 543 files.
    Regenerating them would make every number already measured on this corpus
    irreproducible.
    """
    report = LoadReport()
    docs = load_silver(report)
    assert len(docs) == N_SILVER
    assert report.assertions_cleared == SILVER_SCHEMA_VIOLATIONS, (
        f"expected {SILVER_SCHEMA_VIOLATIONS} illegal lab assertions to be cleared, "
        f"cleared {report.assertions_cleared}"
    )
    assert report.offset_mismatch_dropped == 0, (
        f"{report.offset_mismatch_dropped} silver entities have drifted offsets — "
        f"the generator regressed"
    )
    # and nothing illegal survives
    leaks = [
        (d.doc_id, e)
        for d in docs
        for e in d.entities
        if e["type"] in LAB_TYPES and e.get("assertions")
    ]
    assert not leaks, f"{len(leaks)} lab entities still carry assertions: {leaks[:3]}"


def test_gold_needs_no_filtering():
    """Gold is the yardstick, so the sanitiser must be a no-op on it."""
    report = LoadReport()
    load_gold(report)
    assert report.assertions_cleared == 0, (
        f"GOLD has {report.assertions_cleared} schema violation(s) — every score, "
        f"threshold and ablation measured against it is suspect"
    )
    assert report.offset_mismatch_dropped == 0


def test_annotated_document_is_a_document():
    """`load_gold()` satisfies its documented `-> list[Document]` contract."""
    doc = load_gold()[0]
    assert isinstance(doc, AnnotatedDocument) and isinstance(doc, Document)
    assert hash(doc)  # holds dicts; must still be usable in a set
    assert len({doc, doc}) == 1


def test_gold_dir_matches_the_documented_path():
    assert gold_dir().is_dir()
    assert len(list(gold_dir().glob("*.json"))) == N_GOLD


def test_read_raw_matches_the_reference_reader():
    """`io.read_raw` and the reader inside tests/test_offsets.py must agree."""
    for path in sorted(corpus_test_dir().glob("*.txt"))[:20]:
        assert read_raw(path) == path.read_text(encoding="utf-8", newline="")
