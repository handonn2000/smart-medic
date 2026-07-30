"""L3 · lane R · the lexicon lane and the guards that keep it from over-firing.

Recall bought with spurious spans is not recall: +10% spurious costs 6.10 points
on gold. Every test here is either "the lane finds the thing the gazetteer
cannot" or "the lane does not invent a span".

Run:  pytest tests/test_lexicon.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smart_medic.extract import lexicon, tokenize  # noqa: E402
from smart_medic.io.config import load_pipeline, require  # noqa: E402
from smart_medic.io.document import Document  # noqa: E402
from smart_medic.io.labels import TYPES  # noqa: E402


def _spans(raw: str):
    doc = Document(doc_id="t", raw=raw)
    return lexicon.spans(doc, tokenize(doc)), doc


def _surfaces(raw: str):
    found, doc = _spans(raw)
    return [(s.text(doc), s.argmax_type()) for s in found]


# ─────────────────────────── the resource itself ───────────────────────────
def test_lexicon_loads_and_is_not_empty():
    entries = lexicon.load_lexicon()
    assert len(entries) > 100, f"only {len(entries)} entries — did the YAML load?"


def test_every_entry_carries_a_legal_type():
    for tokens, etype in lexicon.load_lexicon():
        assert etype in TYPES, f"{tokens} has type {etype!r}"


def test_entries_are_sorted_longest_first():
    """Longest-first is what makes 'đau bụng' beat 'đau' in one pass."""
    widths = [len(tokens) for tokens, _ in lexicon.load_lexicon()]
    assert widths == sorted(widths, reverse=True)


def test_entries_are_normalised_lowercase():
    import unicodedata

    for tokens, _ in lexicon.load_lexicon():
        for tok in tokens:
            assert tok == unicodedata.normalize("NFC", tok).lower(), (
                f"{tok!r} is not folded — matching compares against folded text, "
                f"so this entry can never fire"
            )


# ──────────────────────── what the gazetteer misses ────────────────────────
@pytest.mark.parametrize(
    "raw, surface, etype",
    [
        # Drug CLASSES: no RxNorm ingredient row exists for these.
        ("Bệnh nhân đang dùng thuốc lợi tiểu", "thuốc lợi tiểu", "THUỐC"),
        ("đã dùng kháng sinh 5 ngày", "kháng sinh", "THUỐC"),
        ("dị ứng NSAIDs", "NSAIDs", "THUỐC"),
        # Lay vitamin names: RxNorm says "cyanocobalamin".
        ("tiêm B12 hàng tháng", "B12", "THUỐC"),
        # Short lay symptom words: 73 of 134 missed symptom spans were ≤2 words.
        ("Cháu bị ngứa nhiều về đêm", "ngứa", "TRIỆU_CHỨNG"),
        # Longest match wins: "nổi mề đay" is also an entry, and it is the better
        # span, so this asserts the longer one rather than the bare noun.
        ("nổi mề đay khắp người", "nổi mề đay", "TRIỆU_CHỨNG"),
        ("tiền sử mề đay", "mề đay", "TRIỆU_CHỨNG"),
        ("thấy hồi hộp đánh trống ngực", "hồi hộp", "TRIỆU_CHỨNG"),
    ],
)
def test_finds_what_the_gazetteer_cannot(raw, surface, etype):
    assert (surface, etype) in _surfaces(raw)


def test_offsets_index_raw_exactly():
    """The invariant the whole project rests on — a 1-char shift scores 0.00."""
    raw = "Bệnh nhân ho khan, ngứa họng, dùng kháng sinh"
    found, doc = _spans(raw)
    assert found, "no spans on a line with three lexicon terms"
    for s in found:
        assert raw[s.start : s.end] == s.text(doc)


# ──────────────────────────── the guards ────────────────────────────
def test_longest_match_wins():
    """'đau bụng' and 'đau' both match; only one span may survive."""
    surfaces = [t for t, _ in _surfaces("Cháu bị đau bụng từ hôm qua")]
    assert "đau bụng" in surfaces
    assert "đau" not in surfaces


def test_no_overlapping_spans_within_the_lane():
    found, _ = _spans("đau bụng, buồn nôn, mệt mỏi, khó thở, ngứa, ho khan")
    ordered = sorted(found, key=lambda s: s.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start, f"[{a.start},{a.end}) overlaps [{b.start},{b.end})"


def test_a_phrase_does_not_match_across_a_sentence_boundary():
    """Without this guard every two-word entry matches across punctuation."""
    assert "đau bụng" not in [t for t, _ in _surfaces("Hết đau. Bụng mềm.")]


def test_matching_is_on_token_boundaries():
    """A substring inside a longer word is not a hit."""
    assert "ho" not in [t for t, _ in _surfaces("Bệnh nhân bị hoa mắt chóng mặt")]


def test_lane_can_be_switched_off():
    assert isinstance(
        require(load_pipeline(), "extract.recall_floor.lexicon.enabled"), bool
    )


def test_lane_score_is_below_every_gazetteer_source_and_above_the_gate():
    """This lane knows a type but no code, so the gazetteer must win a tie.

    It still has to clear the emit threshold, or the entries would be dead
    weight — a lane whose spans are all gated away is a lane that does nothing.
    """
    cfg = load_pipeline()
    score = float(require(cfg, "extract.recall_floor.lexicon.score"))
    gaz = require(cfg, "extract.recall_floor.aho.source_score")
    lowest_gate = min(
        float(row["p"]) for row in require(cfg, "decision.emit_threshold")
    )
    assert score < min(float(v) for v in gaz.values())
    assert score > lowest_gate, (
        f"lexicon score {score} is at or below the loosest emit threshold "
        f"{lowest_gate} — every span this lane proposes would be discarded"
    )


def test_lexicon_is_last_in_merge_priority():
    order = require(load_pipeline(), "extract.recall_floor.merge_priority")
    assert order[-1] == "lexicon"


def test_unknown_yaml_section_is_an_error(tmp_path):
    """A typo in a section name must not silently drop its entries."""
    from smart_medic.io.config import ConfigError

    bad = tmp_path / "lex.yaml"
    bad.write_text("symptomz:\n  - ngứa\n", encoding="utf-8")
    lexicon.load_lexicon.cache_clear()
    try:
        with pytest.raises(ConfigError, match="unknown section"):
            lexicon.load_lexicon(str(bad))
    finally:
        lexicon.load_lexicon.cache_clear()
