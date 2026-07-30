"""L1 · the immutable document, and the only safe way to talk about an offset.

`position` in the submission format indexes the ORIGINAL, UN-NORMALISED string.
20/100 test files and 41/162 gold files are not in Unicode NFC. Normalising
before computing an offset shifts every later span by up to 143 characters and
raises no exception at all — the failure mode is a silent zero.

So this module keeps exactly one source of truth (`Document.raw`) and offers
normalisation as a strictly separate, *mapped* view:

    doc.raw                 immutable bytes-as-read. Every emitted offset is here.
    doc.normalized          NFC. FOR MATCHING ONLY (gazetteers, tokenizers).
    doc.to_raw(i)           normalized index  → raw index
    doc.to_norm(i)          raw index         → normalized index
    doc.slice(s, e)         raw[s:e], bounds-checked

Anything computed on `.normalized` must pass through `to_raw()` / `to_raw_span()`
before it leaves the pipeline.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

__all__ = [
    "Document",
    "AnnotatedDocument",
    "OffsetError",
    "read_raw",
    "normalise_with_map",
]


class OffsetError(ValueError):
    """An index or span that cannot be mapped, or a slice that is out of range."""


def read_raw(path: str | Path) -> str:
    """Read a document EXACTLY as the scorer will see it.

    `newline=""` is not optional. Without it Python rewrites CRLF to LF and every
    offset after the first line break is wrong by the number of lines — a shift no
    reviewer spots by eye. No normalisation, no strip, no whitespace fixing.
    """
    return Path(path).read_text(encoding="utf-8", newline="")


def normalise_with_map(raw: str) -> tuple[str, tuple[int, ...], bool]:
    """NFC-normalise `raw` and return `(normalized, char_map, exact)`.

    `char_map[i]` is the index in `raw` where the character `normalized[i]` came
    from. Both strings are cut at the same combining-sequence boundaries, so the
    map is monotonic and `char_map[i]` doubles as the exclusive raw end of the
    preceding character.

    The text is normalised one combining sequence at a time — a starter plus the
    combining marks that follow it. Splitting there is safe for every script in
    this corpus, and the result is verified against `NFC(raw)` before it is
    returned. `exact` is False only if that verification fails, in which case the
    identity map is returned instead: matching then happens on the raw string
    (slightly worse recall on that one document) but **offsets stay correct**.
    Degrade, never drift.
    """
    parts: list[str] = []
    char_map: list[int] = []
    i, n = 0, len(raw)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(raw[j]):
            j += 1
        chunk = unicodedata.normalize("NFC", raw[i:j])
        parts.append(chunk)
        char_map.extend([i] * len(chunk))
        i = j

    normalized = "".join(parts)
    if normalized != unicodedata.normalize("NFC", raw):
        return raw, tuple(range(len(raw))), False
    return normalized, tuple(char_map), True


@dataclass(frozen=True)
class Document:
    """One source document. `raw` is immutable and is the only offset space."""

    doc_id: str
    raw: str
    path: Path | None = field(default=None, compare=False)

    # ── derived views · MATCHING ONLY ─────────────────────────────────────────
    @cached_property
    def _nfc(self) -> tuple[str, tuple[int, ...], bool]:
        return normalise_with_map(self.raw)

    @property
    def normalized(self) -> str:
        """NFC form of `raw`. Never emit an index computed on this string."""
        return self._nfc[0]

    @property
    def char_map(self) -> tuple[int, ...]:
        """`char_map[i]` = index in `raw` of the character `normalized[i]`."""
        return self._nfc[1]

    @property
    def nfc_map_exact(self) -> bool:
        """False if chunk-wise NFC did not reproduce `NFC(raw)` (identity fallback)."""
        return self._nfc[2]

    @cached_property
    def _inverse_map(self) -> tuple[int, ...]:
        """`inv[r]` = smallest normalized index whose source is at or after raw `r`."""
        cmap = self.char_map
        inv = [0] * (len(self.raw) + 1)
        k = 0
        for r in range(len(self.raw) + 1):
            while k < len(cmap) and cmap[k] < r:
                k += 1
            inv[r] = k
        return tuple(inv)

    @property
    def is_nfc(self) -> bool:
        return self.raw == self.normalized

    # ── the safe accessors ───────────────────────────────────────────────────
    def slice(self, start: int, end: int) -> str:
        """`raw[start:end]`, with the out-of-range case made loud instead of empty."""
        if not (0 <= start <= end <= len(self.raw)):
            raise OffsetError(
                f"{self.doc_id}: span [{start},{end}] out of range for a "
                f"{len(self.raw)}-char document"
            )
        return self.raw[start:end]

    def to_raw(self, norm_idx: int) -> int:
        """Map an index on `.normalized` back to `.raw`. Inclusive or exclusive."""
        cmap = self.char_map
        if norm_idx == len(cmap):
            return len(self.raw)
        if not (0 <= norm_idx < len(cmap)):
            raise OffsetError(
                f"{self.doc_id}: normalized index {norm_idx} outside "
                f"[0,{len(cmap)}]"
            )
        return cmap[norm_idx]

    def to_raw_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a span on `.normalized` back to `.raw`. Use this, not to_raw twice."""
        return self.to_raw(start), self.to_raw(end)

    def to_norm(self, raw_idx: int) -> int:
        """Map an index on `.raw` onto `.normalized`, for matching."""
        if not (0 <= raw_idx <= len(self.raw)):
            raise OffsetError(
                f"{self.doc_id}: raw index {raw_idx} outside [0,{len(self.raw)}]"
            )
        return self._inverse_map[raw_idx]

    def to_norm_span(self, start: int, end: int) -> tuple[int, int]:
        return self.to_norm(start), self.to_norm(end)

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def from_path(cls, path: str | Path, doc_id: str | None = None) -> "Document":
        p = Path(path)
        return cls(doc_id=doc_id or p.stem, raw=read_raw(p), path=p)

    def __len__(self) -> int:
        return len(self.raw)

    def __repr__(self) -> str:  # keep a 40kB document out of tracebacks
        return (
            f"Document(doc_id={self.doc_id!r}, len={len(self.raw)}, "
            f"nfc={self.is_nfc})"
        )


@dataclass(frozen=True)
class AnnotatedDocument(Document):
    """A `Document` that also carries labels — gold or silver.

    A subtype so that `load_gold()` / `load_silver()` satisfy the documented
    `-> list[Document]` contract while still handing callers the annotations they
    actually need. `entities` is a tuple of plain dicts in submission shape.
    """

    entities: tuple[dict, ...] = ()

    # `entities` holds dicts, so the generated field-wise hash would raise. Hash
    # on identity instead, so an AnnotatedDocument can still go in a set.
    def __hash__(self) -> int:
        return hash((self.doc_id, self.raw))

    def __repr__(self) -> str:
        return (
            f"AnnotatedDocument(doc_id={self.doc_id!r}, len={len(self.raw)}, "
            f"entities={len(self.entities)}, nfc={self.is_nfc})"
        )
