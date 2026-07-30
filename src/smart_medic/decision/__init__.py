"""L5 · `decision/` — the ONLY layer allowed to apply a threshold.

~300 lines, nothing trained, and it compounds with every other layer. It is the
cheapest layer per point bought, because every one of its parameters is a line of
YAML that no model has to be retrained to change.

The global invariant *"layers return DISTRIBUTIONS; only `decision/` thresholds"*
exists to make that true.

    emit.py       span gate — density-keyed table            P1 (one row) → P6
    select.py     assertions (expected-Jaccard argmax) + candidates (KB rules)  P6
    calibrate.py  Platt, 2 parameters                        P6, if there is a model
"""
from __future__ import annotations

from .emit import Concept, ThresholdChoice, finalize, select_threshold

__all__ = ["Concept", "ThresholdChoice", "finalize", "select_threshold"]
