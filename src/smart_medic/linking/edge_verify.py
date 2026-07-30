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

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..io.config import ConfigError, kb_paths, load_pipeline, require

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
def _retired() -> dict[str, str]:
    """RxCUI → its successor, from `RXNCUI.RRF` (21.524 retired codes)."""
    p = Path(kb_paths()["root"]) / "RXNCUI.RRF"
    if not p.exists():
        raise ConfigError(
            f"{p} not found — the retired-code check cannot run. A retired RxCUI "
            f"scores 0 and looks identical to a correct one in the output."
        )
    out: dict[str, str] = {}
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("|")
            if len(f) > 4 and f[0] and f[4] and f[0] != f[4]:
                out[f[0]] = f[4]
    return out


@lru_cache(maxsize=1)
def _t200() -> frozenset[str]:
    """Every RxCUI carrying T200. DROP by this; do NOT whitelist T109/T121 —
    measured, 220/220 gold RxCUIs are ingredient level but two of them
    (9863 sodium chloride T197, 11124 vancomycin T116/T195) fall outside that
    whitelist, so whitelisting loses real codes."""
    p = Path(kb_paths()["root"]) / "RXNSTY.RRF"
    if not p.exists():
        raise ConfigError(f"{p} not found — the T200 check cannot run.")
    drop = set(require(load_pipeline(), "linking.exclude_sty"))
    out = set()
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.split("|", 2)
            if len(f) > 1 and f[1] in drop:
                out.add(f[0])
    return frozenset(out)


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
