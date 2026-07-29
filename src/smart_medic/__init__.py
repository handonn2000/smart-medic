"""Smart Medic — Vietnamese clinical concept extraction and normalisation.

Viettel AI Race 2026, Vòng 1.

Invariant that governs this whole package: `position` is always an index into
the **raw, unmodified** bytes of the source document as read from disk. Never
compute an offset against a normalised, re-wrapped, or word-segmented copy —
20 of the 100 scored inputs are not in Unicode NFC, and normalising them shifts
every later span by up to 143 characters.

Normalise for matching, map back before emitting. `tests/test_offsets.py`
enforces this on every prediction we write.
"""

__version__ = "0.1.0"
