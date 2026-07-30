"""Assertion detection: isNegated / isFamily / isHistorical for an extracted span.

Assertions are scored by Jaccard against the gold set, and the convention "both empty
means J = 1" makes an empty set the safe default: guessing an assertion on a concept
whose gold set is empty drops that concept from 1.0 to 0.0. So every rule here is
deliberately narrow, and anything unrecognised yields no assertion at all.

Two signals, both local to the span — a document-wide keyword scan would tag every
concept in the note from a single "tiền sử" anywhere in it:

  * the nearest section heading above the span  -> isHistorical / isFamily
  * a negation cue earlier on the span's line   -> isNegated

The cue tables mirror `scripts/gen_sample_data.py`, which measures them on gold and
uses them to label generated data. That script is deliberately standalone (stdlib
only, no `src/` imports), so the tables live in both files — change one, change both.

Known limitation, inherited on purpose: negation scope runs to the end of the clause
across commas, because negated symptoms are usually written as a list ("phủ nhận đau
ngực, khó thở, ho ra máu"). The cost is that an affirmed item following a negated one
on the same clause ("phủ nhận đau ngực, có ho khan") is wrongly tagged isNegated.
"""

import re

#: Only these three types carry assertions; the two lab types never do.
ASSERTION_TYPES = ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG")

#: Negation cues, measured on the 41 isNegated spans in gold: "phủ nhận" 18,
#: "không ..." 12, "không có" 2, "không phải"/"không kèm" 1 each.
NEG_CUES = ("Không ", "Không có ", "Không kèm ", "Không phải ",
            "Phủ nhận ", "Chưa ghi nhận ")

#: Section headings whose spans are all historical in gold. The abbreviated forms
#: matter for the handwritten-note genre, which writes headings clipped ("TS:").
HIST_SECTIONS = (
    "Tiền sử bệnh", "Thuốc trước khi nhập viện", "Các bệnh lý mạn tính",
    "Tiền sử bệnh nội khoa", "Các thủ thuật đã thực hiện",
    "Tiền sử", "TS bệnh", "TS nội khoa", "TS",
)

FAMILY_SECTIONS = ("Tiền sử gia đình", "TS gia đình", "TS GĐ", "Tiền sử GĐ")

LIST_MARKER = re.compile(r"^[\s>]*(?:(?:\d+|[a-zA-Z])[.)]\s*|[-–—•*+]\s*)+")

#: {2,40} rather than {3,40} so the clipped heading "TS:" is seen. The cost is that
#: measurement lines ("M: 82 ck/ph") also read as headings and hide the real heading
#: above them — but hiding it yields an EMPTY assertion set, i.e. a missing label
#: rather than a wrong one, which is the cheaper mistake under Jaccard.
HEADING = re.compile(r"(?m)^([^\n:]{2,40}):")


def assertions_at(text: str, offset: int, concept_type: str) -> list[str]:
    """Assertions for the span starting at `offset`, or [] if the type carries none."""
    if concept_type not in ASSERTION_TYPES:
        return []

    out = []

    heading = ""
    for match in HEADING.finditer(text[:offset]):
        heading = LIST_MARKER.sub("", match.group(1)).strip()
    if any(heading.startswith(h) for h in FAMILY_SECTIONS):
        out.append("isFamily")
    elif any(heading.startswith(h) for h in HIST_SECTIONS):
        out.append("isHistorical")

    line_start = text.rfind("\n", 0, offset) + 1
    before = text[line_start:offset].lower()
    if any(re.search(cue.strip().lower() + r"\b[^.;]{0,30}$", before) for cue in NEG_CUES):
        out.append("isNegated")

    return out
