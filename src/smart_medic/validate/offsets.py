"""L6 · `raw[start:end] == text`, byte-exact, tolerance 0.

This check is worth the entire 70.00, and it is the one failure in the project
that produces **no exception and no log** on its own — just a zero. So here it is
made loud.

It is deliberately NOT repairable. Setting `text = raw[start:end]` would make the
assertion true by construction and hide the exact bug it exists to catch: a stage
that normalised to NFC before computing an offset, shifting every later span by up
to 143 characters. 20/100 test files and 41/162 gold files are not in NFC.

Compared against `Document.raw`, never `.normalized`.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

from ..io.document import Document

__all__ = ["OffsetViolation", "check", "assert_exact"]

#: Display limit for the error message. Not a threshold — nothing is filtered.
_MAX_ERRORS_SHOWN = 20


class OffsetViolation(AssertionError):
    """A span that does not slice back to its own text. Always a pipeline bug."""


def check(raw: str, entities: Iterable[dict], label: str = "") -> list[str]:
    """Return human-readable violations; empty means clean."""
    errs: list[str] = []
    prefix = f"{label}" if label else "entity"

    for i, e in enumerate(entities):
        where = f"{prefix}[{i}]"
        pos = e.get("position")
        if (
            not isinstance(pos, (list, tuple))
            or len(pos) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in pos)
        ):
            errs.append(f"{where}: position must be [int, int], got {pos!r}")
            continue

        start, end = pos
        if not (0 <= start < end <= len(raw)):
            errs.append(
                f"{where}: position [{start},{end}] out of range for a "
                f"{len(raw)}-char document"
            )
            continue

        sliced = raw[start:end]
        text = e.get("text")
        if sliced == text:
            continue

        msg = (
            f"{where}: OFFSET MISMATCH\n"
            f"    raw[{start}:{end}] = {sliced!r}\n"
            f"    text              = {text!r}"
        )
        # A shift caused by NFC normalisation has a recognisable signature: the
        # two strings are equal once both are normalised. Say so, because that
        # single line is the difference between an hour and a day of debugging.
        if isinstance(text, str) and unicodedata.normalize(
            "NFC", sliced
        ) == unicodedata.normalize("NFC", text):
            msg += (
                "\n    ^ equal under NFC — this is a UNICODE NORMALISATION bug. "
                "Some stage computed the offset on Document.normalized and never "
                "called to_raw()."
            )
        errs.append(msg)

    return errs


def assert_exact(
    raw: str | Document, entities: Iterable[dict], label: str = ""
) -> None:
    """Raise `OffsetViolation` on the first sign of an offset defect."""
    text = raw.raw if isinstance(raw, Document) else raw
    errs = check(text, entities, label)
    if errs:
        raise OffsetViolation(
            f"{len(errs)} offset violation(s)"
            + (f" in {label}" if label else "")
            + ":\n\n"
            + "\n".join(errs[:_MAX_ERRORS_SHOWN])
            + ("\n... (truncated)" if len(errs) > _MAX_ERRORS_SHOWN else "")
        )
