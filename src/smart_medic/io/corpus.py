"""L1 · loading the three corpora, with the known silver defect filtered at load.

    load_test()    100 documents · data/test/                        IMMUTABLE
    load_gold()    162 documents · restyled/annotations_gold/        the yardstick
    load_silver()  543 documents · synthetic + translated + restyled

`load_silver()` filters the 165 schema violations **as it loads**. It does not
regenerate the 543 files: doing that costs half a day and makes every number
already measured on this corpus irreproducible. See ADR 0004.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import repo_root
from .document import AnnotatedDocument, Document, read_raw
from .labels import LAB_TYPES

__all__ = [
    "LoadReport",
    "load_test",
    "load_gold",
    "load_silver",
    "test_dir",
    "gold_dir",
    "output_dir",
    "load_documents",
]

#: Submission records are `1.json` / `1.txt`. `run_manifest.json` is not a record.
_RECORD_NAME = re.compile(r"^\d+$")

_SILVER_KINDS = ("synthetic", "translated", "restyled")


def test_dir() -> Path:
    return repo_root() / "data" / "test"


def output_dir() -> Path:
    return repo_root() / "data" / "output"


def gold_dir() -> Path:
    return (
        repo_root()
        / "data"
        / "generated_medical_records"
        / "restyled"
        / "annotations_gold"
    )


def _silver_root() -> Path:
    return repo_root() / "data" / "generated_medical_records"


def _numbered(directory: Path, suffix: str) -> list[Path]:
    """Record files only, ordered numerically — `2.txt` before `10.txt`."""
    return sorted(
        (p for p in directory.glob(f"*{suffix}") if _RECORD_NAME.match(p.stem)),
        key=lambda p: int(p.stem),
    )


@dataclass
class LoadReport:
    """What the loader had to throw away. Printed, not swallowed."""

    documents: int = 0
    entities_in: int = 0
    entities_out: int = 0
    assertions_cleared: int = 0
    offset_mismatch_dropped: int = 0
    offenders: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.documents} docs · {self.entities_out}/{self.entities_in} entities "
            f"kept · {self.assertions_cleared} illegal lab assertions cleared · "
            f"{self.offset_mismatch_dropped} offset mismatches dropped"
        )


# ────────────────────────────── the plain corpus ──────────────────────────────
def load_documents(directory: Path | str, *, numbered: bool = False) -> list[Document]:
    """Load every `.txt` in a directory as a `Document`."""
    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"not a directory: {d}")
    paths = _numbered(d, ".txt") if numbered else sorted(d.glob("*.txt"))
    return [Document.from_path(p) for p in paths]


def load_test() -> list[Document]:
    """The 100 scored inputs, in numeric order. Never write to this directory."""
    docs = load_documents(test_dir(), numbered=True)
    if not docs:
        raise FileNotFoundError(f"no test documents under {test_dir()}")
    return docs


# ──────────────────────────── the annotated corpora ────────────────────────────
def _sanitise(
    entities: list, raw: str, label: str, report: LoadReport
) -> tuple[dict, ...]:
    """Drop what the schema forbids, keep the span. ~The 5 lines that matter.

    Two filters, in the order they matter:

    1. `assertions` on `TÊN_XÉT_NGHIỆM` / `KẾT_QUẢ_XÉT_NGHIỆM` are cleared. The
       flag is what violates the schema, not the span — dropping the entity would
       throw away 165 perfectly good training spans as well.
    2. An entity whose `raw[start:end] != text` is dropped outright. There is no
       safe repair: we do not know whether `position` or `text` is the wrong one.
       (0 such entities today. This is insurance against generator drift.)
    """
    kept: list[dict] = []
    for i, e in enumerate(entities):
        if not isinstance(e, dict):
            continue
        report.entities_in += 1
        pos = e.get("position")
        if (
            not isinstance(pos, (list, tuple))
            or len(pos) != 2
            or not all(isinstance(v, int) for v in pos)
            or not (0 <= pos[0] <= pos[1] <= len(raw))
            or raw[pos[0] : pos[1]] != e.get("text")
        ):
            report.offset_mismatch_dropped += 1
            report.offenders.append(f"{label}[{i}]: offset/text mismatch")
            continue

        if e.get("type") in LAB_TYPES and e.get("assertions"):
            e = {**e, "assertions": []}
            report.assertions_cleared += 1
            report.offenders.append(f"{label}[{i}]: cleared assertions on {e['type']}")

        kept.append(e)
    report.entities_out += len(kept)
    return tuple(kept)


def _load_annotated(
    pairs: list[tuple[Path, Path]], report: LoadReport
) -> list[AnnotatedDocument]:
    docs: list[AnnotatedDocument] = []
    for ann_path, txt_path in pairs:
        raw = read_raw(txt_path)
        entities = json.loads(ann_path.read_text(encoding="utf-8"))
        if not isinstance(entities, list):
            report.offenders.append(f"{ann_path.name}: top level is not a list")
            continue
        report.documents += 1
        docs.append(
            AnnotatedDocument(
                doc_id=ann_path.stem,
                raw=raw,
                path=txt_path,
                entities=_sanitise(entities, raw, ann_path.stem, report),
            )
        )
    return docs


def _pairs(ann_dir: Path, txt_dir: Path) -> list[tuple[Path, Path]]:
    out = []
    for ann in sorted(ann_dir.glob("*.json")):
        txt = txt_dir / f"{ann.stem}.txt"
        if txt.exists():
            out.append((ann, txt))
    return out


def load_gold(report: LoadReport | None = None) -> list[AnnotatedDocument]:
    """The 162 hand-adjudicated documents — the measuring stick.

    Gold is already clean (0 violations), so the sanitiser here is a tripwire: if
    `report.assertions_cleared` is ever non-zero, gold has regressed and every
    score measured against it is suspect.
    """
    rep = report if report is not None else LoadReport()
    txt = _silver_root() / "restyled" / "text"
    docs = _load_annotated(_pairs(gold_dir(), txt), rep)
    if not docs:
        raise FileNotFoundError(f"no gold documents under {gold_dir()}")
    return docs


def load_silver(report: LoadReport | None = None) -> list[AnnotatedDocument]:
    """All 543 generated documents, with the 165 known schema violations filtered.

    Includes `restyled/annotations` (the silver labels for the same texts that
    gold re-annotates). Train on this; measure on `load_gold()`.
    """
    rep = report if report is not None else LoadReport()
    pairs: list[tuple[Path, Path]] = []
    for kind in _SILVER_KINDS:
        ann = _silver_root() / kind / "annotations"
        txt = _silver_root() / kind / "text"
        if ann.is_dir() and txt.is_dir():
            pairs += _pairs(ann, txt)
    docs = _load_annotated(pairs, rep)
    if not docs:
        raise FileNotFoundError(f"no silver documents under {_silver_root()}")
    return docs
