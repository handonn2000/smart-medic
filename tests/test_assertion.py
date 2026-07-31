"""L4a · assertion scope — the rules, and the band that stops them running away.

The economics this file is defending, derived from the leaderboard rather than
from our own corpus: submission A emitted `assertions: []` on every span and
still scored `J_assertion = 30.9496` against `text = 26.63`, which puts
`P(gold assertions empty | matched)` near 0.87. So roughly seven of every eight
matched entities score a free 1 for staying empty, and a flag placed on one of
those turns that 1 into a 0. Recall is worth having; precision is worth more.

Run:  pytest tests/test_assertion.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smart_medic.assertion import assertions_for, history_section, negation_cue_before  # noqa: E402
from smart_medic.decision import emit  # noqa: E402
from smart_medic.io.labels import ASSERTABLE_TYPES, LAB_TYPES  # noqa: E402


# ───────────────────────────── isNegated ─────────────────────────────
@pytest.mark.parametrize(
    "line, target, expected",
    [
        ("Không phù, không xuất huyết dưới da", "xuất huyết", True),
        ("Bụng mềm, không chướng", "chướng", True),
        ("Tim đều, T1T2 rõ tiếng van cơ học, không tiếng thổi", "tiếng thổi", True),
        ("Tiền sử: Không có viêm họng cấp", "viêm họng cấp", True),
        ("Không ghi nhận co giật", "co giật", True),
        # No cue at all.
        ("Bệnh nhân đau bụng quanh rốn", "đau bụng", False),
        # Cue present but too far away — a new clause has started.
        (
            "Không sốt, bệnh nhân hiện tại vẫn còn đau bụng nhiều về đêm",
            "đau bụng",
            False,
        ),
    ],
)
def test_negation_scope(line, target, expected):
    start = line.index(target)
    assert (negation_cue_before(line, start) is not None) is expected


def test_negation_does_not_reach_across_a_comma():
    """The rule that costs recall on purpose.

    Negated symptoms are often written as comma lists ("Không ghi nhận co giật,
    cứng đờ, cắn lưỡi" is three negated spans), and this rule catches only the
    first of them. Widening to reach the rest also reaches affirmed items after a
    clause boundary — measured on 20 annotated test documents, going from
    15-chars/no-comma to 20-chars/≤2-commas turns 0 false positives into 4 for
    the same net score. A false positive costs a point already held; a false
    negative costs a point already lost.
    """
    line = "Phủ nhận đau ngực, có ho khan"
    assert negation_cue_before(line, line.index("đau ngực")) is not None
    assert negation_cue_before(line, line.index("ho khan")) is None


def test_negation_stops_at_the_line_boundary():
    text = "Không sốt\nĐau bụng nhiều"
    assert negation_cue_before(text, text.index("Đau bụng")) is None


# ──────────────────────────── isHistorical ────────────────────────────
@pytest.mark.parametrize(
    "titles, expected",
    [
        (("<document>", "Tiền sử bệnh nội khoa"), True),
        (("<document>", "Tiền sử", "Các bệnh lý mạn tính"), True),
        (("<document>", "Thuốc trước khi nhập viện"), True),
        (("<document>", "- Tiền sử phẫu thuật / thủ thuật"), True),
        (("<document>", "Khám lâm sàng"), False),
        (("<document>",), False),
    ],
)
def test_history_headings(titles, expected):
    assert (history_section(titles) is not None) is expected


def test_present_illness_headings_are_not_history():
    """"Bệnh sử" reads like history and is not.

    In Vietnamese charting it is the story of the CURRENT admission — the
    symptoms that brought the patient in are present, not past. Measured on the
    annotated sample, treating it as history costs 9 false positives and gains
    nothing.
    """
    for title in ("Bệnh sử", "Lý do nhập viện", "Lịch sử bệnh hiện tại"):
        assert history_section(("<document>", title)) is None


def test_history_is_inherited_from_any_ancestor():
    """A bullet nested under a history heading is still history."""
    titles = ("<document>", "Tiền sử bệnh nội khoa", "Các bệnh mãn tính")
    assert history_section(titles) is not None


# ──────────────────────── type gate and ordering ────────────────────────
@pytest.mark.parametrize("etype", sorted(LAB_TYPES))
def test_lab_types_never_carry_an_assertion(etype):
    """The schema forbids it, and the schema is worth 11.59 points."""
    line = "Không có kết quả bất thường"
    assert assertions_for(line, line.index("kết quả"), etype, ("Tiền sử",)) == ()


@pytest.mark.parametrize("etype", sorted(ASSERTABLE_TYPES))
def test_assertable_types_can_carry_both(etype):
    line = "Không có tăng huyết áp"
    got = assertions_for(line, line.index("tăng huyết áp"), etype, ("Tiền sử",))
    assert got == ("isNegated", "isHistorical"), "order is fixed for a stable archive"


def test_no_signal_means_no_assertion():
    """The default is empty, because empty is what scores 1 seven times in eight."""
    line = "Bệnh nhân có tăng huyết áp"
    assert assertions_for(line, line.index("tăng huyết áp"), "CHẨN_ĐOÁN", ()) == ()


def test_isfamily_is_never_emitted():
    """3 of 718 annotated spans carry it — below the rate where a rule can help."""
    line = "Mẹ bệnh nhân bị đái tháo đường"
    got = assertions_for(
        line, line.index("đái tháo đường"), "CHẨN_ĐOÁN", ("Tiền sử gia đình",)
    )
    assert "isFamily" not in got


# ─────────────────────────── the rate tripwire ───────────────────────────
def _records(n, flagged):
    return [
        {"assertions": ["isNegated"] if i < flagged else [], "type": "CHẨN_ĐOÁN"}
        for i in range(n)
    ]


def test_rate_inside_the_band_is_silent():
    assert emit.assertion_rate_check(_records(1000, 130)) == ""


def test_rate_above_the_band_fires():
    """29.6% is the synthetic corpus's rate — the one we must not drift toward."""
    warning = emit.assertion_rate_check(_records(1000, 296))
    assert "ABOVE" in warning and "0.296" in warning


def test_rate_below_the_band_fires():
    """Silence is also a failure: it means the rules stopped firing."""
    assert "BELOW" in emit.assertion_rate_check(_records(1000, 5))


def test_empty_input_is_not_a_rate_violation():
    assert emit.assertion_rate_check([]) == ""
