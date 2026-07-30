"""L5 · the emit gate. P1 ships the CONSTANT branch only.

`decision/` is the one layer allowed to compare a score against a threshold. Every
layer below returns a distribution precisely so that this comparison happens in
exactly one place, where it can be retuned from YAML without retraining anything.

## Why the threshold is a table, and why P1 uses one row of it

The marginal exchange rate measured directly is `c_fn / c_fp = 1.14`, giving a
Bayes threshold of `p* = 0.468`. But that is measured *near the ceiling*. In real
operation a rescued entity brings its `assertions` and `candidates` score with it,
so the break-even moves with how much you are already missing:

    miss 10% → score 63.02 → break-even ≈ 0.44
    miss 30% → score 49.45 → break-even ≈ 0.38
    miss 60% → score 28.01 → break-even ≈ 0.23

Hence `decision.emit_threshold` in `configs/pipeline.yaml` is keyed by the run's own
entity density, not by a constant. **P1 deliberately implements only the
`density_ratio < 0.50` row**: the lane-R baseline is far under half of gold's
45.9 entities/file, so that is the row that applies, and building the full table
before there is anything to look up in it would be guessing at the shape of a
curve the P6 measurements have not drawn yet. `select_threshold()` therefore
*asserts* it is in that regime and says so loudly when it is not, rather than
silently reading a row it was not built to honour.

This is not "recall at any cost". Measured: missing 30% *and* adding 30% spurious
scores 42.58, which is 6.87 points **worse** than missing 30% alone (49.45). A gate
at 0 is wrong in every regime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..extract.spans import Span
from ..io.config import ConfigError, load_pipeline, require
from ..io.document import Document
from ..io.labels import CODEABLE_TYPES, LAB_TYPES
from ..linking import edge_verify, icd, rxnorm

__all__ = ["Concept", "ThresholdChoice", "select_threshold", "finalize", "P1_BRANCH"]

#: The one row of the table P1 implements. P6 replaces this module's single
#: lookup with the full three-tier schedule.
P1_BRANCH = "<0.50"

_RANGE = re.compile(r"^(?P<op><|>|<=|>=)?\s*(?P<a>[\d.]+)(?:\s*-\s*(?P<b>[\d.]+))?$")


def _pick_codes(
    codes: tuple[str, ...], etype: str, caps: dict, order: str, surface: str = ""
) -> tuple[str, ...]:
    """The codes that leave this layer for one entity. Deterministic, always.

    A type absent from `caps` gets none, which is what keeps the three
    non-codeable types empty without a second rule to remember: the schema
    constraint below and this table cannot disagree.
    """
    cap = int(caps.get(etype, 0))
    if cap <= 0:
        return ()
    if not codes and etype == "CHẨN_ĐOÁN" and surface:
        # Nothing matched the gazetteer exactly. On a span we would otherwise ship
        # empty, a wrong code scores the same 0 as no code — see linking/icd.py.
        codes = icd.retrieve(surface)
    if not codes:
        return ()
    if etype == "THUỐC":
        # ADR 0001 rule 1, BEFORE the cut: a combination brand lifts to two
        # ingredient codes, and cutting first would truncate the second one.
        codes = rxnorm.lift_to_ingredient(codes)
        # …and verify AFTER the lift: the lift is the one path into `candidates`
        # that does not pass the gazetteer's tty filter, so it is exactly the path
        # that can introduce a retired or T200 code. Fires 0 times today; see
        # linking/edge_verify.py for why it is here anyway.
        codes = edge_verify.apply_verdicts(codes, etype)
    if order == "shortest_first":
        ranked = sorted(codes, key=lambda c: (len(c), c))
    elif order == "ascending":
        ranked = sorted(codes)
    else:
        raise ConfigError(
            f"decision.code_order is {order!r}; expected 'shortest_first' or "
            f"'ascending'. A silent fallback here would make two builds of the "
            f"same commit emit different codes."
        )
    return tuple(ranked[:cap])


@dataclass(frozen=True)
class Concept:
    """The record that gets serialised. `validate/` is what actually writes it."""

    text: str
    position: tuple[int, int]
    type: str
    assertions: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "type": self.type,
            "candidates": list(self.candidates),
            "assertions": list(self.assertions),
            "position": [self.position[0], self.position[1]],
        }


@dataclass(frozen=True)
class ThresholdChoice:
    """Which row of the table was used, and on what evidence."""

    p: float
    branch: str
    density: float
    density_ratio: float
    regime: str

    @property
    def regime_matches(self) -> bool:
        return self.regime == P1_BRANCH

    def summary(self) -> str:
        return (
            f"emit_threshold p={self.p:.2f} (branch {self.branch!r}) from "
            f"candidate density {self.density:.2f}/file, ratio "
            f"{self.density_ratio:.3f}"
        )

    def warning(self) -> str:
        """Empty when the measured density agrees with the branch P1 implements."""
        if self.regime_matches:
            return ""
        return (
            f"⚠ REGIME MISMATCH — candidate density {self.density:.2f}/file is "
            f"ratio {self.density_ratio:.3f} of gold's 45.9, which the table maps to "
            f"branch {self.regime!r}, not the {P1_BRANCH!r} branch this P1 constant "
            f"gate implements.\n"
            f"  The plan's premise was the 15.8/file baseline (ratio 0.34). Lane R "
            f"is denser than that, so p={self.p:.2f} is now a LOOSER gate than the "
            f"table intends and the run is over-generating rather than under-\n"
            f"  generating. +10% spurious costs 6.10 points, +30% costs 15.61. The "
            f"three-tier schedule is P6 by design (see the module docstring); this "
            f"is the number that says P6 has become load-bearing."
        )


@lru_cache(maxsize=1)
def _decision_cfg() -> dict:
    return require(load_pipeline(), "decision")


def _matches(spec: str, ratio: float) -> bool:
    m = _RANGE.match(str(spec).strip())
    if m is None:
        raise ConfigError(
            f"decision.emit_threshold: cannot parse density_ratio {spec!r} "
            f"(expected '<0.50', '0.50-0.80' or '>0.80')"
        )
    a = float(m.group("a"))
    if m.group("b") is not None:
        return a <= ratio <= float(m.group("b"))
    op = m.group("op") or "<"
    return {"<": ratio < a, "<=": ratio <= a, ">": ratio > a, ">=": ratio >= a}[op]


def select_threshold(density: float) -> ThresholdChoice:
    """Look up `p` for this run's entity density. P1 honours one row only.

    `density` is candidate spans per file from `extract.RecallFloorReport`. This
    is why that number is printed on every run: it is the input to a decision
    parameter, not a diagnostic.
    """
    cfg = _decision_cfg()
    gold_density = float(require(cfg, "gold_density_per_file"))
    if gold_density <= 0:
        raise ConfigError("decision.gold_density_per_file must be > 0")
    ratio = density / gold_density

    table = require(cfg, "emit_threshold")
    # The CONSTANT: the row P1 implements, looked up by name, not by measurement.
    # Reading the table by density here would be implementing the schedule, which
    # is P6's job and needs P6's measurements behind it.
    row = next(
        (r for r in table if str(require(r, "density_ratio")) == P1_BRANCH), None
    )
    if row is None:
        raise ConfigError(
            f"decision.emit_threshold has no {P1_BRANCH!r} row — that row is the "
            f"P1 constant gate. Rows present: "
            f"{[r.get('density_ratio') for r in table]}"
        )
    # Which row the measurement WOULD have selected. Reported, never acted on:
    # if these two disagree, the plan's density premise no longer holds and that
    # is a finding, not something to paper over.
    regime = next(
        (
            str(require(r, "density_ratio"))
            for r in table
            if _matches(require(r, "density_ratio"), ratio)
        ),
        "unmapped",
    )
    return ThresholdChoice(
        p=float(require(row, "p")),
        branch=P1_BRANCH,
        density=density,
        density_ratio=ratio,
        regime=regime,
    )


def finalize(
    doc: Document,
    spans: list[Span],
    threshold: ThresholdChoice,
) -> list[dict]:
    """Apply the gate, pick the type, and produce submission records.

    * `assertions` is P4. An empty list is the correct answer for the two lab
      types (worth 11.59 points) and a Jaccard of 0 elsewhere — the same 0 a wrong
      flag would score, so guessing here buys nothing.
    * `candidates` comes from `Span.codes`, which `extract/aho.py` already carries
      off the gazetteer: 799 of 971 codeable spans (82.3%) arrive here with a code
      attached. This function used to discard all of them, on the reading that the
      `+1` in the official denominator capped the whole term at 10.00 of a 70.00
      ceiling. **That reading was wrong** — the `+1` is a per-document weight, not
      a denominator, the ceiling is 100.00, and dropping the codes was costing
      5.11 points measured (CI95 [+4.51; +5.73]). See ADR 0002, "Đặc tả CHÍNH
      THỨC", and `configs/pipeline.yaml: decision.max_candidates_per_type` for the
      cardinality table.

      Still true, and still the reason not to pad the list: an extra code on an
      entity whose gold carries one shrinks that entity's Jaccard from 1.0 to 0.5.
      Cardinality is a measured rule, not a hedge.

    `type` is argmax with no hedging: emitting two types for one span costs 1.29
    points under *both* alignment readings.
    """
    caps = require(load_pipeline(), "decision.max_candidates_per_type")
    order = require(load_pipeline(), "decision.code_order")

    out: list[dict] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if span.score < threshold.p:
            continue
        etype = span.argmax_type()
        surface = span.text(doc)
        concept = Concept(
            text=surface,
            position=(span.start, span.end),
            type=etype,
            assertions=(),
            candidates=_pick_codes(span.codes, etype, caps, order, surface),
        )
        if etype in LAB_TYPES:
            assert not concept.assertions  # the 11.59-point constraint
        if etype not in CODEABLE_TYPES:
            assert not concept.candidates
        out.append(concept.as_dict())
    return out
