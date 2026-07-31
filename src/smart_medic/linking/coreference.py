"""L4 · recover the RxNorm code behind a redacted drug name. SHIPPED OFF.

`extract/redacted.py` emits a THUỐC span for each run of asterisks and leaves
`candidates` empty. Sometimes the masked name is recoverable anyway: the same
drug appears unmasked elsewhere in the document, and the length of the asterisk
run equals the length of that name.

    document 100, offset 690:  "... Tuy nhiên, ******* là thuốc có tác dụng
                                 chống đông máu ..."
    document 100, offset 1114: "... việc tiếp tục sử dụng aspirin và ..."

Seven asterisks, `aspirin` is seven characters, RxCUI 1191. The organisers'
masking preserved length, which makes it a usable key.

## This is OFF, and the reason is not accuracy

Emitting a code for a masked span is a one-directional bet on a convention we
cannot observe. If the gold leaves `candidates` empty there — which is the
reading `extract/redacted.py` argues for, since publishing the code would defeat
the redaction — then every code we add turns a scored 1 into a 0. It cannot win
more cells than it can lose.

Submission H settles it without costing an extra attempt, because the three
columns carry different signatures:

    all three columns DOWN     gold does not annotate redactions at all
    text UP, J_candidates UP   gold annotates them, candidates empty  → stay off
    text UP, J_candidates DOWN gold annotates them WITH codes         → turn on

Only the third reading makes this module worth anything, and then it is worth
about +0.16 điểm: 12 of the 99 runs resolve, against ~982 matched pairs.

## Precision, stated honestly

Hand-checked all 16 candidates the length rule proposes before filtering:
11 right, 5 wrong — 0.688. Three filters then remove 4 of those 5, giving 0.917.
That 0.917 is measured ON THE CASES THE FILTERS WERE WRITTEN FROM, so it is a
fit, not an out-of-sample estimate; the honest number is closer to 0.688. Both
clear the break-even of 0.553 (see ADR 0006), which is why the conclusion holds
either way — but do not quote 0.917 as if it were validation.

The three filters, each from a real failure:

  * **salt fragments** — "Alverin citrate 40mg" made `citrate` a 7-character
    candidate that matched an unrelated 7-run. A bare counter-ion is never the
    drug being prescribed.
  * **lab-assay context** — "Định lượng Fibrinogen (Yếu tố I)" is an assay, not
    a prescription; the type was wrong upstream and the length matched.
  * **mid-name fragments** — a mention preceded by another lowercase word, with
    no prescribing verb before it, is usually the tail of a longer drug name.

The one surviving error is document 30, where `methadone` (9) matches a 9-run
that context shows is a first-generation antihistamine. Length alone cannot see
that; only reading the sentence can, which is the LLM route the PRD proposes and
this project's reproducibility constraint discourages.
"""

from __future__ import annotations

import re
import unicodedata

from ..io.config import load_pipeline, require

__all__ = ["recover_codes", "SALT_FRAGMENTS"]

#: Counter-ions and salt formers. These appear inside a drug's full name
#: ("Alverin citrate 40mg") and are never the prescribed substance on their own.
SALT_FRAGMENTS = frozenset(
    {
        "citrate", "sulfate", "sulphate", "tartrate", "maleate", "succinate",
        "fumarate", "phosphate", "hydrochloride", "acetate", "carbonate",
        "sodium", "potassium", "calcium", "chloride", "oxide", "hydroxid",
        "nitrate", "besylate", "mesylate",
    }
)

#: A mention right after one of these is a measured analyte, not a prescription.
_LAB_CUE = re.compile(
    r"(định lượng|xét nghiệm|nồng độ|kết quả|chỉ số|tỷ lệ)\s*$", re.IGNORECASE
)

#: Verbs and connectives that legitimately precede a prescribed drug.
_PRESCRIBING = re.compile(r"(dùng|uống|kê|đơn|tiêm|thuốc|và|,)\s*$", re.IGNORECASE)

#: Another lowercase word immediately before, i.e. probably a longer name's tail.
_MID_NAME = re.compile(r"[a-zà-ỹ]{4,}\s+$", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).lower().strip())


def recover_codes(raw: str, concepts: list[dict]) -> dict[int, tuple[str, ...]]:
    """Map `position[0]` of each resolvable redacted span to its RxNorm codes.

    `concepts` are the finalised records for ONE document — the function needs
    the document's own coded drug spans as the candidate pool, so it runs after
    `decision/emit.finalize`, not inside a lane.

    Returns an empty mapping when the feature is disabled, so the caller can
    apply it unconditionally.
    """
    cfg = require(load_pipeline(), "linking.masked_coreference")
    if not cfg.get("enabled", False):
        return {}

    pool: list[tuple[str, tuple[str, ...]]] = []
    for concept in concepts:
        if concept["type"] != "THUỐC" or not concept["candidates"]:
            continue
        name = _norm(concept["text"])
        if name in SALT_FRAGMENTS:
            continue
        before = _norm(raw[max(0, concept["position"][0] - 24) : concept["position"][0]])
        if _LAB_CUE.search(before):
            continue
        if _MID_NAME.search(before) and not _PRESCRIBING.search(before):
            continue
        pool.append((name, tuple(concept["candidates"])))

    out: dict[int, tuple[str, ...]] = {}
    for concept in concepts:
        text = concept["text"]
        if not text or set(text) != {"*"}:
            continue
        same_length = [codes for name, codes in pool if len(name) == len(text)]
        # Unique or nothing: two different drugs of the same length inside one
        # document means the length key has told us nothing.
        if same_length and len(set(same_length)) == 1:
            out[concept["position"][0]] = same_length[0]
    return out
