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

from dataclasses import dataclass
from functools import lru_cache

from ..assertion import scope
from ..extract.spans import Span
from ..io.config import ConfigError, load_pipeline, require, require_probability
from ..io.document import Document
from ..io.labels import CODEABLE_TYPES, LAB_TYPES
from ..linking import edge_verify, icd, rxnorm

__all__ = [
    "Concept",
    "ThresholdChoice",
    "select_threshold",
    "finalize",
    "assertion_rate_check",
]

#: The one row of the table P1 implements. P6 replaces this module's single
#: lookup with the full three-tier schedule.
def _in_swept_range(ratio: float) -> bool:
    lo, hi = _swept_range()
    return lo <= ratio <= hi


def _swept_range() -> tuple[float, float]:
    """Density ratios the emit threshold was measured over.

    Lives in `configs/pipeline.yaml` like every other number here: a bound baked
    into Python is a bound nobody reviews, and the config's sha256 goes into the
    run manifest.
    """
    lo, hi = (float(x) for x in require(load_pipeline(), "decision.swept_density_ratio"))
    return lo, hi


def assertion_rate_check(records: list[dict]) -> str:
    """Empty when the share of flagged entities is inside the configured band.

    A tripwire, not a tuning knob. The synthetic gold corpus flags 29.6% of its
    entities; the real test set is near 13% (implied by the leaderboard) and
    11.6% (hand-annotated sample). A run drifting toward the synthetic rate is
    over-flagging against the thing we are actually scored on, and each excess
    flag turns a scored 1 into a 0. `cli.py` refuses to write when this fires.
    """
    if not records:
        return ""
    lo, hi = (float(x) for x in require(load_pipeline(), "assertion.rate_band"))
    flagged = sum(1 for r in records if r.get("assertions"))
    rate = flagged / len(records)
    if lo <= rate <= hi:
        return ""
    direction = "ABOVE" if rate > hi else "BELOW"
    return (
        f"⚠ ASSERTION RATE {rate:.3f} IS {direction} THE BAND [{lo:.2f}, {hi:.2f}] "
        f"— {flagged}/{len(records)} entities flagged.\n"
        f"  The test set carries an assertion on ~13% of matched entities "
        f"(leaderboard) and 11.6% (hand-annotated sample); the synthetic gold "
        f"corpus says 29.6% and is not what we are scored on.\n"
        f"  Above the band means points already held are being spent: on an "
        f"entity whose gold set is empty, any flag scores 0 where nothing scored "
        f"1. Below it means the rules stopped firing. Either way, look before "
        f"submitting."
    )


#: Types for which `linking/icd.py` is asked for a code when the gazetteer found
#: none. Both map into the same Vietnamese ICD-10 name space — diagnoses into the
#: body-system chapters, symptoms into chapter XVIII (R00–R99). THUỐC is absent
#: because its codes are RxCUIs, a different vocabulary entirely.
_ICD_RETRIEVAL_TYPES = frozenset({"CHẨN_ĐOÁN", "TRIỆU_CHỨNG"})



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
    if not codes and etype in _ICD_RETRIEVAL_TYPES and surface:
        # Nothing matched the gazetteer exactly. On a span we would otherwise ship
        # empty, a wrong code scores the same 0 as no code — see linking/icd.py.
        #
        # TRIỆU_CHỨNG joined CHẨN_ĐOÁN here on 2026-07-31. ICD-10 chapter XVIII
        # (R00–R99, "Symptoms, signs and abnormal findings") is a symptom
        # vocabulary, so the same Vietnamese-to-Vietnamese index answers both;
        # the reason to ask it is that the leaderboard ratio bounds the share of
        # uncoded gold entities at 0.356 and diagnosis+drug alone cannot fit
        # under that (see io/labels.CODEABLE_TYPES).
        codes = icd.retrieve(
            surface, prefer_symptom_chapter=(etype == "TRIỆU_CHỨNG")
        )
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
        """True when this run's density is inside the range `p` was swept over."""
        return self.regime == "in-range"

    def summary(self) -> str:
        return (
            f"emit_threshold p={self.p:.2f} (branch {self.branch!r}) from "
            f"candidate density {self.density:.2f}/file, ratio "
            f"{self.density_ratio:.3f}"
        )

    def warning(self) -> str:
        """Empty when the density lands inside a row of the table.

        Before W5 this fired on every run: the table was pinned to one row by
        name while the density pointed at another, and the ratio it compared
        against used the synthetic corpus's 45.9 entities/file instead of the
        test set's 36.2. Both are fixed, so this is now a real anomaly signal
        rather than standing noise — the only way to reach it is a density
        outside every row, which means the run does not resemble anything the
        table was swept on.
        """
        if self.regime_matches:
            return ""
        lo, hi = _swept_range()
        return (
            f"⚠ DENSITY OUTSIDE THE SWEPT RANGE — {self.density:.2f} entities/file "
            f"is ratio {self.density_ratio:.3f} of the test set's "
            f"{self.density / self.density_ratio:.1f}/file, outside the "
            f"[{lo:.2f}, {hi:.2f}] the threshold was measured over.\n"
            f"  p={self.p:.2f} is still applied — it is flat from 0.10 to 0.25 on "
            f"every run measured — but nothing here was verified at this density.\n"
            f"  Check the extract report before trusting the output: a ratio this "
            f"far out usually means a lane changed, not that the corpus did."
        )


@lru_cache(maxsize=1)
def _decision_cfg() -> dict:
    return require(load_pipeline(), "decision")


def select_threshold(density: float) -> ThresholdChoice:
    """The emit threshold, plus whether this run resembles the swept range.

    `density` is candidate spans per file from `extract.RecallFloorReport`. It no
    longer selects `p` — see the comment below and the sweep in
    configs/pipeline.yaml — but it is still what tells us whether the measured
    constant applies to the run in front of us.
    """
    cfg = _decision_cfg()
    gold_density = float(require(cfg, "gold_density_per_file"))
    if gold_density <= 0:
        raise ConfigError("decision.gold_density_per_file must be > 0")
    ratio = density / gold_density

    # ONE swept constant since W5 (2026-07-31), not a density-keyed schedule.
    #
    # The old table pinned `p` by row name and reported which row the density
    # would have chosen; that report disagreed on every run. Two errors were
    # stacked. `gold_density_per_file` was the synthetic corpus's 45.9 rather
    # than the test set's 36.2, so every ratio was 27% off — and fixing only
    # that made things worse, because the corrected ratio (0.804) selects the
    # tightest row, which the sweep shows costs 5.5 points.
    #
    # The schedule's premise ("dense run ⇒ over-generating ⇒ tighten") is false
    # here: recall is still 0.622 at 29.12 entities/file. Density rose because
    # the lexicon lane found spans that were RIGHT. So the tiers were removed
    # rather than re-tuned — see configs/pipeline.yaml for the full sweep.
    p = require_probability(cfg, "emit_threshold")

    # `ratio` is no longer an input to the choice; it is the anomaly signal. The
    # sweep covered 0.5–1.2, so a run far outside that is not one these numbers
    # were measured on.
    return ThresholdChoice(
        p=p,
        branch="swept-constant",
        density=density,
        density_ratio=ratio,
        regime="in-range" if _in_swept_range(ratio) else "outside",
    )


def finalize(
    doc: Document,
    spans: list[Span],
    threshold: ThresholdChoice,
    section_at=None,
) -> list[dict]:
    """Apply the gate, pick the type, and produce submission records.

    * `assertions` comes from `assertion/scope.py`. It stays empty for the two
      lab types, which the schema requires, and empty elsewhere unless a narrow
      rule fires: only ~13% of matched gold entities carry a flag at all, so an
      unjustified one turns a scored 1 into a 0 about seven times as often as it
      rescues a 0. `section_at` is `layout.outline.SectionIndex`; without it the
      history rule cannot fire and only negation is detected.
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
        titles = section_at(span.start).path() if section_at is not None else ()
        # A redacted drug name carries no assertions. All 7 such spans in
        # proxy_gold_test/ have an empty list, and the reason generalises: the
        # annotator masked the name precisely because they were not asserting
        # anything about that specific drug. Left to the ordinary rules, 3 of the
        # 99 pick up a flag — 1 from a Tiền sử heading (defensible), and 2 from a
        # negation cue that is really the interrogative "không:" ending a
        # patient's question, which the 15-character lookback misreads. The
        # scoring is symmetric (a wrong flag and a missing flag both score 0), so
        # this follows the 7/7 evidence rather than the rule.
        assertions = (
            ()
            if span.source == "redacted"
            else scope.assertions_for(doc.raw, span.start, etype, titles)
        )
        concept = Concept(
            text=surface,
            position=(span.start, span.end),
            type=etype,
            assertions=assertions,
            candidates=_pick_codes(span.codes, etype, caps, order, surface),
        )
        if etype in LAB_TYPES:
            assert not concept.assertions  # the 11.59-point constraint
        if etype not in CODEABLE_TYPES:
            assert not concept.candidates
        out.append(concept.as_dict())
    return out
