"""Offset and schema integrity — the single most important test in this repo.

Three independent guards:

1. `test_test_corpus_unmodified`  — the 100 scored input files must never change.
   Guards against an agent "fixing the encoding" of data/test/*.txt, which would
   silently invalidate every offset we produce and every measurement we take.

2. `test_output_offsets_and_schema` — for every data/output/N.json we emit,
   assert `raw[start:end] == text` **byte-exact against the unmodified source**,
   plus the full competition schema. 20/100 test files are not in Unicode NFC;
   any pipeline stage that normalises before computing offsets shifts every
   later span by up to 143 characters. This test is what catches that.

3. `test_silver_offsets` — same offset check against the generated silver
   corpus, so generator drift surfaces immediately rather than after training.

Run:  pytest tests/test_offsets.py -q
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

RECORD_NAME = re.compile(r"^\d+$")


def numbered(directory: Path, suffix: str) -> list[Path]:
    """Record files only — `1.json`, not `run_manifest.json`."""
    return sorted(
        (p for p in directory.glob(f"*{suffix}") if RECORD_NAME.match(p.stem)),
        key=lambda p: int(p.stem),
    )

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smart_medic.io.labels import (  # noqa: E402
    ASSERTABLE_TYPES as _ASSERTABLE_TYPES,
    CODEABLE_TYPES as _CODEABLE_TYPES,
)

TEST_DIR = ROOT / "data" / "test"
OUTPUT_DIR = ROOT / "data" / "output"
SILVER_ROOT = ROOT / "data" / "generated_medical_records"
MANIFEST = Path(__file__).parent / "data_test_manifest.json"

TYPES = {
    "TRIỆU_CHỨNG",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
    "CHẨN_ĐOÁN",
    "THUỐC",
}
ASSERTIONS = {"isNegated", "isFamily", "isHistorical"}

# Imported, not restated. These were literals here until W1, which made
# TRIỆU_CHỨNG codeable (ADR 0006) — and this file then failed the submission gate
# with 2000 "must have empty candidates" errors on output that was correct. A
# schema rule copied into three places is a rule that will disagree with itself;
# `io/labels.py` is the one that `validate/schema.py` actually enforces, so this
# check has to be reading the same object.
#
# The invariant worth pinning independently is the lab-type one, and it is:
# test_validate.py::test_codeable_types_are_exactly_the_three_documented asserts
# the exact membership and that no lab type ever enters it.
CODEABLE = set(_CODEABLE_TYPES)
ASSERTABLE = set(_ASSERTABLE_TYPES)


def read_raw(path: Path) -> str:
    """Read a source document EXACTLY as the scorer will see it.

    No normalisation, no newline translation. `newline=""` stops Python from
    rewriting CRLF, which would shift offsets on any file that uses it.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def check_entities(entities, raw: str, label: str) -> list[str]:
    """Return a list of human-readable violations (empty == clean)."""
    errs: list[str] = []
    seen: set[tuple[int, int, str]] = set()

    if not isinstance(entities, list):
        return [f"{label}: top level must be a list, got {type(entities).__name__}"]

    for i, e in enumerate(entities):
        where = f"{label}[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: entity must be an object")
            continue

        for field in ("text", "type", "position"):
            if field not in e:
                errs.append(f"{where}: missing required field '{field}'")
        if errs and where in errs[-1]:
            continue

        text, etype, pos = e.get("text"), e.get("type"), e.get("position")

        if etype not in TYPES:
            errs.append(f"{where}: type {etype!r} not one of the 5 allowed")

        if (
            not isinstance(pos, (list, tuple))
            or len(pos) != 2
            or not all(isinstance(v, int) for v in pos)
        ):
            errs.append(f"{where}: position must be [int, int], got {pos!r}")
            continue

        start, end = pos
        if not (0 <= start < end <= len(raw)):
            errs.append(
                f"{where}: position [{start},{end}] out of range for a "
                f"{len(raw)}-char document"
            )
            continue

        # ---- THE critical assertion -------------------------------------
        sliced = raw[start:end]
        if sliced != text:
            errs.append(
                f"{where}: OFFSET MISMATCH\n"
                f"    raw[{start}:{end}] = {sliced!r}\n"
                f"    text              = {text!r}"
            )
            # A shift caused by NFC normalisation has a recognisable signature.
            if unicodedata.normalize("NFC", sliced) == unicodedata.normalize(
                "NFC", str(text)
            ):
                errs[-1] += "\n    ^ strings match under NFC — this is a UNICODE NORMALISATION bug"
        # -----------------------------------------------------------------

        key = (start, end, str(etype))
        if key in seen:
            errs.append(f"{where}: duplicate entity {key}")
        seen.add(key)

        asserts = e.get("assertions", [])
        if not isinstance(asserts, list):
            errs.append(f"{where}: assertions must be a list")
        else:
            bad = set(asserts) - ASSERTIONS
            if bad:
                errs.append(f"{where}: unknown assertions {sorted(bad)}")
            if asserts and etype not in ASSERTABLE:
                errs.append(
                    f"{where}: type {etype} must have empty assertions, got {asserts}"
                )

        cands = e.get("candidates", [])
        if not isinstance(cands, list):
            errs.append(f"{where}: candidates must be a list")
        elif cands and etype not in CODEABLE:
            errs.append(
                f"{where}: type {etype} must have empty candidates, got {cands}"
            )

    return errs


# ─────────────────────────── 1. corpus integrity ───────────────────────────
def test_test_corpus_unmodified():
    """The 100 scored inputs are immutable. Fail loudly if any byte changed."""
    if not TEST_DIR.is_dir():
        pytest.skip("data/test/ not present")

    files = numbered(TEST_DIR, ".txt")
    digests = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }

    if not MANIFEST.exists():
        MANIFEST.write_text(
            json.dumps(digests, indent=1, sort_keys=True), encoding="utf-8"
        )
        pytest.skip(
            f"created baseline manifest with {len(digests)} files — commit "
            f"tests/{MANIFEST.name} and re-run"
        )

    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = [n for n in expected if digests.get(n) != expected[n]]
    missing = [n for n in expected if n not in digests]
    added = [n for n in digests if n not in expected]

    assert not (changed or missing or added), (
        "data/test/ HAS BEEN MODIFIED — the scored inputs must never change.\n"
        f"  changed: {changed}\n  missing: {missing}\n  unexpected: {added}\n"
        "Restore from git (`git checkout -- data/test/`). If a change is "
        f"genuinely intended, delete tests/{MANIFEST.name} to re-baseline."
    )


# ──────────────────────── 2. our submission output ─────────────────────────
def test_output_offsets_and_schema():
    """Every predicted span must slice back to itself from the raw source."""
    if not OUTPUT_DIR.is_dir():
        pytest.skip("data/output/ not present yet")

    outputs = numbered(OUTPUT_DIR, ".json")
    if not outputs:
        pytest.skip("no predictions in data/output/ yet")

    all_errs: list[str] = []
    for out in outputs:
        src = TEST_DIR / f"{out.stem}.txt"
        if not src.exists():
            all_errs.append(f"{out.name}: no matching data/test/{out.stem}.txt")
            continue
        try:
            entities = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            all_errs.append(f"{out.name}: invalid JSON — {exc}")
            continue
        all_errs += check_entities(entities, read_raw(src), out.name)

    assert not all_errs, (
        f"{len(all_errs)} schema/offset violation(s) in data/output/:\n\n"
        + "\n".join(all_errs[:40])
        + ("\n... (truncated)" if len(all_errs) > 40 else "")
    )


# ───────────────────────── 3. silver corpus drift ──────────────────────────
def _silver_pairs():
    for kind in ("synthetic", "translated", "restyled"):
        ann_dir = SILVER_ROOT / kind / "annotations"
        txt_dir = SILVER_ROOT / kind / "text"
        if not ann_dir.is_dir():
            continue
        for ann in sorted(ann_dir.glob("*.json")):
            txt = txt_dir / f"{ann.stem}.txt"
            if txt.exists():
                yield kind, ann, txt


GOLD_DIR = SILVER_ROOT / "restyled" / "annotations_gold"


def test_gold_offsets_and_schema():
    """The hand-adjudicated gold set must be spotless — it is the measuring stick.

    Any violation here is worse than a violation in silver: every score, every
    threshold and every ablation is measured against these files.
    """
    if not GOLD_DIR.is_dir():
        pytest.skip("no gold corpus present")

    txt_dir = SILVER_ROOT / "restyled" / "text"
    all_errs: list[str] = []
    n = 0
    for ann in sorted(GOLD_DIR.glob("*.json")):
        txt = txt_dir / f"{ann.stem}.txt"
        if not txt.exists():
            all_errs.append(f"gold/{ann.name}: no matching text file")
            continue
        try:
            entities = json.loads(ann.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            all_errs.append(f"gold/{ann.name}: invalid JSON — {exc}")
            continue
        n += 1
        all_errs += check_entities(entities, read_raw(txt), f"gold/{ann.name}")

    assert not all_errs, (
        f"{len(all_errs)} violation(s) in the GOLD set ({n} files checked). "
        f"Gold must be clean — fix before measuring anything:\n\n"
        + "\n".join(all_errs[:30])
    )


def test_silver_offsets():
    """Generated training data must satisfy the same offset invariant."""
    pairs = list(_silver_pairs())
    if not pairs:
        pytest.skip("no silver corpus present")

    all_errs: list[str] = []
    lab_flag_errs: list[str] = []
    bad_files = 0
    for kind, ann, txt in pairs:
        try:
            entities = json.loads(ann.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            all_errs.append(f"{kind}/{ann.name}: invalid JSON — {exc}")
            bad_files += 1
            continue
        errs = check_entities(entities, read_raw(txt), f"{kind}/{ann.name}")
        # ADR 0004: the 165 lab-type `assertions` in the silver corpus are a
        # KNOWN data defect, and the accepted remedy is `io.corpus.load_silver()`
        # clearing the flag at load rather than regenerating the corpus (which
        # would invalidate every measured number in configs/ and docs/reports/).
        # Asserting on the raw files therefore tests a layer the decision says is
        # not the enforcement point. Those violations are split out here and
        # checked where they are actually fixed, in
        # test_loader_clears_illegal_lab_assertions below; everything else — and
        # above all an offset mismatch — still has to be zero.
        for e in errs:
            (lab_flag_errs if "must have empty assertions" in e else all_errs).append(e)
        if errs:
            bad_files += 1

    assert not all_errs, (
        f"{len(all_errs)} violation(s) across {bad_files}/{len(pairs)} silver "
        f"files — the generator is producing drifted offsets:\n\n"
        + "\n".join(all_errs[:30])
        + ("\n... (truncated)" if len(all_errs) > 30 else "")
    )


def test_loader_clears_illegal_lab_assertions():
    """ADR 0004's remedy, tested where it actually runs: at load.

    The silver corpus on disk carries `assertions` on lab-type entities, which the
    task forbids. `load_silver()` strips them. This asserts the contract end to
    end — nothing reaches a training loop still carrying an illegal flag — and
    that the loader reports how many it cleared, so a regenerated corpus that
    fixes the defect shows up as the count falling to 0 rather than silently.
    """
    pytest.importorskip("yaml")
    from smart_medic.io.corpus import LoadReport, load_silver
    from smart_medic.io.labels import LAB_TYPES

    report = LoadReport()
    docs = load_silver(report)
    if not docs:
        pytest.skip("no silver corpus present")

    leaked = [
        f"{d.doc_id}[{i}]: {e['type']} kept assertions {e['assertions']}"
        for d in docs
        for i, e in enumerate(d.entities)
        if e.get("type") in LAB_TYPES and e.get("assertions")
    ]
    assert not leaked, (
        f"{len(leaked)} lab-type entities survived load_silver() with an illegal "
        f"assertion — ADR 0004's guarantee is broken:\n" + "\n".join(leaked[:20])
    )
    assert report.assertions_cleared > 0, (
        "load_silver() cleared 0 assertions. Either the corpus was regenerated "
        "clean (good — update ADR 0004 and delete this assertion) or the clearing "
        "step stopped running (bad)."
    )
