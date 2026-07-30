"""L4a · assertion — `isNegated` / `isHistorical` for an extracted span.

Reads `raw` and the section path from `layout/`; writes nothing. The rate band
that stops this layer from over-flagging lives in `decision/emit.py`, because
`decision/` is the only layer allowed to hold a threshold.
"""
from .scope import (
    FAMILY_HEADINGS,
    HISTORY_HEADINGS,
    NEGATION_CUES,
    assertions_for,
    history_section,
    negation_cue_before,
)

__all__ = [
    "assertions_for",
    "negation_cue_before",
    "history_section",
    "NEGATION_CUES",
    "HISTORY_HEADINGS",
    "FAMILY_HEADINGS",
]
