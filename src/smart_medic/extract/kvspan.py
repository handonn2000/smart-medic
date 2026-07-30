"""L3 · lane R · the generic `TÊN: giá trị` pair, typed by its label.

`aho.py` finds names it has seen; this finds the ones it has not. `Chẩn đoán:
viêm phổi lan toả hai bên` is a diagnosis whether or not that exact string is in
ICD-10, and the section label is the evidence for the type.

## Why this lane is deliberately small

Measured on 162 gold files: only **6.7%** of the 7,435 gold spans coincide
exactly with a layout unit's value, a unit's full extent, or a bullet's content.
Gold annotates *inside* the bullet — `- Bệnh phổi tắc nghẽn mạn tính (COPD)` is
not one span. So emitting whole units would buy almost nothing on gold while
adding a spurious span for every unit it got wrong, and +10% spurious costs 6.10.

It stays because the corpora disagree in a way that matters: gold is synthetic
`restyled/` prose, whereas **94/100 test files carry a `TÊN: giá trị` line**. This
is the lane that covers the real submission, and gold cannot show that. So it is
kept narrow rather than dropped: short values only, a label that names a type, and
nothing that another lane already covers.

Types come from `label_types` in `configs/pipeline.yaml` — a label prefix to a type
distribution. `extract/` returns distributions; `decision/` decides.
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..io.config import load_pipeline, require
from ..io.document import Document
from ..io.labels import TYPES
from ..layout.kv import LayoutUnit
from ..layout.lines import Line, LineKind
from .spans import Span, TokenView, tokenize

__all__ = ["spans", "SOURCE"]

SOURCE = "kvspan"


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return require(load_pipeline(), "extract.recall_floor.kvspan")


@lru_cache(maxsize=1)
def _label_types() -> tuple[tuple[str, dict[str, float]], ...]:
    """`label prefix -> type distribution`, longest prefix first.

    Longest-first is the rule, not an optimisation: `tiền sử dị ứng` must beat
    `tiền sử`, and a dict iteration order would decide it by accident.
    """
    table = require(_cfg(), "label_types")
    out = []
    for prefix, dist in table.items():
        clean = {k: float(v) for k, v in dist.items() if k in TYPES}
        if clean:
            total = sum(clean.values())
            out.append((_fold(prefix), {k: v / total for k, v in sorted(clean.items())}))
    return tuple(sorted(out, key=lambda kv: -len(kv[0])))


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _type_for(label: str) -> dict[str, float] | None:
    folded = _fold(label)
    for prefix, dist in _label_types():
        if folded == prefix or folded.startswith(prefix + " "):
            return dict(dist)
    return None


def _trim(raw: str, start: int, end: int) -> tuple[int, int]:
    """Shrink past whitespace and the punctuation a list item ends with."""
    trailing = require(_cfg(), "strip_trailing")
    while start < end and raw[start].isspace():
        start += 1
    while end > start and (raw[end - 1].isspace() or raw[end - 1] in trailing):
        end -= 1
    return start, end


def spans(
    doc: Document,
    view: TokenView | None = None,
    units: tuple[LayoutUnit, ...] = (),
    lines: tuple[Line, ...] = (),
    covered: list[Span] | None = None,
) -> list[Span]:
    """Values of typed `label: value` units, plus bullets under a typed header.

    `covered` is what the other lanes already found; anything overlapping it is
    dropped here rather than merged, because the other lanes have the sharper
    boundary and 0/7435 gold spans are nested.
    """
    view = view if view is not None else tokenize(doc)
    cfg = _cfg()
    max_tokens = int(require(cfg, "max_value_tokens"))
    score = float(require(cfg, "score"))
    bullet_score = float(require(cfg, "bullet_score"))
    raw = doc.raw

    taken = sorted((s.start, s.end) for s in (covered or ()))

    def clashes(start: int, end: int) -> bool:
        return any(start < b and a < end for a, b in taken)

    def n_tokens(start: int, end: int) -> int:
        ns, ne = doc.to_norm_span(start, end)
        i = view.token_at_or_after(ns)
        j = view.token_at_or_after(ne)
        return j - i

    found: list[Span] = []

    # ── typed `label: value` units ────────────────────────────────────────────
    for unit in units:
        if unit.label_span is None or unit.value_span is None:
            continue
        dist = _type_for(unit.label)
        if dist is None:
            continue
        start, end = _trim(raw, *unit.value_span)
        if start >= end or n_tokens(start, end) > max_tokens or clashes(start, end):
            continue
        found.append(
            Span(start=start, end=end, type_dist=dist, score=score, source=SOURCE)
        )

    # ── bullets under a typed header ──────────────────────────────────────────
    # `3. Tiền sử bệnh:` followed by `- Suy tim sung huyết` — the bullet inherits
    # the header's type. The header is carried forward rather than looked up per
    # line so a bullet list keeps its type all the way down.
    if bool(require(cfg, "bullets_inherit_header")):
        current: dict[str, float] | None = None
        for line in lines:
            if line.kind is LineKind.BLANK:
                continue
            if line.is_header:
                current = _type_for(line.label or line.content)
                continue
            if line.kind is not LineKind.BULLET or current is None:
                continue
            start, end = _trim(raw, line.content_start, line.end)
            if start >= end or n_tokens(start, end) > max_tokens or clashes(start, end):
                continue
            found.append(
                Span(
                    start=start,
                    end=end,
                    type_dist=dict(current),
                    score=bullet_score,
                    source=SOURCE,
                )
            )

    found.sort(key=lambda s: (s.start, -s.length, s.argmax_type()))
    out: list[Span] = []
    reach = -1
    for span in found:
        if span.start < reach:
            continue
        out.append(span)
        reach = span.end
    return out
