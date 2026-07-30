"""L4b · verify an RxCUI against the KB before it ships. A GUARD, not a scorer.

## Say the uncomfortable number first

On the pipeline as it stands, **both implemented rules fire zero times**. Measured
2026-07-30 over the 228 distinct RxCUIs the run emits across gold and test:

    in the retired/remap table   0 / 228
    carrying semantic type T200  0 / 228
    absent from RXNSTY           0 / 228   ← so the check is conclusive, not blind

So this module is worth **0.00 points today** and nothing here claims otherwise.

## Then why it exists

We are clean by *accident of an upstream filter*, not by rule.
`scripts/build_gazetteer.py` keeps only `tty ∈ {IN, PIN, MIN}`, which happens to
exclude retired and clinical-drug atoms. But `linking/rxnorm.py` lifts through
`brand_to_ingredient.json`, and that map is **not** tty-filtered:

    50.341 lift targets in the map      46.742 of them (93%) carry T200
    102 targets reachable from today's gazetteer      0 carry T200

Ninety-three percent of that map is a semantic type we must not emit, and the only
thing standing between it and the submission is a filter in a different file,
owned by a different phase, with no test tying the two together. Widen the tty
filter — a plausible P5/P6 move to raise drug recall — and T200 codes ship
silently. This module turns "clean because of something far away" into "clean
because a rule says so", and `tests/test_linking.py` fails the day that stops
being true.

That is the honest case for it: a regression guard on a path that is one config
edit away from breaking, not a source of points.

## The 6-bit vector, and why only 2 bits are real

`plan-v4` specifies six rules. This is the reduced two-rule version the P5 prompt
sanctions, and the two chosen are the ones it names as covering the "retired code"
failure mode that no other check can produce. The remaining four bits are declared
so the vector's width and bit order are fixed now — a later phase filling bit 2 in
must not renumber bits 0 and 1 underneath a stored verdict.

Rules are RxNorm-specific and apply to **THUỐC only**. An ICD-10 code passing
through here would be judged against a vocabulary it does not belong to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..io.config import ConfigError, load_pipeline, repo_root, require

__all__ = ["Verdict", "verify", "apply_verdicts", "RULES", "BIT_RETIRED", "BIT_T200"]

#: Bit positions are part of the contract — never renumber, only append.
BIT_RETIRED = 0
BIT_T200 = 1

#: (bit, name, implemented). The four unimplemented slots keep the width fixed.
RULES: tuple[tuple[int, str, bool], ...] = (
    (BIT_RETIRED, "retired_rxcui", True),
    (BIT_T200, "semantic_type_t200", True),
    (2, "ambiguous_ingredient_set", False),
    (3, "tty_mismatch_vs_target", False),
    (4, "dose_form_contradiction", False),
    (5, "strength_contradiction", False),
)


@dataclass(frozen=True)
class Verdict:
    """What the rules say about one code. `bits` is the violation vector."""

    code: str
    bits: int
    action: str                       # keep | remap | drop | abstain
    replacement: tuple[str, ...] = ()

    @property
    def violated(self) -> tuple[str, ...]:
        return tuple(n for b, n, impl in RULES if impl and self.bits >> b & 1)


@lru_cache(maxsize=1)
def _edge_index() -> dict:
    """The two RxCUI facts this module needs, precomputed and committed.

    These used to be read straight from `RXNCUI.RRF` (1.7 MB) and `RXNSTY.RRF`
    (20 MB) at inference time. Both are licence-gated UMLS drops that
    `.gitignore` excludes, so a clean checkout raised `ConfigError` on the first
    drug span — and PRD §5 disqualifies a submission the organisers cannot
    re-run. Only two columns of those 22 MB are ever used: 21.524 retirement
    pairs and 249.563 excluded-STY RxCUIs, which is 2.7 MB of JSON, small enough
    to track in git.

    Rebuild with `python3 scripts/build_edge_index.py` after refreshing RxNorm,
    and commit the result. `src/` never imports `scripts/`.
    """
    p = repo_root() / require(load_pipeline(), "linking.edge_index")
    if not p.exists():
        raise ConfigError(
            f"missing {p} — the retired-code and semantic-type checks cannot run. "
            f"A retired RxCUI scores 0 and looks identical to a correct one in "
            f"the output.\n"
            f"  rebuild it with:  python3 scripts/build_edge_index.py\n"
            f"  (needs the raw RxNorm drops; the built index is committed so a "
            f"fresh clone does not)"
        )
    blob = json.loads(p.read_text(encoding="utf-8"))

    # The index bakes in which semantic types were excluded when it was built.
    # If the config has moved since, the file on disk answers a question nobody
    # is asking any more — louder than silently filtering by the wrong set.
    built_for = [str(s) for s in blob.get("exclude_sty", ())]
    configured = sorted(str(s) for s in require(load_pipeline(), "linking.exclude_sty"))
    if built_for != configured:
        raise ConfigError(
            f"{p} was built for linking.exclude_sty={built_for}, but the config "
            f"now says {configured}. Re-run scripts/build_edge_index.py and "
            f"commit the result."
        )
    return blob


def _retired() -> dict[str, str]:
    """RxCUI → its successor (21.524 retired codes)."""
    return _edge_index()["retired"]


def _t200() -> frozenset[str]:
    """Every RxCUI carrying an excluded semantic type.

    DROP by T200; do NOT whitelist T109/T121 — measured, 220/220 gold RxCUIs are
    ingredient level but two of them (9863 sodium chloride T197, 11124
    vancomycin T116/T195) fall outside that whitelist, so whitelisting loses
    real codes.
    """
    return frozenset(_edge_index()["excluded_sty_rxcui"])


def verify(codes: tuple[str, ...] | list[str], etype: str) -> tuple[Verdict, ...]:
    """One verdict per code. Non-drug types are returned untouched as `keep`."""
    if etype != "THUỐC":
        return tuple(Verdict(str(c), 0, "keep") for c in codes)

    retired, t200 = _retired(), _t200()
    out = []
    for raw in codes:
        c = str(raw)
        bits = 0
        action, repl = "keep", ()
        if c in retired:
            bits |= 1 << BIT_RETIRED
            action, repl = "remap", (retired[c],)
        # T200 outranks a remap: a successor that is still a clinical drug is not
        # worth shipping either, and `drop` is the safer of the two verdicts.
        target = repl[0] if repl else c
        if target in t200:
            bits |= 1 << BIT_T200
            action, repl = "drop", ()
        out.append(Verdict(c, bits, action, repl))
    return tuple(out)


def apply_verdicts(codes: tuple[str, ...] | list[str], etype: str) -> tuple[str, ...]:
    """The codes that survive, order-stable and de-duplicated.

    `drop` removes a code rather than replacing it. That is the right trade here
    and only here: an entity whose gold carries a code scores 0 for a wrong code
    and 0 for no code, so dropping a code we have positive evidence against is
    free — unlike `linking/icd.py`, where guessing on an empty span is the free
    direction. The two modules look like they disagree; they are reading the same
    asymmetry from opposite ends.
    """
    kept: list[str] = []
    for v in verify(codes, etype):
        if v.action == "drop":
            continue
        kept.extend(v.replacement or (v.code,))
    return tuple(dict.fromkeys(kept))
