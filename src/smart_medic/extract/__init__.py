"""L3 · `extract/` — span + type. ≈60.00 of the reachable 70.00 points.

A missed entity scores zero in all three terms at once under the `penalised`
reading, so this layer is not the 30 points its nominal weight suggests. Measured
on 162 gold files, dropping 10% of entities at random: `text` −2.99,
`assertions` −2.99, `candidates` −1.00.

Two lanes, in a fixed order (see `README.md`):

    LANE R · recall_floor()   rules only. No model, no GPU, no checkpoint.
    LANE M · propose()        encoder ≤9B, raw threshold 0.15.            [P3]

Lane R ships first because it is the only recall in the project that cannot
regress when a checkpoint changes, and because if the clock runs out it *is* the
submission.

`recall_floor()` merges its three sub-lanes by source priority. That is the P1
stand-in for the graph merge in `overlap_graph.py` + `boundary.py` (P3), and it is
a stand-in, not the answer: the measured reason the real version exists is that an
IoU≥0.5 merge discards 54.2% of boundary variants (85.7% on one-word spans, and
37.8% of gold spans are exactly one word). Priority ordering at least never
*invents* a boundary no lane proposed.

Invariant: nothing in this layer applies a threshold. Spans come out with a type
DISTRIBUTION and a score; `decision/emit.py` is the only place allowed to decide.
"""
from __future__ import annotations

from ..io.config import load_pipeline, require
from ..io.document import Document
from ..layout.kv import LayoutUnit, split_units
from ..layout.lines import Line, split_lines
from . import aho, kvspan, labvalues
from .spans import Span, Token, TokenView, merge_type_dist, tokenize

__all__ = [
    "Span",
    "Token",
    "TokenView",
    "tokenize",
    "merge_type_dist",
    "recall_floor",
    "RecallFloorReport",
]


class RecallFloorReport:
    """Per-lane counts. Printed on every run — density feeds `emit_threshold`.

    `configs/pipeline.yaml decision.emit_threshold` is a table keyed by the run's
    own entity density, so this is an input to a decision parameter, not a
    decoration.
    """

    def __init__(self) -> None:
        self.documents = 0
        self.per_lane: dict[str, int] = {}
        self.dropped_overlap = 0
        self.emitted = 0

    def note(self, lane: str, n: int) -> None:
        self.per_lane[lane] = self.per_lane.get(lane, 0) + n

    def density(self) -> float:
        return self.emitted / self.documents if self.documents else 0.0

    def summary(self) -> str:
        lanes = " · ".join(f"{k} {v}" for k, v in sorted(self.per_lane.items()))
        return (
            f"{self.documents} docs · {self.emitted} candidate spans "
            f"({self.density():.2f}/file) · lanes: {lanes} · "
            f"{self.dropped_overlap} dropped as overlapping"
        )


def _priority() -> dict[str, int]:
    order = require(load_pipeline(), "extract.recall_floor.merge_priority")
    return {name: i for i, name in enumerate(order)}


def recall_floor(
    doc: Document,
    lines: tuple[Line, ...] | None = None,
    units: tuple[LayoutUnit, ...] | None = None,
    report: RecallFloorReport | None = None,
) -> list[Span]:
    """Lane R: every rule-based candidate in `doc`, on `doc.raw`, non-overlapping.

    No model is loaded and no threshold is applied.
    """
    lines = lines if lines is not None else split_lines(doc)
    units = units if units is not None else split_units(doc, lines)
    view = tokenize(doc)

    lab = labvalues.spans(doc, view, units)
    gaz = aho.spans(doc, view)
    kv = kvspan.spans(doc, view, units, lines, covered=lab + gaz)

    if report is not None:
        report.documents += 1
        report.note("labvalues", len(lab))
        report.note("aho", len(gaz))
        report.note("kvspan", len(kv))

    merged = _merge(lab + gaz + kv, report)
    if report is not None:
        report.emitted += len(merged)
    return merged


def _merge(found: list[Span], report: RecallFloorReport | None) -> list[Span]:
    """Resolve overlaps LONGEST first, then by source priority, then leftmost.

    The no-nesting constraint is not cosmetic: 0/7435 gold spans are nested, so a
    nested pair is one right answer plus one guaranteed spurious span.
    `validate/schema.py` re-checks it on the written JSON, but by then the choice
    of *which* span to keep has already been made, and badly.

    Length outranks source priority, and that ordering was measured, not assumed.
    Letting `labvalues` win on length as well as priority costs 0.47 on
    `penalised/greedy_iou` and **2.08 on `penalised/overlap_type`**, the blocking
    column: `mạch` is a real lab name, but inside `bệnh mạch vành` the gazetteer's
    longer diagnosis span is the right answer, and a lane-priority sort hands the
    span to the wrong type. `merge_priority` therefore breaks ties at equal
    length — where the lane that read the line structure should indeed win.
    """
    rank = _priority()
    order = sorted(
        found,
        key=lambda s: (
            -s.length,
            rank.get(s.source, len(rank)),
            s.start,
            s.argmax_type(),
        ),
    )
    kept: list[Span] = []
    for span in order:
        if any(span.start < k.end and k.start < span.end for k in kept):
            if report is not None:
                report.dropped_overlap += 1
            continue
        kept.append(span)
    kept.sort(key=lambda s: (s.start, s.end))
    return kept
