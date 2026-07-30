"""L6 · the 11.59-point gate, checked on the JSON that was actually written.

The acceptance criterion is deliberately phrased over files on disk, not variables
in memory: "0 lab entities carrying an assertion, 0 uncodeable entities carrying
candidates — checked on the written JSON itself". So the tests here write, read
back, and then assert.

Two enforcement policies, and both are tested:

* schema constraints are REPAIRED silently (the span survives, the illegal flag
  does not)
* anything about `position` RAISES (an offset mismatch is always a bug in a stage
  above, never data noise)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic import validate  # noqa: E402
from smart_medic.io import Document, load_gold, load_test, output_dir  # noqa: E402
from smart_medic.io import test_dir as corpus_test_dir  # noqa: E402
from smart_medic.io.labels import CODEABLE_TYPES, LAB_TYPES  # noqa: E402

RAW = "Chẩn đoán: thiếu men G6PD; Chol: 4,7 mmol/l\n"

# Spans derived from RAW, never hand-counted: an off-by-one in a fixture is
# indistinguishable from the bug these tests exist to catch.
DX = (RAW.index("thiếu men G6PD"), RAW.index("thiếu men G6PD") + len("thiếu men G6PD"))
DX_INNER = (RAW.index("men G6PD"), DX[1])
LAB = (RAW.index("Chol"), RAW.index("Chol") + len("Chol"))
LABEL = (RAW.index("Chẩn đoán"), RAW.index("Chẩn đoán") + len("Chẩn đoán"))


@pytest.fixture(scope="module")
def codes():
    return validate.load_code_index()


def _entity(raw, start, end, etype, **kw):
    e = {
        "text": raw[start:end],
        "type": etype,
        "position": [start, end],
        "assertions": [],
        "candidates": [],
    }
    e.update(kw)
    return e


# ───────────────── the gate is a no-op on clean data ─────────────────
def test_gold_passes_every_check(codes):
    """162 files / 7435 entities. A single violation here invalidates every score."""
    errs = []
    for doc in load_gold():
        errs += validate.schema.check(doc.entities, doc.raw, codes, doc.doc_id)
    assert not errs, f"{len(errs)} violation(s) in GOLD:\n  " + "\n  ".join(errs[:10])


def test_every_gold_code_resolves_in_the_kb(codes):
    """If gold codes did not resolve, check 5 would be measuring the wrong thing."""
    unknown = {
        c
        for doc in load_gold()
        for e in doc.entities
        for c in e.get("candidates", [])
        if c not in codes
    }
    assert not unknown, f"gold uses codes absent from the packaged KB: {sorted(unknown)[:10]}"


def test_written_output_dir_satisfies_the_acceptance_criteria(codes):
    """The criterion, read off `data/output/` as it stands on disk."""
    errs = validate.audit_dir(output_dir(), corpus_test_dir(), codes=codes)
    lab = [e for e in errs if "must have EMPTY assertions" in e]
    cand = [e for e in errs if "must have EMPTY candidates" in e]
    assert not lab, f"{len(lab)} lab entities carry assertions: {lab[:5]}"
    assert not cand, f"{len(cand)} uncodeable entities carry candidates: {cand[:5]}"
    assert not errs, f"{len(errs)} other violation(s): {errs[:5]}"


# ───────────────── check 3 · the 11.59 points ─────────────────
@pytest.mark.parametrize("etype", sorted(LAB_TYPES))
@pytest.mark.parametrize("flag", ["isNegated", "isHistorical", "isFamily"])
def test_lab_assertion_is_cleared_at_serialisation(tmp_path, etype, flag):
    """Leaking `isNegated` onto the two lab types takes 70.00 down to 58.41."""
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *LAB, etype, assertions=[flag])
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)

    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert written[0]["assertions"] == [], (
        f"{etype} kept {flag} in the WRITTEN file — this is the 11.59-point leak"
    )
    assert written[0]["text"] == "Chol"  # the span survives; only the flag goes


def test_assertable_types_keep_their_flags(tmp_path):
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *DX, "CHẨN_ĐOÁN", assertions=["isNegated"])
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert written[0]["assertions"] == ["isNegated"]


def test_unknown_assertion_labels_are_dropped(tmp_path):
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(
        RAW, *DX, "CHẨN_ĐOÁN", assertions=["isNegated", "isHypothetical"]
    )
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert written[0]["assertions"] == ["isNegated"]


# ───────────────── check 4 and 5 · candidates ─────────────────
@pytest.mark.parametrize("etype", ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"])
def test_uncodeable_types_lose_their_candidates(tmp_path, etype, codes):
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *LAB, etype, candidates=["D55.0"])
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=codes)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert written[0]["candidates"] == []


def test_codes_absent_from_the_kb_are_dropped(tmp_path, codes):
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *DX, "CHẨN_ĐOÁN", candidates=["D55.0", "ZZ99.9", "28439"])
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=codes)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert written[0]["candidates"] == ["D55.0", "28439"], (
        "an unlookupable code is a wrong code — it must not reach the file"
    )


def test_codeable_types_are_exactly_the_two_documented(codes):
    assert CODEABLE_TYPES == {"CHẨN_ĐOÁN", "THUỐC"}


# ───────────────── check 1 · offsets RAISE, never repair ─────────────────
def test_one_character_shift_raises(tmp_path):
    """A 1-character span shift scores 0.00 under `exact`. It must never be written."""
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *DX, "CHẨN_ĐOÁN")
    entity["position"] = [DX[0] + 1, DX[1] + 1]  # shift, keep the old text
    with pytest.raises(validate.OffsetViolation):
        validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)
    assert not (tmp_path / "1.json").exists(), "a bad record must not be written at all"


def test_nfc_shift_is_named_in_the_error():
    """The NFC signature is the difference between an hour and a day of debugging."""
    import unicodedata

    nfd = unicodedata.normalize("NFD", "Chẩn đoán")
    errs = validate.offsets.check(
        nfd, [{"text": "Chẩn đoán", "type": "CHẨN_ĐOÁN", "position": [0, len(nfd)]}]
    )
    assert errs and "UNICODE NORMALISATION" in errs[0]


def test_text_is_never_rewritten_to_match_the_offset(tmp_path):
    """Repairing `text` from `raw` would make check 1 true by construction."""
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *DX, "CHẨN_ĐOÁN")
    entity["text"] = "something else"
    with pytest.raises(validate.OffsetViolation):
        validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)


# ───────────────── check 6 and 7 · nesting and duplicates ─────────────────
def test_nested_spans_are_removed_keeping_the_longer(tmp_path):
    """0/7435 gold spans nest, so the schema forbids it."""
    doc = Document(doc_id="1", raw=RAW)
    outer = _entity(RAW, *DX, "CHẨN_ĐOÁN")
    inner = _entity(RAW, *DX_INNER, "CHẨN_ĐOÁN")
    validate.emit_document(doc, [inner, outer], tmp_path / "1.json", codes=None)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert [e["position"] for e in written] == [list(DX)]


def test_duplicates_are_removed(tmp_path):
    doc = Document(doc_id="1", raw=RAW)
    e = _entity(RAW, *DX, "CHẨN_ĐOÁN")
    validate.emit_document(doc, [e, dict(e)], tmp_path / "1.json", codes=None)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert len(written) == 1


def test_invalid_type_is_dropped(tmp_path):
    doc = Document(doc_id="1", raw=RAW)
    good = _entity(RAW, *DX, "CHẨN_ĐOÁN")
    bad = _entity(RAW, *LAB, "NOT_A_TYPE")
    validate.emit_document(doc, [good, bad], tmp_path / "1.json", codes=None)
    written = json.loads((tmp_path / "1.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in written] == ["CHẨN_ĐOÁN"]


# ───────────────── the file format itself ─────────────────
def test_written_file_format(tmp_path):
    doc = Document(doc_id="1", raw=RAW)
    entity = _entity(RAW, *LABEL, "CHẨN_ĐOÁN", candidates=[])
    validate.emit_document(doc, [entity], tmp_path / "1.json", codes=None)
    blob = (tmp_path / "1.json").read_bytes()

    assert not blob.startswith(b"\xef\xbb\xbf"), "must not carry a UTF-8 BOM"
    assert blob.endswith(b"\n"), "must end with a newline"
    assert b"\r\n" not in blob, "must use \\n line endings on every platform"
    text = blob.decode("utf-8")
    assert "Chẩn đoán" in text, "ensure_ascii=False — Vietnamese must not be escaped"
    assert "\\u" not in text
    # documented field order
    assert list(json.loads(text)[0]) == [
        "text",
        "type",
        "candidates",
        "assertions",
        "position",
    ]


def test_empty_list_is_valid_a_missing_file_is_not(tmp_path):
    doc = Document(doc_id="7", raw=RAW)
    validate.emit_document(doc, [], tmp_path / "7.json", codes=None)
    assert json.loads((tmp_path / "7.json").read_text(encoding="utf-8")) == []


def test_emit_corpus_rejects_a_hole(tmp_path):
    docs = load_test()[:3]
    with pytest.raises(ValueError, match="incomplete"):
        validate.emit_corpus(
            [(d, []) for d in docs[:2]],
            tmp_path,
            codes=None,
            expect_ids=[d.doc_id for d in docs],
        )


def test_emit_report_reports_density(tmp_path):
    docs = load_test()[:4]
    report = validate.emit_corpus(
        [(d, [_entity(d.raw, 0, 4, "TRIỆU_CHỨNG")]) for d in docs],
        tmp_path,
        codes=None,
        expect_ids=[d.doc_id for d in docs],
    )
    assert report.files_written == 4
    assert report.total_entities == 4
    assert report.density() == 1.0, "density feeds decision.emit_threshold"
