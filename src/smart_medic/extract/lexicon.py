"""L3 · lane R · vocabulary the gazetteer structurally cannot contain.

`aho.py` matches names mined from ICD-10 and RxNorm. Those are registries of
formal nomenclature; the test set is not written in it. 47 of the 100 test
documents are patient-facing Q&A, and a patient writes "thuốc giảm đau", not
"paracetamol", and "ngứa", not "pruritus, unspecified".

Measured against `proxy_gold_test/` (20 hand-annotated test documents, 724
spans), on the run that shipped before this lane existed:

    missed THUỐC        33   of which 14 are class/lay names, 4 are vitamins
    missed TRIỆU_CHỨNG 134   of which 73 are two words or shorter
    density             14.3 spans/1k chars, against 19.0 in the annotations

Recall is the term that pays three times: under `penalised`, a missed entity
scores zero in `text`, `assertions` and `candidates` at once. Dropping 10% of
entities costs 2.99 + 2.99 + 1.00 across the three.

## Why a separate lane and not more gazetteer rows

The gazetteer is a build artifact compiled by `scripts/build_gazetteer.py` from
the knowledge bases. An entry added there has to survive a rebuild, needs a code
to justify its row, and is invisible in review. This file's entries have no code
by nature — "thuốc lợi tiểu" is not an RxNorm ingredient — and the decision to
call a bare "đau" a symptom is exactly the kind that belongs in a reviewable YAML
next to its reasoning, not inside a generated JSON.

## The two guards that stop it over-generating

Recall bought with spurious spans is not recall: +10% spurious costs 6.10 points.

1. **Longest match wins, no overlaps within the lane.** "đau bụng" and "đau" both
   match at the same offset; only the longer one survives. Cross-lane overlap is
   resolved by `extract/__init__._merge`, which already prefers length.

2. **This lane yields to every other lane.** It sits last in `merge_priority`, so
   a gazetteer hit with a real code always wins the same span. That is the right
   order: `aho.py` knows a code, this file knows only a type.

Scores are deliberately below the gazetteer's. `decision/emit.py` holds the
threshold; this lane just proposes with less confidence than a KB-backed name.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..io.config import ConfigError, load_pipeline, require
from ..io.document import Document
from .spans import Span, TokenView

__all__ = ["spans", "load_lexicon", "SOURCE"]

SOURCE = "lexicon"

#: resources/lexicon_vi.yaml, relative to the package root.
_RESOURCE = Path(__file__).resolve().parents[3] / "resources" / "lexicon_vi.yaml"

#: YAML section → the type its entries carry. A section absent from this table is
#: a typo in the resource file, and is reported rather than skipped.
_SECTION_TYPES: dict[str, str] = {
    "drug_classes": "THUỐC",
    "vitamins": "THUỐC",
    "symptoms": "TRIỆU_CHỨNG",
}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


@lru_cache(maxsize=1)
def _rules() -> dict:
    return require(load_pipeline(), "extract.recall_floor.lexicon")


@lru_cache(maxsize=1)
def load_lexicon(path: str | None = None) -> tuple[tuple[tuple[str, ...], str], ...]:
    """`((token, ...), type)` pairs, longest phrase first.

    Sorting by length here is what makes "đau bụng" beat "đau" at the same offset
    without a second pass.
    """
    import yaml

    p = Path(path) if path else _RESOURCE
    if not p.exists():
        raise ConfigError(
            f"missing lexicon {p}\n"
            f"  This is a source resource, not a build artifact — it should be in "
            f"git. Restore it rather than regenerating it."
        )

    blob = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    unknown = sorted(set(blob) - set(_SECTION_TYPES))
    if unknown:
        raise ConfigError(
            f"{p}: unknown section(s) {unknown}. Add them to _SECTION_TYPES in "
            f"extract/lexicon.py with the type they carry, or fix the spelling — "
            f"silently ignoring a section would drop entries with no sign of it."
        )

    out: list[tuple[tuple[str, ...], str]] = []
    for section, etype in _SECTION_TYPES.items():
        for phrase in blob.get(section) or ():
            tokens = tuple(_fold(str(phrase)).split())
            if tokens:
                out.append((tokens, etype))

    # Longest first; ties alphabetical so the order is stable across runs.
    out.sort(key=lambda kv: (-len(kv[0]), kv[0]))
    return tuple(out)


def spans(doc: Document, view: TokenView) -> list[Span]:
    """Lexicon hits in `doc`, non-overlapping, longest match first."""
    cfg = _rules()
    if not bool(require(cfg, "enabled")):
        return []
    score = float(require(cfg, "score"))
    filler = re.compile(str(require(cfg, "phrase_filler")))

    texts = [_fold(t) for t in view.texts]
    n = len(texts)
    taken = [False] * n
    found: list[Span] = []

    for tokens, etype in load_lexicon():
        width = len(tokens)
        if width > n:
            continue
        for i in range(n - width + 1):
            if any(taken[i : i + width]):
                continue
            if tuple(texts[i : i + width]) != tokens:
                continue
            # A multi-token phrase must be ONE phrase: the same guard aho.py uses,
            # so "đau" + "bụng" across a sentence boundary is not a match.
            if width > 1 and not view.spans_one_phrase(i, i + width - 1, filler):
                continue
            start, end = view.raw_span(i, i + width - 1)
            found.append(
                Span(
                    start=start,
                    end=end,
                    type_dist={etype: 1.0},
                    score=score,
                    source=SOURCE,
                )
            )
            for k in range(i, i + width):
                taken[k] = True

    found.sort(key=lambda s: (s.start, s.end))
    return found
