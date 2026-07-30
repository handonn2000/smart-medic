"""L2 · `layout/` — document structure. Deterministic, regex only, no model.

    layout.parse(doc: Document) -> Layout

`Layout` exports exactly three things, and everything below uses one of them:

    ① boundary_priors : frozenset[int]   offsets a span may start/end at
    ② section(offset) : SectionNode      the enclosing section → assertion scope
    ③ unit(offset)    : LayoutUnit       the layout unit → offset anchor, KV pairing

Invariants: every offset here indexes `Document.raw`, never `.normalized`; and
`boundary_priors` is a prior for `decision/`, never a hard filter in `extract/`.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from ..io.document import Document
from .kv import LayoutUnit, boundary_priors, split_units
from .lines import HEADER_KINDS, Line, LineKind, split_lines
from .outline import ROOT_TITLE, SectionIndex, SectionNode, build_outline
from .rules import LayoutRules, default_rules

__all__ = [
    "Layout",
    "parse",
    "Line",
    "LineKind",
    "HEADER_KINDS",
    "LayoutUnit",
    "SectionNode",
    "LayoutRules",
    "ROOT_TITLE",
]


@dataclass(frozen=True)
class Layout:
    doc: Document
    lines: tuple[Line, ...]
    units: tuple[LayoutUnit, ...]
    root: SectionNode
    boundary_priors: frozenset[int]

    _sections: SectionIndex = field(repr=False, compare=False)
    _unit_starts: tuple[int, ...] = field(repr=False, compare=False)

    # ── ② the assertion scope ────────────────────────────────────────────────
    def section(self, offset: int) -> SectionNode:
        """Deepest section containing `offset`; the root if none does."""
        return self._sections(offset)

    # ── ③ the offset anchor ──────────────────────────────────────────────────
    def unit(self, offset: int) -> LayoutUnit | None:
        """The unit containing `offset`, or None (indent, marker, blank line)."""
        i = bisect_right(self._unit_starts, offset) - 1
        if i < 0:
            return None
        unit = self.units[i]
        return unit if unit.contains(offset) else None

    def line(self, offset: int) -> Line | None:
        starts = [ln.start for ln in self.lines]
        i = bisect_right(starts, offset) - 1
        if i < 0:
            return None
        ln = self.lines[i]
        return ln if offset < max(ln.eol, ln.start + 1) else None

    @property
    def header_lines(self) -> tuple[Line, ...]:
        return tuple(ln for ln in self.lines if ln.is_header)

    def counts(self) -> dict[str, int]:
        """Line-kind histogram — the diagnostic this layer is judged on."""
        out = {k.value: 0 for k in LineKind}
        for ln in self.lines:
            out[ln.kind.value] += 1
        return out


def parse(doc: Document, rules: LayoutRules | None = None) -> Layout:
    r = rules or default_rules()
    lines = split_lines(doc, r)
    root = build_outline(lines, len(doc.raw), r)
    units = split_units(doc, lines, r)
    return Layout(
        doc=doc,
        lines=lines,
        units=units,
        root=root,
        boundary_priors=boundary_priors(doc, units, r),
        _sections=SectionIndex(root),
        _unit_starts=tuple(u.start for u in units),
    )
