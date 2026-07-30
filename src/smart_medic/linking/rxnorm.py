"""L4b · RxNorm — lift a brand RxCUI to its ingredient level.

ADR 0001 rule 1: *"Biệt dược → hoạt chất qua `brand_to_ingredient.json`"*. The
gazetteer is filtered to `tty ∈ {IN, PIN, MIN}` at build time, so a name that
matches directly already arrives at ingredient level — but a **brand** name reaches
`extract/aho.py` through a silver-mined key whose code is the brand's RxCUI, and
that code is not what gold carries.

Measured 2026-07-30 on 162 gold, official metric:

    Solu-Medrol tĩnh mạch   gold 6902        we emitted 203856
    Astelin dạng xịt mũi    gold 18603       we emitted 215453
    Lorcet                  gold 161 · 5489  we emitted 491666

`brand_to_ingredient.json` resolves all three exactly — `203856 → [6902]`,
`491666 → [161, 5489]`. 73 of the 386 fully-wrong codes on that run were this one
failure mode, and 398 drug spans carry a code the map can lift.

    lift applied  →  candidates 57.82 → 60.60, score 56.75 → 57.86
    Δ = +1.109  SE 0.103  CI95 [+0.912; +1.318]  bar 0.202  → real

Why `Lorcet` returns TWO codes and why that is correct: it is a combination
product, and gold lists every active ingredient. That is the whole reason
`decision.max_candidates_per_type: {THUỐC: 2}` is 2 and not 1 — the lift has to run
BEFORE the cardinality cut or the second ingredient is truncated away.

This module reads a KB file and applies a rule. It holds no threshold: `target_tty`
lives in `configs/pipeline.yaml` (ADR 0001 requires it stay a parameter, and the
lift is exactly what `IN` means operationally).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..io.config import ConfigError, kb_paths, load_pipeline, require

__all__ = ["load_brand_map", "lift_to_ingredient", "BRAND_MAP"]

#: Flat KB directory, name resolved through io.config — never hard-coded.
BRAND_MAP = "brand_to_ingredient.json"


@lru_cache(maxsize=1)
def load_brand_map(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """RxCUI → ingredient RxCUIs. 96.495 keys.

    Raises rather than degrading: a silently absent map means every brand name
    ships the wrong code and the run still looks healthy, which is the one failure
    shape this project has repeatedly paid for.
    """
    p = Path(path) if path else Path(kb_paths()["root"]) / BRAND_MAP
    if not p.exists():
        raise ConfigError(
            f"{p} not found — the brand→ingredient lift (ADR 0001 rule 1) cannot "
            f"run, and every brand-name drug would ship a brand RxCUI where gold "
            f"carries the ingredient. Restore the KB rather than skipping the lift."
        )
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {
        str(k): tuple(str(x) for x in v)
        for k, v in raw.items()
        if isinstance(v, (list, tuple)) and v
    }


def lift_to_ingredient(
    codes: tuple[str, ...] | list[str], *, brand_map: dict | None = None
) -> tuple[str, ...]:
    """Replace every brand RxCUI with its ingredient RxCUIs, order-stable.

    A code absent from the map is kept as-is — it is either already an ingredient
    (the gazetteer's `tty` filter guarantees most are) or something the map has no
    opinion about, and dropping it would trade a possibly-right code for nothing.

    Duplicates collapse: two brands of the same ingredient must not consume both
    slots of `max_candidates_per_type: {THUỐC: 2}` with the same RxCUI.
    """
    if not codes:
        return ()
    m = brand_map if brand_map is not None else load_brand_map()
    out: list[str] = []
    for c in codes:
        out.extend(m.get(str(c), (str(c),)))
    return tuple(dict.fromkeys(out))


def target_tty() -> str:
    """`configs/pipeline.yaml: linking.target_tty`. ADR 0001 closed this at `IN`
    on 2026-07-30 (Probe B, ΔB = +1.5429), but it stays a parameter: the ADR's
    fallback path to a product tier is one YAML edit, not a code change."""
    return str(require(load_pipeline(), "linking.target_tty"))
