"""Single definition of where the knowledge-base source files live, and how to read them.

`data/knowledge_base/` is flat: every file sits directly in it, no release
subdirectories. Import this module instead of hard-coding paths, so a future
re-layout is one edit rather than six.

    import sys; sys.path.insert(0, "<repo>/scripts")
    from kb_sources import KB, RXNCONSO, iter_rxnconso

RXNCONSO replaces the organisers' `RXNORM.csv`. That CSV was RXNCONSO converted
to comma-separated form with a lowercase header and a `SUPPRESS`/SAB filter
already applied — same 18 fields, same order. `iter_rxnconso()` yields the exact
dict shape `csv.DictReader` produced for it, so call sites did not have to change
shape when the CSV was dropped.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KB = REPO / "data" / "knowledge_base"

# ── RxNorm (flat, from the RxNorm_full release) ──────────────────────────────
RXNCONSO = KB / "RXNCONSO.RRF"          # concept names — replaces RXNORM.csv
RXNREL = KB / "RXNREL.RRF"              # relations: tradename_of, consists_of, …
RXNSTY = KB / "RXNSTY.RRF"              # semantic types — used to DROP T200
RXNATOMARCHIVE = KB / "RXNATOMARCHIVE.RRF"  # MERGED_TO_RXCUI for retired codes

# ── ICD-10 ───────────────────────────────────────────────────────────────────
ICD10_VI = KB / "ICD10.csv"             # ⚠ Vietnamese, 13,189 codes / 36,689 names.
                                        #   The competition's own list. IRREPLACEABLE:
                                        #   only 41.4% of its codes exist in the US
                                        #   ICD-10-CM file below.
ICD10CM_EN = KB / "icd10cm-codes-2027.txt"   # English labels, joined BY CODE to
                                             # enrich ICD10_VI (5,460 matches).

BRAND_TO_INGREDIENT = KB / "brand_to_ingredient.json"

#: RXNCONSO.RRF column order (RxNorm docs). The organisers' CSV used these exact
#: names, lowercased, as its header row.
RXNCONSO_COLS = (
    "rxcui", "lat", "ts", "lui", "stt", "sui", "ispref", "rxaui", "saui",
    "scui", "sdui", "sab", "tty", "code", "str", "srl", "suppress", "cvf",
)

#: The six vocabularies the organisers' RXNORM.csv carried. Passing `sabs=None`
#: reads all of RXNCONSO (1.20M rows) instead of this 638k-row subset.
CSV_SABS = frozenset({"RXNORM", "MTHSPL", "VANDF", "MSH", "CVX", "MTHCMSFRF"})


def iter_rxnconso(sabs=CSV_SABS, path=None):
    """Yield RXNCONSO rows as dicts keyed like the old RXNORM.csv header.

    `sabs=None` disables source filtering. Rows are yielded in file order.
    """
    p = Path(path) if path else RXNCONSO
    if not p.exists():
        raise SystemExit(
            f"thiếu {p} — bảng RxNorm. Giải nén bản RxNorm_full vào "
            f"{KB} (phẳng, không có thư mục con)."
        )
    n = len(RXNCONSO_COLS)
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            f = line.rstrip("\n").split("|")
            if len(f) < n:
                continue
            if sabs is not None and f[11] not in sabs:
                continue
            yield dict(zip(RXNCONSO_COLS, f[:n]))


def require(*paths) -> None:
    """Exit with a readable message if any source file is missing."""
    missing = [str(p) for p in paths if not os.path.exists(p)]
    if missing:
        raise SystemExit("thiếu file KB:\n  " + "\n  ".join(missing))
