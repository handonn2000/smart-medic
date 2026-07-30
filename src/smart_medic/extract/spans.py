"""L3 · the `Span` contract, and the token view every lane matches against.

Two things live here because all three recall-floor lanes (`aho`, `labvalues`,
`kvspan`) need them and none of them owns them.

**`Span`** is the layer's output type. It carries a type DISTRIBUTION and a
score, never a decision: `decision/emit.py` is the only place allowed to compare
that score against a threshold.

**`TokenView`** is the answer to the offset trap. `position` in the submission
indexes the ORIGINAL, un-normalised string, but matching a gazetteer against the
original string loses every document that is not in NFC — 20/100 test files and
41/162 gold files. So matching happens on `doc.normalized` and every span is
mapped back with `Document.to_raw_span()` before it leaves this module. Nothing
here returns an index in normalised space.

The view is a token sequence, not a character stream, and that is a deliberate
choice with three consequences:

1. **Word boundaries are free.** A character-level automaton matches "ho" inside
   "hoặc" and "hồng cầu"; a token-level one cannot. The gazetteer holds ~50k
   names, many of them ordinary Vietnamese words, so this is not a nicety.
2. **Line-wrapped names still match.** `restyled/` wraps mid-phrase — one gold
   span is literally `"tim \nenzym"`. Tokens skip the whitespace between them, so
   the wrap costs nothing.
3. **The automaton fits in memory.** Character-level over 50k names is ~1.5M
   Python dict nodes; token-level is ~300k, and its alphabet is interned strings.

Tokens come from `layout.rules.token`, the same pattern `boundary_priors` uses,
so a gazetteer key and a document are cut at identical places. The pattern's
numeric alternative comes first, which is what keeps `4,7` one token instead of
`4` and `7` — a decimal comma split turns one lab result into two wrong spans.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from ..io.document import Document
from ..layout.rules import LayoutRules, default_rules

__all__ = ["Span", "Token", "TokenView", "tokenize", "merge_type_dist"]

#: Line-break shapes, matched explicitly. `str.splitlines()` also breaks on \v,
#: \f and U+2028 — characters the organisers' scorer reads as ordinary text.
_EOL = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class Span:
    """One candidate entity. Offsets index `Document.raw`, always.

    `type_dist` is a distribution over the five labels, not a label:
    `extract/` proposes, `decision/` decides. `score` is P(this is an entity).
    """

    start: int
    end: int
    type_dist: dict[str, float]
    score: float
    source: str
    codes: tuple[str, ...] = ()
    cluster_id: int | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.start < self.end):
            raise ValueError(f"degenerate span [{self.start},{self.end}]")

    @property
    def length(self) -> int:
        return self.end - self.start

    def text(self, doc: Document) -> str:
        """The one legal way to get a span's text: slice `raw`, never `normalized`."""
        return doc.slice(self.start, self.end)

    def argmax_type(self) -> str:
        """Type is argmax, never hedged — emitting two types costs 1.29 points."""
        return max(self.type_dist.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def confidence(self) -> float:
        return max(self.type_dist.values()) if self.type_dist else 0.0


def merge_type_dist(
    parts: list[tuple[dict[str, float], float]]
) -> dict[str, float]:
    """Weighted average of type distributions, renormalised. Sorted for stability."""
    total: dict[str, float] = {}
    mass = 0.0
    for dist, weight in parts:
        if weight <= 0:
            continue
        mass += weight
        for label, p in dist.items():
            total[label] = total.get(label, 0.0) + weight * p
    if not total or mass <= 0:
        return {}
    scale = sum(total.values())
    return {k: total[k] / scale for k in sorted(total)}


# ─────────────────────────────── the token view ───────────────────────────────
@dataclass(frozen=True)
class Token:
    """One token of `doc.normalized`. `text` is lowercased; offsets are not."""

    text: str
    start: int          # index into doc.normalized
    end: int            # index into doc.normalized, exclusive


@dataclass(frozen=True)
class TokenView:
    """`doc.normalized` as tokens, with the mapping back to `doc.raw`.

    Never hand a caller an index from this class without going through
    `raw_span()`. That is the whole reason the class exists.
    """

    doc: Document
    tokens: tuple[Token, ...]
    _texts: tuple[str, ...] = field(repr=False, default=())

    @property
    def texts(self) -> tuple[str, ...]:
        return self._texts

    def __len__(self) -> int:
        return len(self.tokens)

    def raw_span(self, i: int, j: int) -> tuple[int, int]:
        """Raw offsets covering tokens `i..j` inclusive. The only exit door."""
        return self.doc.to_raw_span(self.tokens[i].start, self.tokens[j].end)

    def gap(self, i: int) -> str:
        """The normalised text between token `i` and token `i+1`."""
        return self.doc.normalized[self.tokens[i].end : self.tokens[i + 1].start]

    def spans_one_phrase(self, i: int, j: int, allowed: re.Pattern) -> bool:
        """True if tokens `i..j` are separated only by `allowed` filler.

        Rejects a match that jumps a sentence end or a blank line. Without this,
        a two-word gazetteer name matches across `". "` and across a paragraph
        break, and every such hit is a spurious span — and +10% spurious costs
        6.10 points.
        """
        for k in range(i, j):
            filler = self.gap(k)
            if not allowed.fullmatch(filler):
                return False
            if len(_EOL.findall(filler)) > 1:
                return False
        return True

    def token_at_or_after(self, norm_offset: int) -> int:
        """Index of the first token starting at or after a normalised offset."""
        lo, hi = 0, len(self.tokens)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.tokens[mid].start < norm_offset:
                lo = mid + 1
            else:
                hi = mid
        return lo


def tokenize(doc: Document, rules: LayoutRules | None = None) -> TokenView:
    """Tokenise `doc.normalized` with the layout token pattern."""
    r = rules or default_rules()
    norm = doc.normalized
    toks = tuple(
        Token(text=m.group(0).lower(), start=m.start(), end=m.end())
        for m in r.token.finditer(norm)
    )
    return TokenView(doc=doc, tokens=toks, _texts=tuple(t.text for t in toks))


@lru_cache(maxsize=256)
def tokenize_key(key: str) -> tuple[str, ...]:
    """Tokenise a gazetteer key with the SAME pattern the document uses.

    Cached because the lab lexicon is re-tokenised for every document otherwise.
    """
    return tuple(m.group(0).lower() for m in default_rules().token.finditer(key))
