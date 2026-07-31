"""L3 · lane R · runs of `*` where a drug name has been redacted.

The organisers masked brand names in 30 of the 100 test documents, leaving runs
of asterisks in their place. 99 such runs; the shipped pipeline emits a span for
0 of them, because every other lane keys off letters.

## Why this is worth a lane of its own

A redacted span is the one concept type where all three scored terms are exactly
1.0 when the boundary is right:

    text        gold '**********' vs pred '**********'  →  WER 0     →  1.0
    assertions  gold [] and pred []                     →  J = 1
    candidates  gold [] and pred []                     →  J = 1

Nothing else in this corpus scores like that. An ordinary clinical span averages
q ≈ 0.83 on `text` and needs a correct code to score on `candidates`. Here the
annotator could not know the drug either, so "no code" is the *correct* answer
and a lane that emits nothing but the span gets full marks on two of three
columns for free.

## Evidence for the type

All 7 redaction runs inside `proxy_gold_test/` (20 hand-annotated test
documents) are labelled THUỐC with empty assertions and empty candidates, and in
all 7 the gold span is the whole run of asterisks — no surrounding whitespace,
no adjacent punctuation. The surrounding text agrees: the runs sit after "dùng",
"kê đơn thuốc", "Tiêm", "kem", "thuốc", or at the head of a treatment bullet.

That is a small sample, so the risk is stated plainly: if the real gold does not
annotate redactions, these 99 spans are spurious and dilute every document's
denominator by ~3.4%. Two things argue against that reading — the 7/7 agreement,
and the fact that a masked drug name is still a drug mention, which is what the
task asks for. It is a one-submission question either way, and the lane is a
single config flag.

## Guards

Runs of one or two asterisks are skipped. A single `*` is a footnote marker and
a `**` is markdown emphasis; the shortest run the annotators labelled is 8. The
lane also refuses a run that touches a letter on either side, which would mean
it is part of a word rather than standing in for one.
"""

from __future__ import annotations

import re

from ..io.config import load_pipeline, require, require_probability
from ..io.document import Document
from .spans import Span

#: A redaction is a run of asterisks standing alone. `(?<![^\W\d_])` and its
#: mirror reject a run glued to a letter — `xin*` is a typo, not a mask.
_RUN = re.compile(r"(?<![^\W\d_])\*{3,}(?![^\W\d_])")

__all__ = ["find_redacted"]


def find_redacted(doc: Document) -> list[Span]:
    """Emit one THUỐC span per redaction run in `doc.raw`.

    Offsets index `doc.raw` directly — there is no normalisation step to undo,
    since an asterisk survives every transform in `io/`.
    """
    cfg = require(load_pipeline(), "extract.recall_floor.redacted")
    if not cfg.get("enabled", False):
        return []

    min_len = int(require(cfg, "min_asterisks"))
    score = require_probability(cfg, "score")
    etype = str(require(cfg, "type"))

    found: list[Span] = []
    for match in _RUN.finditer(doc.raw):
        if len(match.group(0)) < min_len:
            continue
        found.append(
            Span(
                start=match.start(),
                end=match.end(),
                type_dist={etype: 1.0},
                score=score,
                source="redacted",
                codes=(),
            )
        )
    return found
