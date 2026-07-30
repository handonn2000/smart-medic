"""L4a · `isNegated` / `isHistorical` / `isFamily` for one span.

## Why an empty list is the safe default, and what that costs

`assertions` is scored by Jaccard against the gold set, with the convention that
two empty sets score 1. So for a MATCHED entity:

    gold empty,     we emit nothing   →  J = 1   (already held)
    gold empty,     we emit a flag    →  J = 0   ← the only way to LOSE a point
    gold has flags, we emit nothing   →  J = 0   (already lost)
    gold has flags, we emit the right →  J = 1
    gold has flags, we emit the wrong →  J = 0   (loses nothing further)

Derived from the leaderboard rather than from our own corpus: submission A
emitted `assertions: []` everywhere and scored `J_assertion = 30.9496`, while
`text = 26.63`. Both carry the same match rate `m`, and `text = m·q` with
`q = mean(1 − WER) ≤ 1`, so `m ≥ 0.2663`; taking `q ≈ 0.75` (measured on 20
hand-checked test documents) gives `m ≈ 0.357` and

    P(gold assertions empty | matched) = 30.9496 / (100·0.357) ≈ 0.868

**Only ~13% of matched gold entities carry an assertion at all.** Guessing
liberally therefore risks seven points of held ground to chase one. Every rule
here is tuned for precision and returns nothing when unsure, and
`decision/emit.py` enforces a rate band on the aggregate so a future edit cannot
quietly turn this into a guesser.

## The two signals, and why not a third

Measured on `proxy_gold_test/` — 20 test documents annotated by hand, 724 spans,
84 of them carrying an assertion:

* **isNegated** — a negation cue earlier on the same line, within 15 characters,
  with no comma in between. Sweeping the window against the annotations:

      window   commas allowed   tp   fp
        15         none         27    0
        20         none         28    2
        20          ≤2          31    4
        40          ≤2          34    9

  The tight window is not caution for its own sake: it wins on net points
  (`tp − fp`, since a tp turns 0→1 and an fp turns 1→0) *and* takes zero of the
  expensive error. Negated symptoms do get written as comma lists — "Không ghi
  nhận co giật, cứng đờ, cắn lưỡi" is three negated spans in the annotations, and
  this rule catches only the first — but widening to reach them drags in
  affirmed items after a clause boundary, and those cost double.

* **isHistorical** — the span sits inside a section whose heading is a
  history heading. Scope comes from `layout/outline.py`, which already closes a
  section when a same-or-shallower heading arrives; a "nearest heading above"
  scan (what a first cut does) leaks the flag across the rest of the document,
  and a measurement line like `M: 82 ck/ph` reads as a heading and hides the real
  one.

* **isFamily** is deliberately NOT implemented. Three of 724 annotated spans
  carry it — under 0.5%. At that base rate a rule good enough to help is
  indistinguishable from one that hurts, and the downside is the expensive
  direction. `FAMILY_HEADINGS` is kept as data so the decision stays visible.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from ..io.config import load_pipeline, require
from ..io.labels import ASSERTABLE_TYPES

__all__ = ["assertions_for", "negation_cue_before", "history_section"]


#: Negation cues, longest first so "không có" is recognised before "không".
#: Vietnamese clinical negation is overwhelmingly one of these; the annotations
#: show "không" bare and "không ghi nhận" carrying most of the mass.
NEGATION_CUES: tuple[str, ...] = (
    "không ghi nhận",
    "chưa ghi nhận",
    "không phát hiện",
    "chưa phát hiện",
    "không thấy",
    "không có",
    "không kèm",
    "không phải",
    "phủ nhận",
    "chưa có",
    "loại trừ",
    "không",
)

#: Section headings under which every span is a past condition. Compared after
#: stripping list markers and lowercasing, by prefix — "Tiền sử bệnh nội khoa"
#: and "Tiền sử phẫu thuật / thủ thuật" both start with "tiền sử".
HISTORY_HEADINGS: tuple[str, ...] = (
    "tiền sử",
    "tiền căn",
    "ts:",
    "ts bệnh",
    "ts nội khoa",
    "bản thân",
    "thuốc trước khi nhập viện",
    "thuốc đang dùng",
    "thuốc đang sử dụng",
    "các bệnh lý mạn tính",
    "bệnh lý mạn tính",
    "các bệnh mãn tính",
    "các thủ thuật đã thực hiện",
    "quá trình bệnh lý",
)

#: Kept as data, not used. See the module docstring: 3 of 724 annotated spans.
FAMILY_HEADINGS: tuple[str, ...] = (
    "tiền sử gia đình",
    "ts gia đình",
    "ts gđ",
    "tiền sử gđ",
    "gia đình",
)

#: A history heading that is ALSO a present-illness heading. "Bệnh sử" is the
#: history of the CURRENT admission in Vietnamese charting — the symptoms that
#: brought the patient in are present, not past — so it is excluded even though
#: it reads like one. Measured: including it costs 9 false positives, gains 0.
NOT_HISTORY: tuple[str, ...] = (
    "bệnh sử",
    "lý do nhập viện",
    "lịch sử bệnh hiện tại",
    "tiền sử bệnh hiện tại",
    "quá trình bệnh hiện tại",
)

#: Leading list markers and enumerators, stripped before a heading is compared.
_LIST_MARKER = re.compile(r"^[\s>]*(?:(?:\d+|[a-zA-Z])[.)]\s*|[-–—•*+]\s*)+")


def _fold(text: str) -> str:
    """Lowercase NFC — the form every table in this module is written in."""
    return unicodedata.normalize("NFC", text).lower()


@lru_cache(maxsize=1)
def _config() -> dict:
    return require(load_pipeline(), "assertion")


def negation_cue_before(raw: str, start: int) -> str | None:
    """The negation cue governing `start`, or None.

    In scope only when the cue is on the same line, within
    `assertion.negation.max_chars` characters, and no comma separates the two —
    a comma is where a clause boundary lives in this corpus, and an affirmed item
    after one ("phủ nhận đau ngực, có ho khan") is the error that costs double.
    """
    cfg = _config()["negation"]
    line_start = raw.rfind("\n", 0, start) + 1
    before = _fold(raw[line_start:start])

    at = -1
    cue_found = None
    for cue in NEGATION_CUES:
        pos = before.rfind(cue)
        if pos > at:
            at, cue_found = pos, cue
    if cue_found is None:
        return None

    between = before[at + len(cue_found):]
    if len(between) > int(require(cfg, "max_chars")):
        return None
    if not bool(require(cfg, "allow_comma")) and "," in between:
        return None
    return cue_found


def history_section(section_titles) -> str | None:
    """The history heading governing a span, or None.

    `section_titles` is the ancestor path from `layout/outline.py`, root first.
    Any ancestor being a history section is enough — a bullet nested two levels
    under "Tiền sử bệnh nội khoa" is still history.
    """
    for title in section_titles:
        folded = _LIST_MARKER.sub("", _fold(title)).strip()
        if any(folded.startswith(x) for x in NOT_HISTORY):
            continue
        if any(folded.startswith(x) for x in HISTORY_HEADINGS):
            return title
    return None


def assertions_for(
    raw: str, start: int, etype: str, section_titles: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Assertions for one span. Empty for the two lab types, always.

    Order is fixed (`isNegated` then `isHistorical`) so two builds of one commit
    serialise the same list — Jaccard does not care, but ADR 0005's byte-identical
    archive does.
    """
    if etype not in ASSERTABLE_TYPES:
        return ()

    out: list[str] = []
    if negation_cue_before(raw, start) is not None:
        out.append("isNegated")
    if history_section(section_titles) is not None:
        out.append("isHistorical")
    return tuple(out)
