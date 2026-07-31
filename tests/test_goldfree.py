"""Checks that need no reference labels.

Everything else in this suite either compares against `data/proxy_gold_test/`
(one inferred annotation pass) or waits for a leaderboard attempt. These
checks are properties of the output alone, so they run on every build and
cost nothing.

They do not measure accuracy. They measure self-consistency, which is a strict
lower bound on error: a pipeline that labels the same string two ways in one
document is wrong at least once, and you learn that without knowing which way
is right.

Run:  pytest tests/test_goldfree.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "gold"))

import goldfree  # noqa: E402

TEST_DIR = ROOT / "data" / "test"
OUT_DIR = ROOT / "data" / "output"


def _raw(doc_id: str) -> str:
    with (TEST_DIR / f"{doc_id}.txt").open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _shipped() -> dict[str, list[dict]]:
    if not OUT_DIR.is_dir():
        return {}
    out = {}
    for path in OUT_DIR.glob("*.json"):
        if re.fullmatch(r"\d+", path.stem):
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def test_self_consistency_flags_contradictions() -> None:
    """A surface labelled two ways in one document is an error either way."""
    records = [
        {"text": "protein", "type": "THUỐC", "position": [0, 7]},
        {"text": "protein", "type": "TÊN_XÉT_NGHIỆM", "position": [20, 27]},
    ]
    report = goldfree.self_consistency("protein ... protein", records)
    assert report["n_type_conflicts"] == 1
    assert report["type_conflicts"]["protein"] == {
        "THUỐC": 1,
        "TÊN_XÉT_NGHIỆM": 1,
    }


def test_self_consistency_flags_coverage_gaps() -> None:
    """Labelling 1 of 3 occurrences of the same surface is an inconsistency."""
    text = "đau bụng nhiều, sau đó đau bụng lại, rồi đau bụng dữ dội"
    records = [{"text": "đau bụng", "type": "TRIỆU_CHỨNG", "position": [0, 8]}]
    report = goldfree.self_consistency(text, records)
    assert report["n_coverage_gaps"] == 1
    gap = report["coverage_gaps"][0]
    assert (gap["labelled"], gap["occurrences"]) == (1, 3)


def test_swappable_rejects_partial_product_names() -> None:
    """"mucinex" inside "mucinex d" must not be substituted.

    This guard exists because the first run of the metamorphic suite reported a
    false positive from exactly this case: swapping the 7 characters of
    "mucinex" in "- mucinex d" produces "thuốc chống dị ứng d", which the
    pipeline then labels correctly as a single span. The test was wrong, not
    the system.
    """
    text = "    - tylenol\n    - mucinex d\n    - thỉnh thoảng"
    span = {"text": "mucinex", "type": "THUỐC", "position": [20, 27]}
    assert text[20:27] == "mucinex"
    assert not goldfree.swappable(text, span)

    clean = "bệnh nhân dùng mucinex mỗi sáng"
    span2 = {"text": "mucinex", "type": "THUỐC", "position": [15, 22]}
    assert clean[15:22] == "mucinex"
    assert goldfree.swappable(clean, span2)


def test_metamorphic_swap_produces_exact_expected_span() -> None:
    """The expected label after substitution is exact by construction."""
    text = "bệnh nhân dùng aspirin mỗi tối"
    span = {"text": "aspirin", "type": "THUỐC", "position": [15, 22]}
    mutated, expected = goldfree.metamorphic_swap(text, span, "metformin")
    assert mutated == "bệnh nhân dùng metformin mỗi tối"
    assert expected == {
        "text": "metformin",
        "type": "THUỐC",
        "position": [15, 24],
    }
    assert mutated[15:24] == "metformin"


@pytest.mark.skipif(not OUT_DIR.is_dir(), reason="no build in data/output")
def test_shipped_build_has_no_span_ending_mid_word() -> None:
    """A span whose last character is a letter followed by a letter is broken."""
    offenders = []
    for doc_id, records in _shipped().items():
        text = _raw(doc_id)
        for r in records:
            end = r["position"][1]
            if end < len(text) and text[end - 1].isalpha() and text[end].isalpha():
                offenders.append((doc_id, r["text"], text[end : end + 8]))
    assert not offenders, f"{len(offenders)} spans end mid-word: {offenders[:5]}"


@pytest.mark.skipif(not OUT_DIR.is_dir(), reason="no build in data/output")
def test_shipped_build_type_conflicts_stay_bounded() -> None:
    """Same surface, same document, two labels — a floor on the error count.

    The shipped E build has 8. That is small enough to ship and large enough to
    be worth watching, so this pins it: a change that doubles it has almost
    certainly made the type decision worse, and this says so before a
    leaderboard attempt is spent finding out.
    """
    shipped = _shipped()
    if not shipped:
        pytest.skip("empty build")
    total = sum(
        goldfree.self_consistency(_raw(k), v)["n_type_conflicts"]
        for k, v in shipped.items()
    )
    assert total <= 12, (
        f"{total} same-surface type conflicts across the corpus (was 8 on the "
        f"shipped E build) — the type decision has regressed"
    )
