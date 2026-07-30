"""L6 · serialisation — the point where the schema stops being a hope.

This is the difference between a **constraint** and an **expectation**. A model can
be prompted, fine-tuned and reminded not to put `isNegated` on a lab name; it will
still do it. Enforcing here means it cannot reach the file.

So no other layer may write a submission record. Everything goes through
`emit_document` / `emit_corpus`.

Format, from `validate/README.md`:

* one JSON **list** per document; an empty list is valid, a missing file is not
* `ensure_ascii=False`, UTF-8, **no BOM**, `\\n` at end of file
* `\\n` line endings regardless of platform — `newline="\\n"` on the write
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from ..io.config import load_pipeline, require
from ..io.document import Document
from . import offsets, schema
from .schema import CodeIndex, EnforceReport

#: Display limit for the error message. Not a threshold.
_MAX_LISTED = 10

__all__ = [
    "EmitReport",
    "dumps",
    "emit_document",
    "emit_corpus",
    "audit_dir",
]


@dataclass
class EmitReport:
    files_written: int = 0
    enforce: EnforceReport = field(default_factory=EnforceReport)
    entity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_entities(self) -> int:
        return sum(self.entity_counts.values())

    def density(self) -> float:
        """Entities per file — the input to `decision.emit_threshold`, not decoration."""
        return self.total_entities / self.files_written if self.files_written else 0.0

    def summary(self) -> str:
        return (
            f"{self.files_written} files · {self.total_entities} entities · "
            f"density {self.density():.2f}/file · {self.enforce.summary()}"
        )


def _json_settings() -> tuple[int, tuple[str, ...]]:
    cfg = require(load_pipeline(), "validate.json")
    return int(require(cfg, "indent")), tuple(require(cfg, "field_order"))


def _ordered(entity: dict, order: Sequence[str]) -> dict:
    out = {k: entity[k] for k in order if k in entity}
    out.update({k: v for k, v in entity.items() if k not in out})
    return out


def dumps(entities: Iterable[dict]) -> str:
    """The exact bytes we write: `ensure_ascii=False`, fixed field order, trailing newline."""
    indent, order = _json_settings()
    payload = [_ordered(e, order) for e in entities]
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def emit_document(
    doc: Document | str,
    entities: Iterable[dict],
    path: str | Path,
    *,
    codes: CodeIndex | None = None,
    strict_offsets: bool | None = None,
    report: EmitReport | None = None,
) -> EmitReport:
    """Enforce, then write one record. Raises rather than writing a bad offset."""
    pipeline = load_pipeline()
    if strict_offsets is None:
        strict_offsets = bool(require(pipeline, "validate.strict_offsets"))
    validate_cfg = require(pipeline, "validate")

    raw = doc.raw if isinstance(doc, Document) else doc
    label = doc.doc_id if isinstance(doc, Document) else Path(path).stem
    rep = report if report is not None else EmitReport()

    clean, _ = schema.enforce(
        entities,
        raw,
        codes,
        nesting_policy=require(validate_cfg, "nesting_policy"),
        drop_unknown_codes=bool(require(validate_cfg, "drop_unknown_codes")),
        report=rep.enforce,
    )

    # LAST, and loud: an offset mismatch is a bug in a stage above, never noise.
    if strict_offsets:
        offsets.assert_exact(raw, clean, label)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(clean), encoding="utf-8", newline="\n")

    rep.files_written += 1
    for e in clean:
        rep.entity_counts[e["type"]] = rep.entity_counts.get(e["type"], 0) + 1
    return rep


def emit_corpus(
    items: Iterable[tuple[Document | str, Iterable[dict]]],
    out_dir: str | Path,
    *,
    codes: CodeIndex | None = None,
    expect_ids: Sequence[str] | None = None,
    strict_offsets: bool | None = None,
) -> EmitReport:
    """Write one record per document. Every expected id must be present.

    A hole in `1.json … 100.json` is not a partial submission, it is a broken one:
    the organisers' scorer has no prediction to align against, so the document
    scores zero rather than being skipped.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rep = EmitReport()
    written: list[str] = []

    for doc, entities in items:
        doc_id = doc.doc_id if isinstance(doc, Document) else str(doc)
        emit_document(
            doc,
            entities,
            out / f"{doc_id}.json",
            codes=codes,
            strict_offsets=strict_offsets,
            report=rep,
        )
        written.append(doc_id)

    if expect_ids is not None:
        missing = [i for i in expect_ids if i not in set(written)]
        extra = [i for i in written if i not in set(expect_ids)]
        if missing or extra:
            raise ValueError(
                f"submission is incomplete: {len(missing)} missing "
                f"{missing[:_MAX_LISTED]}, {len(extra)} unexpected {extra[:_MAX_LISTED]}"
            )
    return rep


def audit_dir(
    pred_dir: str | Path,
    source_dir: str | Path,
    *,
    codes: CodeIndex | None = None,
) -> list[str]:
    """Re-check records already on disk against their sources.

    The acceptance criterion is stated on the written JSON, not on a variable in
    memory — this is the function that reads it back.
    """
    from ..io.document import read_raw

    pred = Path(pred_dir)
    src = Path(source_dir)
    errs: list[str] = []
    for p in sorted(pred.glob("*.json")):
        source = src / f"{p.stem}.txt"
        if not source.exists():
            continue
        try:
            entities = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errs.append(f"{p.name}: invalid JSON — {exc}")
            continue
        if not isinstance(entities, list):
            errs.append(f"{p.name}: top level must be a list")
            continue
        errs += schema.check(entities, read_raw(source), codes, p.name)
    return errs
