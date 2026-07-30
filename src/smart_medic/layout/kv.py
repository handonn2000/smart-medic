"""L2 · splitting a line into layout units, and the boundary priors that follow.

Three splits, in this order:

1. **`;` unconditionally.**   `Ure: 5,9 mmol/l; Creatinin: 89 micromol/l`
2. **`,` only when a lab name follows.**
   `Cholesterol: 4,7 mmol/l, Triglycerid: 1,9mmol/l` splits once — after
   `mmol/l`, never inside `4,7`. **`4,7` is a decimal comma.** Splitting it is a
   measured defect, not a cosmetic one: it turns one `KẾT_QUẢ_XÉT_NGHIỆM` into two
   wrong spans, and boundary errors cost 6.95 points on the leverage map.
3. **A second `label: value` pair separated only by whitespace.**
   `CRP: 227.0 mg/L Creatinin : 46 µmol/L Kali +: 3.6 mmol/L` → three units.

`boundary_priors` is then the set of offsets a span may legally start or end at:
unit edges plus token edges *inside* units. Because units begin after the
enumerator, the offsets of `- ` and `1.  ` are simply not in the set — which is
what stops `- viêm phổi` and `Chẩn đoán: viêm phổi` from being emitted whole.
The token pattern tries the numeric alternative first, so no offset ever falls
between the `4` and the `,` of `4,7`.

These are PRIORS for `decision/`, not a hard filter in `extract/`.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from ..io.document import Document
from .lines import Line, LineKind, is_clock, label_match
from .rules import LayoutRules, default_rules

__all__ = ["LayoutUnit", "split_units", "boundary_priors"]


@dataclass(frozen=True)
class LayoutUnit:
    """One `label: value` pair, one bullet item, or one run of prose.

    All offsets index `Document.raw`.
    """

    index: int
    line_index: int
    start: int
    end: int
    kind: LineKind
    label_span: tuple[int, int] | None = None
    value_span: tuple[int, int] | None = None
    _raw: str = dc_field(default="", repr=False, compare=False)

    @property
    def text(self) -> str:
        return self._raw[self.start : self.end]

    @property
    def label(self) -> str:
        if self.label_span is None:
            return ""
        return self._raw[self.label_span[0] : self.label_span[1]]

    @property
    def value(self) -> str:
        if self.value_span is None:
            return ""
        return self._raw[self.value_span[0] : self.value_span[1]]

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end


def _trim(raw: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span past surrounding whitespace, keeping raw offsets exact."""
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1
    return start, end


def _split_on_char(
    raw: str, spans: list[tuple[int, int]], ch: str
) -> list[tuple[int, int]]:
    """Unconditional split on a single character, dropping the separator."""
    out: list[tuple[int, int]] = []
    for start, end in spans:
        cursor = start
        i = raw.find(ch, start, end)
        while i != -1:
            out.append((cursor, i))
            cursor = i + 1
            i = raw.find(ch, cursor, end)
        out.append((cursor, end))
    return out


def _split_on_lab_comma(
    raw: str, spans: list[tuple[int, int]], r: LayoutRules
) -> list[tuple[int, int]]:
    """Split on `,` only where the text that follows starts a new lab item.

    This is the decimal-comma guard. `4,7` is followed by ` mmol/l`, which has no
    `name:` shape, so it is never a split point.
    """
    out: list[tuple[int, int]] = []
    for start, end in spans:
        cursor = start
        i = raw.find(r.comma, start, end)
        while i != -1:
            if not r.comma_requires_lab_name or r.lab_name.match(raw, i + 1, end):
                out.append((cursor, i))
                cursor = i + 1
            i = raw.find(r.comma, i + 1, end)
        out.append((cursor, end))
    return out


def _split_inline_kv(
    raw: str, spans: list[tuple[int, int]], r: LayoutRules
) -> list[tuple[int, int]]:
    """Split where a second `label: value` pair opens with only whitespace before it.

    A candidate must sit at least `inline_kv_min_gap` characters into the segment
    (otherwise it is the segment's own label) and must not be a clock or a ratio.
    """
    out: list[tuple[int, int]] = []
    for start, end in spans:
        cuts: list[int] = []
        for m in r.inline_kv.finditer(raw, start, end):
            at = m.start()
            if at - start < r.inline_kv_min_gap:
                continue
            if at > start and not raw[at - 1].isspace():
                continue
            if is_clock(raw, raw.find(":", m.start(), m.end()), r):
                continue
            cuts.append(at)
        cursor = start
        for at in cuts:
            out.append((cursor, at))
            cursor = at
        out.append((cursor, end))
    return out


def _label_value(
    raw: str, start: int, end: int, r: LayoutRules
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    m = label_match(raw, start, end, r)
    if m is None:
        return None, None
    label = _trim(raw, start, m.end() - 1)
    value = _trim(raw, m.end(), end)
    return label, (value if value[0] < value[1] else None)


def split_units(
    doc: Document, lines: tuple[Line, ...], rules: LayoutRules | None = None
) -> tuple[LayoutUnit, ...]:
    """One or more units per non-blank line. Never crosses a line boundary."""
    r = rules or default_rules()
    raw = doc.raw
    units: list[LayoutUnit] = []

    for line in lines:
        if line.kind is LineKind.BLANK:
            continue
        spans = [(line.content_start, line.end)]
        spans = _split_on_char(raw, spans, r.semicolon)
        spans = _split_on_lab_comma(raw, spans, r)
        spans = _split_inline_kv(raw, spans, r)

        for span in spans:
            start, end = _trim(raw, *span)
            if start >= end:
                continue
            label_span, value_span = _label_value(raw, start, end, r)
            units.append(
                LayoutUnit(
                    index=len(units),
                    line_index=line.index,
                    start=start,
                    end=end,
                    kind=line.kind,
                    label_span=label_span,
                    value_span=value_span,
                    _raw=raw,
                )
            )
    return tuple(units)


def boundary_priors(
    doc: Document, units: tuple[LayoutUnit, ...], rules: LayoutRules | None = None
) -> frozenset[int]:
    """Offsets a span may start or end at. A hint for `decision/`, not a filter."""
    r = rules or default_rules()
    raw = doc.raw
    priors: set[int] = set()
    for unit in units:
        priors.add(unit.start)
        priors.add(unit.end)
        if unit.value_span is not None:
            priors.update(unit.value_span)
        for pattern in (r.token, r.token_prefix, r.token_suffix):
            for m in pattern.finditer(raw, unit.start, unit.end):
                priors.add(m.start())
                priors.add(m.end())
    return frozenset(priors)
