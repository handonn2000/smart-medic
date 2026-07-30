"""L4b · ICD-10 — a code for a diagnosis the gazetteer did not match exactly.

## Why this is a free bet, and only here

For an entity the scorer has already MATCHED, `candidates` scores
`|G ∩ P| / |G ∪ P|`. When gold carries a code and we emit none, that is `0`. When
gold carries a code and we emit the *wrong* one, that is also `0`. **Emitting a
wrong code on a span we were leaving empty costs nothing**, while a right one is
worth a full 1. The whole risk sits in the other case: gold empty and we emit
something turns a 1 into a 0.

Measured 2026-07-30 on 162 gold, the 528 matched CHẨN_ĐOÁN spans we left empty:

    gold HAS a code   513  (97.2%)   ← wrong guess free, right guess +1
    gold is empty      15  ( 2.8%)   ← any guess loses a point we already had

97.2 : 2.8 is why this module retrieves rather than abstains, and why the
similarity floor is low rather than cautious. `decision.q0` in
`configs/pipeline.yaml` carries the same fact from the other direction:
P(gold empty | CHẨN_ĐOÁN) = 0.0521.

## Why pure Python and not the dense index the README specifies

`linking/README.md` calls for a flat 45 MB dense matrix, which needs a sentence
encoder, which needs torch — not installed, and adding it makes the organisers'
re-run (the one risk that cannot be bought back with points) strictly more
fragile. So both candidates were measured on the same 528 spans:

    sklearn TF-IDF char_wb(2,4) over 36.689 ICD10.csv names   +114 net spans
    this module: token IDF-cosine over the existing gazetteer  +125 net spans, 40 ms

Pure Python wins on the metric AND adds no dependency, so the README's decision 1
is superseded by measurement — noted here rather than silently diverging.

It also honours the README's real point ("build once, read twice"): the candidate
space is the gazetteer `extract/aho.py` already loaded, filtered to entries whose
first code looks like an ICD-10 code. No second index, no second artifact.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from ..extract.aho import load_gazetteer
from ..extract.spans import tokenize_key
from ..io.config import load_pipeline, require

__all__ = ["IcdIndex", "load_icd_index", "retrieve"]

#: An ICD-10 code is a letter followed by a digit. Cheap, and it is the only thing
#: that separates an ICD entry from an RxCUI in the merged gazetteer.
_ICD_CODE = re.compile(r"^[A-Z]\d")


@dataclass(frozen=True)
class IcdIndex:
    """Inverted token index over the ICD-coded slice of the gazetteer."""

    codes: tuple[tuple[str, ...], ...]
    idf: dict[str, float]
    postings: dict[str, tuple[int, ...]]
    norms: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.codes)


@lru_cache(maxsize=1)
def load_icd_index() -> IcdIndex:
    """Build the index from the gazetteer already on disk. ~40 ms, cached."""
    entries = [
        e for e in load_gazetteer().entries if e.codes and _ICD_CODE.match(e.codes[0])
    ]
    df: Counter = Counter()
    for e in entries:
        df.update(set(e.key))
    n = len(entries) or 1
    idf = {w: math.log(1 + n / (1 + c)) for w, c in df.items()}

    posting: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        for w in set(e.key):
            posting[w].append(i)

    norms = tuple(
        math.sqrt(sum(idf.get(w, 0.0) ** 2 for w in set(e.key))) or 1.0 for e in entries
    )
    return IcdIndex(
        codes=tuple(e.codes for e in entries),
        idf=idf,
        postings={w: tuple(v) for w, v in posting.items()},
        norms=norms,
    )


def _min_similarity() -> float:
    return float(require(load_pipeline(), "linking.icd_retrieval.min_similarity"))


def _symptom_bonus() -> float:
    return float(
        require(load_pipeline(), "linking.icd_retrieval.symptom_chapter_bonus")
    )


def retrieve(
    surface: str,
    *,
    index: IcdIndex | None = None,
    min_similarity: float | None = None,
    prefer_symptom_chapter: bool = False,
) -> tuple[str, ...]:
    """Best ICD code set for `surface`, or `()` below the similarity floor.

    Cosine over IDF-weighted token sets. Ties break on (−score, first code, index)
    so two builds of one commit cannot disagree — an unstable tie-break here would
    silently break the byte-identical archive guarantee (ADR 0005).

    `prefer_symptom_chapter` multiplies R00–R99 candidates by
    `linking.icd_retrieval.symptom_chapter_bonus`. Cosine alone systematically
    picks the wrong code for a bare symptom word, because a rare disease name
    containing that word carries far more IDF than the plain symptom entry:

        "sốt"  → A68   (relapsing fever)          instead of R50  (fever)
        "nôn"  → Y53.7 (poisoning by emetics)     instead of R11  (nausea/vomiting)
        "mụn"  → B07   (viral warts)              instead of a skin-finding code

    Chapter XVIII (R00–R99) is literally titled "Symptoms, signs and abnormal
    clinical findings", so for a TRIỆU_CHỨNG span it is the chapter the code
    should come from. This is a preference, not a filter: a symptom whose best
    match is a real disease code still gets it when the margin is large enough.
    """
    idx = index if index is not None else load_icd_index()
    floor = _min_similarity() if min_similarity is None else min_similarity
    query = set(tokenize_key(surface))
    if not query or not len(idx):
        return ()

    acc: dict[int, float] = defaultdict(float)
    for w in query:
        weight = idx.idf.get(w)
        if weight is None:
            continue
        w2 = weight * weight
        for i in idx.postings[w]:
            acc[i] += w2
    if not acc:
        return ()

    bonus = _symptom_bonus() if prefer_symptom_chapter else 1.0
    qnorm = math.sqrt(sum(idx.idf.get(w, 0.0) ** 2 for w in query)) or 1.0

    def ranked(i: int) -> float:
        base = acc[i] / (idx.norms[i] * qnorm)
        return base * bonus if idx.codes[i][0].startswith("R") else base

    best = min(acc, key=lambda i: (-ranked(i), idx.codes[i][0], i))
    # The floor is applied to the UNBOOSTED similarity: the bonus decides which
    # candidate wins, never whether a weak match is good enough to emit.
    score = acc[best] / (idx.norms[best] * qnorm)
    return idx.codes[best] if score >= floor else ()
