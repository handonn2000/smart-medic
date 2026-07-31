"""L3 lane R · redaction runs.

The lane is four lines of regex, so the tests that matter are not about the
regex — they are about the two claims that justify shipping it at all:

1. the span boundary matches what the annotators drew (7/7 in proxy_gold_test),
2. a redacted span reaches the output with empty assertions AND empty
   candidates, which is the whole reason it scores 1.0 on two of three terms.

Run:  pytest tests/test_redacted.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.decision import emit  # noqa: E402
from smart_medic.extract import recall_floor, redacted  # noqa: E402
from smart_medic.io.document import Document  # noqa: E402
from smart_medic.layout.kv import split_units  # noqa: E402
from smart_medic.layout.lines import split_lines  # noqa: E402

TEST_DIR = ROOT / "data" / "test"
PROXY = ROOT / "data" / "proxy_gold_test"


@pytest.fixture(autouse=True)
def lane_enabled(monkeypatch: pytest.MonkeyPatch):
    """Run every test in this file with the lane ON, whatever the repo default.

    `extract.recall_floor.redacted.enabled` ships `false` so a clean checkout
    rebuilds the archive that is actually queued for submission. That is a
    release decision, not a statement about whether the lane works — these tests
    are about whether it works, so they set the flag themselves. Without this,
    shipping the flag off would silently turn the whole file green-by-vacuum.
    """
    from smart_medic.io import config

    # Hold the real (cached) callable: monkeypatch replaces the module attribute
    # with a plain lambda, which has no `cache_clear`, so teardown has to reach
    # through this reference rather than through `config.load_pipeline`.
    real_loader = config.load_pipeline
    real_loader.cache_clear()
    loaded = real_loader()
    loaded["extract"]["recall_floor"]["redacted"]["enabled"] = True
    monkeypatch.setattr(config, "load_pipeline", lambda: loaded)
    for module in (redacted, emit):
        if hasattr(module, "load_pipeline"):
            monkeypatch.setattr(module, "load_pipeline", lambda: loaded)
    yield
    # The mutation above edited the CACHED dict in place, so the next test file
    # to read config would inherit `enabled: true`. Drop the cache.
    real_loader.cache_clear()


def _raw(doc_id: str) -> str:
    with (TEST_DIR / f"{doc_id}.txt").open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _doc(doc_id: str) -> Document:
    return Document(doc_id=doc_id, raw=_raw(doc_id))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("dùng ********** mỗi tối", ["**********"]),
        ("kem *** hai lần", ["***"]),
        # One and two asterisks are a footnote marker and markdown emphasis.
        ("xem chú thích * ở dưới", []),
        ("**in đậm** không phải thuốc", []),
        # Glued to a word: a typo, not a mask.
        ("aspirin*** loại này", []),
        ("***aspirin loại này", []),
        # Two runs on one line are two spans.
        ("dùng ****** rồi ********", ["******", "********"]),
    ],
)
def test_run_detection(text: str, expected: list[str]) -> None:
    spans = redacted.find_redacted(Document(doc_id="t", raw=text))
    assert [text[s.start : s.end] for s in spans] == expected


def test_offsets_index_raw_exactly() -> None:
    """Every emitted span must slice back to a pure run of asterisks."""
    checked = 0
    for path in sorted(TEST_DIR.glob("*.txt")):
        doc = _doc(path.stem)
        for span in redacted.find_redacted(doc):
            sliced = doc.raw[span.start : span.end]
            assert set(sliced) == {"*"}, f"{path.stem}: sliced {sliced!r}"
            checked += 1
    assert checked >= 90, f"only {checked} runs found — has data/test changed?"


def test_boundary_matches_the_annotators() -> None:
    """The gold span is the WHOLE run, no surrounding whitespace.

    This is the claim the lane rests on. It is checked against every redaction
    the hand annotators labelled, not a fixture, so it fails if the convention
    turns out to be different from what 7/7 showed.
    """
    if not PROXY.is_dir():
        pytest.skip("proxy_gold_test/ not present")

    gold: set[tuple[str, int, int]] = set()
    for path in sorted(PROXY.glob("*.json")):
        for entity in json.loads(path.read_text(encoding="utf-8")):
            if entity["text"] and set(entity["text"]) <= {"*"}:
                gold.add((path.stem, *entity["position"]))
    assert gold, "no redactions in the proxy gold — this test proves nothing"

    predicted = {
        (path.stem, span.start, span.end)
        for path in sorted(PROXY.glob("*.json"))
        for span in redacted.find_redacted(_doc(path.stem))
    }
    assert gold <= predicted, f"missed: {sorted(gold - predicted)}"
    # And no extras inside those same documents — the lane must not invent runs
    # the annotators skipped.
    in_scope = {p for p, _, _ in gold} | {p.stem for p in PROXY.glob("*.json")}
    extra = {t for t in predicted if t[0] in in_scope} - gold
    assert not extra, f"spurious redaction spans: {sorted(extra)}"


def test_redacted_spans_reach_output_empty() -> None:
    """Empty assertions and empty candidates — the reason the lane pays.

    Driven through `finalize`, because the emptying happens there: the ordinary
    assertion rules would otherwise flag 3 of the 99 (one Tiều sử heading, two
    from an interrogative "không:" misread as negation).
    """
    seen = 0
    for doc_id in ("7", "9", "24", "40", "41"):
        doc = _doc(doc_id)
        lines = split_lines(doc)
        spans = recall_floor(doc, lines, split_units(doc, lines))
        for record in emit.finalize(doc, spans, emit.select_threshold(30.0)):
            if not (record["text"] and set(record["text"]) <= {"*"}):
                continue
            seen += 1
            assert record["type"] == "THUỐC", record
            assert record["assertions"] == [], record
            assert record["candidates"] == [], record
    assert seen >= 5, f"only {seen} redacted spans reached finalize"


def test_lane_can_be_switched_off() -> None:
    """The gold convention is a one-submission question, so the flag is real."""
    from smart_medic.io.config import load_pipeline, require

    cfg = require(load_pipeline(), "extract.recall_floor.redacted")
    assert "enabled" in cfg, "the experiment needs a toggle"
    assert cfg["type"] == "THUỐC"
    assert int(cfg["min_asterisks"]) >= 3


def test_no_other_lane_claims_these_offsets() -> None:
    """Merge priority must let the redaction lane win its own spans.

    `redacted` sits first in merge_priority; if a later lane ever starts
    proposing overlapping spans and wins, the emitted text would stop being a
    pure run of asterisks — which `test_offsets_index_raw_exactly` would not
    catch, since it only inspects the lane in isolation.
    """
    doc = _doc("41")
    lane = {(s.start, s.end) for s in redacted.find_redacted(doc)}
    assert lane, "document 41 has redactions"

    lines = split_lines(doc)
    merged = recall_floor(doc, lines, split_units(doc, lines))
    survived = {(s.start, s.end) for s in merged if s.source == "redacted"}
    assert lane <= survived, f"merge dropped {sorted(lane - survived)}"
