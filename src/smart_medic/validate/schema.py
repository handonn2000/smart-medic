"""L6 · the seven schema checks. The cheapest 11.59 points in the project.

| # | check                                                              | cost if dropped |
|---|--------------------------------------------------------------------|-----------------|
| 1 | `raw[start:end] == text`, byte-exact (see `offsets.py`)             | all 70.00, silent |
| 2 | `type` is one of the 5 labels                                        | entity discarded |
| 3 | `assertions` ⊆ 3 labels **and EMPTY** for the two lab types          | **11.59**       |
| 4 | `candidates` empty except `CHẨN_ĐOÁN` / `THUỐC`                      | 0.00 official, 2.36 plain |
| 5 | every code exists in the packaged KB                                 | an unlookupable code is a wrong code |
| 6 | no nested spans (0/7435 gold spans are nested)                       | schema violation |
| 7 | no duplicate `(start, end, type)`                                    | double-counted prediction |

Two different enforcement policies, and the difference is deliberate:

* **Repaired silently** — the schema constraints. They are model *habits*, and
  the enforcement point is serialisation. Clearing an illegal `isNegated` keeps
  the span, which is worth points; dropping the entity would not be.
* **Raised** — anything about `position`. That is never data noise, always a bug.

Check 3 is the one that pays. Leaking `isNegated` onto `TÊN_XÉT_NGHIỆM` and
`KẾT_QUẢ_XÉT_NGHIỆM` takes 70.00 down to 58.41 — roughly ten lines of code. The
silver corpus does it 165 times, which is exactly why it must be enforced here and
not hoped for in the model.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from ..io.config import ConfigError, kb_paths, load_pipeline, require
from ..io.labels import (
    ASSERTABLE_TYPES,
    ASSERTIONS,
    CODEABLE_TYPES,
    LAB_TYPES,
    REQUIRED_FIELDS,
    TYPES,
)
from . import offsets

__all__ = [
    "CodeIndex",
    "load_code_index",
    "EnforceReport",
    "check",
    "enforce",
]


# ────────────────────────────── check 5 · the KB ──────────────────────────────
@dataclass(frozen=True)
class CodeIndex:
    """Every code the packaged knowledge base can resolve."""

    icd: frozenset[str]
    rxcui: frozenset[str]

    def __contains__(self, code: object) -> bool:
        s = str(code)
        return s in self.icd or s in self.rxcui

    def kind(self, code: object) -> str:
        s = str(code)
        if s in self.icd:
            return "icd10"
        if s in self.rxcui:
            return "rxcui"
        return "unknown"

    def __len__(self) -> int:
        return len(self.icd) + len(self.rxcui)


def _read_icd_codes(path, header_row: int, code_column: str) -> set[str]:
    """`ICD10.csv` opens with a four-row title block; the header is row 5."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = rows[header_row - 1]
    try:
        col = header.index(code_column)
    except ValueError as exc:
        raise ConfigError(
            f"{path}: no {code_column!r} column in header row {header_row}: {header}"
        ) from exc
    out = set()
    for row in rows[header_row:]:
        if len(row) > col and row[col].strip():
            out.add(row[col].strip())
    return out


def _read_rxcuis(path) -> set[str]:
    """RXNCONSO.RRF is pipe-delimited; field 1 is the RXCUI."""
    out = set()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            i = line.find("|")
            if i > 0:
                out.add(line[:i])
    return out


@lru_cache(maxsize=1)
def load_code_index(use_cache: bool = True) -> CodeIndex:
    """Build (or reload) the set of resolvable codes.

    Cached under `data/artifacts/` because that directory is regenerable and
    gitignored. Raises if the KB is absent: a check that quietly turns itself off
    is worse than no check, since "every code exists in the KB" is the whole
    difference between a candidate and a guess.
    """
    paths = kb_paths()
    cache = paths["cache"]
    if use_cache and cache.exists():
        blob = json.loads(cache.read_text(encoding="utf-8"))
        return CodeIndex(
            icd=frozenset(blob["icd"]), rxcui=frozenset(blob["rxcui"])
        )

    missing = [str(paths[k]) for k in ("icd10_vi", "rxnconso") if not paths[k].exists()]
    if missing:
        raise ConfigError(
            "cannot verify candidate codes — missing knowledge-base file(s):\n  "
            + "\n  ".join(missing)
            + "\nPaths come from configs/pipeline.yaml `knowledge_base:`."
        )

    kb = require(load_pipeline(), "knowledge_base")
    icd = _read_icd_codes(
        paths["icd10_vi"],
        int(require(kb, "icd10_vi_header_row")),
        require(kb, "icd10_vi_code_column"),
    )
    rxcui = _read_rxcuis(paths["rxnconso"])

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"icd": sorted(icd), "rxcui": sorted(rxcui)}), encoding="utf-8"
    )
    return CodeIndex(icd=frozenset(icd), rxcui=frozenset(rxcui))


# ──────────────────────────────── enforcement ────────────────────────────────
@dataclass
class EnforceReport:
    """Exactly what the gate had to change. Counted, never swallowed."""

    entities_in: int = 0
    entities_out: int = 0
    dropped_malformed: int = 0
    dropped_bad_type: int = 0
    dropped_nested: int = 0
    dropped_duplicate: int = 0
    assertions_cleared_lab: int = 0
    assertions_dropped_unknown: int = 0
    candidates_cleared_uncodeable: int = 0
    candidates_dropped_unknown_code: int = 0
    notes: list[str] = field(default_factory=list)

    def __iadd__(self, other: "EnforceReport") -> "EnforceReport":
        for key, value in vars(other).items():
            if key == "notes":
                self.notes += value
            else:
                setattr(self, key, getattr(self, key) + value)
        return self

    @property
    def clean(self) -> bool:
        return (
            self.assertions_cleared_lab == 0
            and self.candidates_cleared_uncodeable == 0
            and self.dropped_bad_type == 0
            and self.dropped_malformed == 0
        )

    def summary(self) -> str:
        return (
            f"{self.entities_out}/{self.entities_in} entities · "
            f"lab assertions cleared {self.assertions_cleared_lab} · "
            f"uncodeable candidates cleared {self.candidates_cleared_uncodeable} · "
            f"unknown codes dropped {self.candidates_dropped_unknown_code} · "
            f"dropped malformed {self.dropped_malformed} / bad type "
            f"{self.dropped_bad_type} / nested {self.dropped_nested} / duplicate "
            f"{self.dropped_duplicate}"
        )


def check(
    entities: Iterable[dict],
    raw: str,
    codes: CodeIndex | None = None,
    label: str = "",
) -> list[str]:
    """All seven checks, read-only. Returns violations; empty means clean.

    This is the *audit* form — run it on the JSON already written to disk, which
    is the only place the constraint actually has to hold.
    """
    ents = list(entities)
    errs = offsets.check(raw, ents, label)
    prefix = label or "entity"
    seen: set[tuple[int, int, str]] = set()
    spans: list[tuple[int, int, int]] = []

    for i, e in enumerate(ents):
        where = f"{prefix}[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: entity must be an object, got {type(e).__name__}")
            continue

        for f in REQUIRED_FIELDS:
            if f not in e:
                errs.append(f"{where}: missing required field {f!r}")

        etype = e.get("type")
        if etype not in TYPES:
            errs.append(f"{where}: type {etype!r} is not one of the 5 allowed")

        asserts = e.get("assertions", [])
        if not isinstance(asserts, list):
            errs.append(f"{where}: assertions must be a list, got {asserts!r}")
        else:
            unknown = sorted(set(asserts) - ASSERTIONS)
            if unknown:
                errs.append(f"{where}: unknown assertions {unknown}")
            if asserts and etype in LAB_TYPES:
                errs.append(
                    f"{where}: type {etype} must have EMPTY assertions, got "
                    f"{asserts} — this is the 11.59-point constraint"
                )
            elif asserts and etype not in ASSERTABLE_TYPES:
                errs.append(f"{where}: type {etype} may not carry assertions")

        cands = e.get("candidates", [])
        if not isinstance(cands, list):
            errs.append(f"{where}: candidates must be a list, got {cands!r}")
        else:
            if cands and etype not in CODEABLE_TYPES:
                errs.append(
                    f"{where}: type {etype} must have EMPTY candidates, got {cands}"
                )
            if codes is not None:
                for c in cands:
                    if c not in codes:
                        errs.append(f"{where}: code {c!r} is not in the packaged KB")

        pos = e.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            key = (pos[0], pos[1], str(etype))
            if key in seen:
                errs.append(f"{where}: duplicate entity {key}")
            seen.add(key)
            if all(isinstance(v, int) for v in pos):
                spans.append((pos[0], pos[1], i))

    for a_start, a_end, ai in spans:
        for b_start, b_end, bi in spans:
            if ai >= bi:
                continue
            if a_start <= b_start and b_end <= a_end and (a_start, a_end) != (
                b_start,
                b_end,
            ):
                errs.append(
                    f"{prefix}: nested spans — [{a_start},{a_end}] contains "
                    f"[{b_start},{b_end}] (0/7435 gold spans are nested)"
                )
    return errs


def enforce(
    entities: Iterable[dict],
    raw: str,
    codes: CodeIndex | None = None,
    *,
    nesting_policy: str = "keep_longer",
    drop_unknown_codes: bool = True,
    report: EnforceReport | None = None,
) -> tuple[list[dict], EnforceReport]:
    """Return entities that satisfy the schema, plus a record of every change.

    Never touches `position`, and never rewrites `text`. Offsets are checked
    separately and raised on — see the module docstring for why.
    """
    rep = report if report is not None else EnforceReport()
    ents = [e for e in entities if isinstance(e, dict)]
    rep.entities_in += len(ents)

    kept: list[dict] = []
    for e in ents:
        etype = e.get("type")
        pos = e.get("position")

        if any(f not in e for f in REQUIRED_FIELDS) or not isinstance(
            pos, (list, tuple)
        ):
            rep.dropped_malformed += 1
            continue
        if etype not in TYPES:
            rep.dropped_bad_type += 1
            rep.notes.append(f"dropped entity with type {etype!r}")
            continue

        out = dict(e)

        # ── check 3 · the 11.59 points ───────────────────────────────────────
        asserts = out.get("assertions") or []
        if not isinstance(asserts, list):
            asserts = []
        known = [a for a in asserts if a in ASSERTIONS]
        if len(known) != len(asserts):
            rep.assertions_dropped_unknown += len(asserts) - len(known)
        if known and etype not in ASSERTABLE_TYPES:
            if etype in LAB_TYPES:
                rep.assertions_cleared_lab += 1
            known = []
        out["assertions"] = known

        # ── check 4 · candidates only where a code can exist ─────────────────
        cands = out.get("candidates") or []
        if not isinstance(cands, list):
            cands = []
        if cands and etype not in CODEABLE_TYPES:
            rep.candidates_cleared_uncodeable += 1
            cands = []
        # ── check 5 · every code must resolve in the packaged KB ─────────────
        if cands and codes is not None and drop_unknown_codes:
            resolvable = [c for c in cands if c in codes]
            if len(resolvable) != len(cands):
                rep.candidates_dropped_unknown_code += len(cands) - len(resolvable)
                rep.notes.append(
                    f"dropped unresolvable code(s) "
                    f"{sorted(set(map(str, cands)) - set(map(str, resolvable)))}"
                )
            cands = resolvable
        out["candidates"] = cands

        # dedupe on the pair the scorer aligns on
        out["position"] = [int(pos[0]), int(pos[1])]
        kept.append(out)

    kept = _dedupe(kept, rep)
    kept = _resolve_nesting(kept, rep, nesting_policy)
    rep.entities_out += len(kept)
    return kept, rep


def _dedupe(entities: list[dict], rep: EnforceReport) -> list[dict]:
    seen: set[tuple[int, int, str]] = set()
    out: list[dict] = []
    for e in entities:
        key = (e["position"][0], e["position"][1], e["type"])
        if key in seen:
            rep.dropped_duplicate += 1
            continue
        seen.add(key)
        out.append(e)
    return out


def _resolve_nesting(
    entities: list[dict], rep: EnforceReport, policy: str
) -> list[dict]:
    """Remove nested spans. 0/7435 gold spans nest, so the schema forbids it.

    `keep_longer` keeps the enclosing span. Ordering is by (start, -length, type)
    so the outcome is identical on every run — a non-deterministic tie-break here
    would make two runs of the same code produce different submissions.
    """
    if policy != "keep_longer":
        raise ValueError(f"unknown nesting_policy {policy!r}")

    ordered = sorted(
        entities, key=lambda e: (e["position"][0], -e["position"][1], e["type"])
    )
    kept: list[dict] = []
    for e in ordered:
        start, end = e["position"]
        contained = any(
            k["position"][0] <= start and end <= k["position"][1]
            and (k["position"][0], k["position"][1]) != (start, end)
            for k in kept
        )
        if contained:
            rep.dropped_nested += 1
            continue
        kept.append(e)
    return kept
