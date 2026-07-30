"""L2 · the layout acceptance criteria, as regression tests.

Two numbers from the P0 acceptance table live here, so they stay true rather than
having been true once:

    ≥97/100 test files have a recognised `Nhãn:` header line
    0 cases of `4,7` split into two tokens

Plus the invariant that pays for the layer: `boundary_priors` must not exclude the
gold span edges it is supposed to help find. Measured on 162 files / 7435 spans,
never assumed.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic import layout  # noqa: E402
from smart_medic.io import Document, load_gold, load_test  # noqa: E402
from smart_medic.layout.lines import LineKind  # noqa: E402

#: Acceptance bar from .claude/prompts/p0_prompt.md
MIN_HEADER_FILES = 97
#: Measured coverage of gold span edges. Tight, so a regression is visible.
MIN_EDGE_COVERAGE = 0.995

#: `\d[.,]\d` — a decimal separator. No boundary may fall on either side of it.
DECIMAL = re.compile(r"\d[.,]\d")


@pytest.fixture(scope="module")
def parsed_test():
    return [(d, layout.parse(d)) for d in load_test()]


@pytest.fixture(scope="module")
def parsed_gold():
    return [(d, layout.parse(d)) for d in load_gold()]


# ───────────────────────── header recognition ─────────────────────────
def test_header_line_recognised_in_at_least_97_files(parsed_test):
    """A `Nhãn:` line is either a COLON_HEADER (no value) or a KV (with one)."""
    hits = [
        d.doc_id
        for d, lay in parsed_test
        if any(ln.kind in (LineKind.COLON_HEADER, LineKind.KV) for ln in lay.lines)
    ]
    assert len(hits) >= MIN_HEADER_FILES, (
        f"only {len(hits)}/100 test files have a recognised header line "
        f"(bar is {MIN_HEADER_FILES}); missing "
        f"{sorted(set(d.doc_id for d, _ in parsed_test) - set(hits), key=int)}"
    )


def test_header_detection_misses_nothing_a_loose_regex_finds(parsed_test):
    """Cross-check against an independent pattern, so the bar is not self-graded."""
    loose = re.compile(
        r"^[ \t]*(?:[-*+•·–—>][ \t]+|\(?\d{1,2}[.)][ \t]+)?[^\W\d_][^:\n]{0,58}?:",
        re.M,
    )
    missed = []
    for d, lay in parsed_test:
        found_by_us = any(
            ln.kind in (LineKind.COLON_HEADER, LineKind.KV) for ln in lay.lines
        )
        if loose.search(d.raw) and not found_by_us:
            missed.append(d.doc_id)
    assert not missed, f"the classifier missed a header the loose regex found: {missed}"


# ──────────────────────── the decimal-comma guard ────────────────────────
@pytest.mark.parametrize("corpus", ["parsed_test", "parsed_gold"])
def test_no_decimal_number_is_ever_split(corpus, request):
    """`4,7` is one token. Splitting it turns one lab result into two wrong spans."""
    bad: list[str] = []
    for d, lay in request.getfixturevalue(corpus):
        for m in DECIMAL.finditer(d.raw):
            sep = m.start() + 1  # the '.' or ',' itself
            if sep in lay.boundary_priors or sep + 1 in lay.boundary_priors:
                bad.append(f"{d.doc_id}: prior inside {d.raw[m.start():m.end()]!r}")
            for u in lay.units:
                if u.start in (sep, sep + 1) or u.end in (sep, sep + 1):
                    bad.append(f"{d.doc_id}: unit edge inside {d.raw[m.start():m.end()]!r}")
    assert not bad, f"{len(bad)} decimal number(s) split:\n  " + "\n  ".join(bad[:15])


HARD_LINES = [
    # (line, expected unit texts)
    (
        "        Cholesterol: 4,7 mmol/l, Triglycerid: 1,9mmol/l \n",
        ["Cholesterol: 4,7 mmol/l", "Triglycerid: 1,9mmol/l"],
    ),
    (
        "        Ure: 5,9 mmol/l; Creatinin: 89 micromol/l\n",
        ["Ure: 5,9 mmol/l", "Creatinin: 89 micromol/l"],
    ),
    (
        " Sinh hóa: CRP: 227.0 mg/L Creatinin : 46 µmol/L Kali +: 3.6 mmol/L\n",
        ["Sinh hóa:", "CRP: 227.0 mg/L", "Creatinin : 46 µmol/L", "Kali +: 3.6 mmol/L"],
    ),
    # a clock must NOT open a second pair
    ("    - Thời gian: khoảng 11:00 sáng\n", ["Thời gian: khoảng 11:00 sáng"]),
    # a lab name ending in a digit is not a clock
    ("Khí máu: Lactat: 0.8    HCO3: 32.09\n", ["Khí máu:", "Lactat: 0.8", "HCO3: 32.09"]),
    # a ratio value stays whole
    ("M: 82 ck/ph; HA: 160/ 80 mmHg \n", ["M: 82 ck/ph", "HA: 160/ 80 mmHg"]),
    # no colons at all: `;` still splits
    ("        BC 5,38 G/l; N 51,4%\n", ["BC 5,38 G/l", "N 51,4%"]),
]


@pytest.mark.parametrize("line,expected", HARD_LINES, ids=lambda v: None)
def test_hard_lines_split_exactly(line, expected):
    doc = Document(doc_id="case", raw=line)
    lay = layout.parse(doc)
    assert [u.text for u in lay.units] == expected


# ───────────────────────── offsets stay on raw ─────────────────────────
@pytest.mark.parametrize("corpus", ["parsed_test", "parsed_gold"])
def test_every_layout_offset_slices_back(corpus, request):
    for d, lay in request.getfixturevalue(corpus):
        for ln in lay.lines:
            assert d.raw[ln.start : ln.end] == ln.text
            assert ln.content_start >= ln.start
        for u in lay.units:
            assert d.raw[u.start : u.end] == u.text, f"{d.doc_id}: {u}"
            assert u.start < u.end
            if u.label_span:
                assert d.raw[u.label_span[0] : u.label_span[1]] == u.label


def test_nfd_document_units_are_not_normalised():
    """A layout offset must index `raw`, so an NFD line stays NFD in its units."""
    nfc = "Chẩn đoán: viêm phổi\n"
    doc = Document(doc_id="nfd", raw=unicodedata.normalize("NFD", nfc))
    lay = layout.parse(doc)
    assert [u.text for u in lay.units] == [doc.raw.rstrip("\n")]
    assert unicodedata.normalize("NFC", lay.units[0].label) == "Chẩn đoán"
    assert lay.units[0].text != nfc.rstrip("\n")  # raw, not normalised


# ────────────────── boundary_priors must not exclude gold ──────────────────
def test_boundary_priors_cover_gold_span_edges(parsed_gold):
    """Measured, not assumed — the layer README asks for exactly this number."""
    total = miss_start = miss_end = 0
    for d, lay in parsed_gold:
        for e in d.entities:
            start, end = e["position"]
            total += 1
            miss_start += start not in lay.boundary_priors
            miss_end += end not in lay.boundary_priors
    cov_start = 1 - miss_start / total
    cov_end = 1 - miss_end / total
    assert total > 7000, f"only {total} gold spans — corpus shrank?"
    assert cov_start >= MIN_EDGE_COVERAGE, (
        f"boundary_priors covers only {cov_start:.3%} of gold span STARTS "
        f"({miss_start}/{total} excluded)"
    )
    assert cov_end >= MIN_EDGE_COVERAGE, (
        f"boundary_priors covers only {cov_end:.3%} of gold span ENDS "
        f"({miss_end}/{total} excluded)"
    )


# ──────────────────────── the three exports ────────────────────────
def test_layout_exports_section_unit_and_priors(parsed_test):
    """`boundary_priors` · `section(offset)` · `unit(offset)` — exactly three things."""
    d, lay = parsed_test[41]  # 42.txt: numbered headers over indented bullet lists
    assert lay.boundary_priors and isinstance(lay.boundary_priors, frozenset)

    unit = lay.units[3]
    mid = (unit.start + unit.end) // 2
    assert lay.unit(mid) is unit
    assert lay.unit(0) is None or lay.unit(0).start == 0

    section = lay.section(mid)
    assert section.start <= mid < section.end
    assert section.path()[0] == "<document>"
    assert len(section.path()) >= 1


def test_indent_stack_builds_a_nested_outline():
    raw = (
        "1.  Tiền sử bệnh lý\n"
        "    Thuốc trước khi nhập viện\n"
        "    - tylenol\n"
        "2.  Tiền sử bệnh hiện tại\n"
        "    Lý do nhập viện: ho\n"
    )
    lay = layout.parse(Document(doc_id="outline", raw=raw))
    paths = [n.path() for n in lay.root.walk() if n.level >= 0]
    assert ("<document>", "Tiền sử bệnh lý") in paths
    assert ("<document>", "Tiền sử bệnh lý", "Thuốc trước khi nhập viện") in paths
    assert ("<document>", "Tiền sử bệnh hiện tại") in paths

    # the bullet inherits the sub-header's scope — this is the assertion scope
    tylenol = raw.index("tylenol")
    assert lay.section(tylenol).title == "Thuốc trước khi nhập viện"
    # and the section from file 2 does not leak into file 1's subtree
    ho = raw.index("ho\n")
    assert lay.section(ho).path()[1] == "Tiền sử bệnh hiện tại"
