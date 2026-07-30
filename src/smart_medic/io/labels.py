"""L1 · the competition's own label vocabulary. Not tunable, not a threshold.

These sets are the problem statement, so they live in code rather than in
`configs/` — there is no version of this project in which changing them is a
legitimate experiment. Both `io/corpus.py` (filtering silver at load) and
`validate/schema.py` (the hard gate) read them from here, so the vocabulary is
defined exactly once.

The constraint that pays: `assertions` must be EMPTY for `TÊN_XÉT_NGHIỆM` and
`KẾT_QUẢ_XÉT_NGHIỆM`. Leaking `isNegated` onto those two types costs 11.59 points
of the 70.00 ceiling. The silver corpus violates it 165 times.
"""
from __future__ import annotations

__all__ = [
    "TYPES",
    "ASSERTIONS",
    "ASSERTABLE_TYPES",
    "CODEABLE_TYPES",
    "LAB_TYPES",
    "REQUIRED_FIELDS",
]

#: The five entity types. Anything else is not a valid prediction.
TYPES = frozenset(
    {
        "TRIỆU_CHỨNG",
        "TÊN_XÉT_NGHIỆM",
        "KẾT_QUẢ_XÉT_NGHIỆM",
        "CHẨN_ĐOÁN",
        "THUỐC",
    }
)

#: The three assertion flags.
ASSERTIONS = frozenset({"isNegated", "isFamily", "isHistorical"})

#: The two types that may never carry an assertion — worth 11.59 points.
LAB_TYPES = frozenset({"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"})

#: The three types that may carry assertions.
ASSERTABLE_TYPES = TYPES - LAB_TYPES

#: The two types that may carry candidate codes. 67% of entities are not here,
#: which is why the candidates term is capped at 10.00 and not 40.00.
CODEABLE_TYPES = frozenset({"CHẨN_ĐOÁN", "THUỐC"})

#: Fields every entity must have.
REQUIRED_FIELDS = ("text", "type", "position")
