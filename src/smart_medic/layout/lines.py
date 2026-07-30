"""L2 · line classification. Five kinds, decided by regex, no model.

The shape of the data justifies this layer: 96% of the corpus is list-structured,
97/100 test files carry a header line, 94/100 carry a `TÊN: giá trị` line.

    NUM_HEADER     "1.  Tiền sử bệnh lý"        enumerator, no value
    COLON_HEADER   "Triệu chứng hiện tại:"      label, colon, nothing after
    KV             "Cholesterol: 4,7 mmol/l"    label, colon, a value
    BULLET         "- ho khan"                  bullet, no label
    PROSE          free text
    BLANK          whitespace only

Every offset on a `Line` indexes `Document.raw`. Lines are split on `\\r\\n`, `\\r`
and `\\n` explicitly rather than with `str.splitlines()`, which also breaks on
`\\v`, `\\f` and `U+2028` — characters the organisers' scorer will read as ordinary
text, so treating them as line ends here would put our offsets in a different
space from theirs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum

from ..io.document import Document
from .rules import LayoutRules, default_rules

__all__ = ["LineKind", "Line", "split_lines", "HEADER_KINDS", "label_match", "is_clock"]

_EOL = re.compile(r"\r\n|\r|\n")


class LineKind(str, Enum):
    BLANK = "BLANK"
    NUM_HEADER = "NUM_HEADER"
    COLON_HEADER = "COLON_HEADER"
    KV = "KV"
    BULLET = "BULLET"
    PROSE = "PROSE"

    def __str__(self) -> str:  # readable in diagnostics
        return self.value


#: The two kinds that name a section on their own.
HEADER_KINDS = frozenset({LineKind.NUM_HEADER, LineKind.COLON_HEADER})


@dataclass(frozen=True)
class Line:
    """One physical line. All offsets index `Document.raw`."""

    index: int
    start: int              # first character of the line, indent included
    end: int                # one past the last character, newline EXCLUDED
    eol: int                # one past the line terminator
    kind: LineKind
    indent: int             # leading whitespace in visual columns
    level: int              # index into rules.indent_levels
    content_start: int      # one past the enumerator/bullet marker
    label_end: int | None   # one past the ':' — KV and COLON_HEADER only
    value_start: int | None # first non-space of the value — KV only

    @property
    def text(self) -> str:
        return self._raw[self.start : self.end]

    @property
    def content(self) -> str:
        return self._raw[self.content_start : self.end]

    @property
    def label(self) -> str:
        if self.label_end is None:
            return ""
        return self._raw[self.content_start : self.label_end - 1].strip()

    @property
    def is_header(self) -> bool:
        return self.kind in HEADER_KINDS

    # `_raw` is attached by split_lines; excluded from repr and equality so a
    # 40kB document never lands in a traceback.
    _raw: str = dc_field(default="", repr=False, compare=False)


def _indent_width(text: str, tab_width: int) -> tuple[int, int]:
    """Return `(visual_columns, characters_consumed)` of the leading whitespace."""
    cols = chars = 0
    for ch in text:
        if ch == " ":
            cols += 1
        elif ch == "\t":
            cols += tab_width - (cols % tab_width)
        else:
            break
        chars += 1
    return cols, chars


def is_clock(raw: str, colon: int, rules: LayoutRules) -> bool:
    """True if the colon at `colon` is the middle of a clock time, not a KV colon.

    Checked against the full `raw` with a positional window rather than a sliced
    substring: the pattern's lookbehind needs the real preceding character to tell
    `khoảng 11:00` (an hour) from `HCO3: 32.09` (a lab name ending in a digit).
    Python's `re` lets a lookbehind read behind `pos`, so this is exact.
    """
    lo = max(0, colon - rules.kv_clock_window)
    hi = min(len(raw), colon + rules.kv_clock_window + 1)
    m = rules.kv_time_like.search(raw, lo, hi)
    return m is not None and m.start() <= colon < m.end()


def label_match(
    raw: str, start: int, end: int, rules: LayoutRules
) -> re.Match | None:
    """Match `label:` at `raw[start:]`, bounded by `end`, rejecting clock times.

    `re.match(raw, pos, end)` anchors at `pos` on its own — which is why the
    configured pattern carries no `^`. A `^` would look for the real start of the
    string and never fire here.
    """
    m = rules.kv_label.match(raw, start, end)
    if m is None:
        return None
    if len(m.group("label")) > rules.kv_label_max_chars:
        return None
    if is_clock(raw, m.end() - 1, rules):
        return None
    return m


def split_lines(doc: Document, rules: LayoutRules | None = None) -> tuple[Line, ...]:
    """Split and classify. Offsets are on `doc.raw`, tolerance 0."""
    r = rules or default_rules()
    raw = doc.raw
    lines: list[Line] = []

    pos = 0
    index = 0
    n = len(raw)
    while pos <= n:
        m = _EOL.search(raw, pos)
        end = m.start() if m else n
        eol = m.end() if m else n
        lines.append(_classify(raw, index, pos, end, eol, r))
        if not m:
            break
        pos = eol
        index += 1
        if pos == n:  # a trailing newline does not open a further line
            break
    return tuple(lines)


def _classify(
    raw: str, index: int, start: int, end: int, eol: int, r: LayoutRules
) -> Line:
    text = raw[start:end]
    indent, indent_chars = _indent_width(text, r.tab_width)
    level = r.level_of(indent)

    body = text[indent_chars:]
    if not body.strip():
        return Line(
            index=index,
            start=start,
            end=end,
            eol=eol,
            kind=LineKind.BLANK,
            indent=indent,
            level=level,
            content_start=end,
            label_end=None,
            value_start=None,
            _raw=raw,
        )

    # strip exactly one enumerator or bullet marker, and remember which
    numeric = r.marker_numeric.match(text)
    bullet = None if numeric else r.marker_bullet.match(text)
    marker = numeric or bullet
    content_start = start + (marker.end() if marker else indent_chars)

    label = label_match(raw, content_start, end, r)
    if label is not None:
        label_end = label.end()
        tail = raw[label_end:end]
        if not tail.strip():
            kind, value_start = LineKind.COLON_HEADER, None
        else:
            kind = LineKind.KV
            value_start = label_end + (len(tail) - len(tail.lstrip()))
    else:
        label_end = value_start = None
        if numeric:
            kind = LineKind.NUM_HEADER
        elif bullet:
            kind = LineKind.BULLET
        else:
            kind = LineKind.PROSE

    return Line(
        index=index,
        start=start,
        end=end,
        eol=eol,
        kind=kind,
        indent=indent,
        level=level,
        content_start=content_start,
        label_end=label_end,
        value_start=value_start,
        _raw=raw,
    )
