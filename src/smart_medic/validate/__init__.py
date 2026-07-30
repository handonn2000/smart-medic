"""L6 · `validate/` — the hard gate. Nothing gets written that does not pass.

Generates no points; stops us losing points we already have. The cheapest item in
the project lives here: the schema constraint is worth **11.59** points for roughly
ten lines of code.

    schema.check(entities, raw, codes)   -> list[str]      audit, read-only
    schema.enforce(entities, raw, codes) -> (clean, report) repair, deterministic
    offsets.assert_exact(raw, entities)  -> None | raises  the byte-exact check
    emit_json.emit_corpus(items, out)    -> EmitReport     the ONLY writer

The split that matters: schema constraints are **repaired** silently (they are
model habits, and serialisation is the enforcement point); anything about
`position` is **raised** (never data noise, always a bug in a stage above).
"""
from __future__ import annotations

from . import emit_json, offsets, schema
from .emit_json import EmitReport, audit_dir, dumps, emit_corpus, emit_document
from .offsets import OffsetViolation, assert_exact
from .schema import CodeIndex, EnforceReport, enforce, load_code_index

__all__ = [
    "schema",
    "offsets",
    "emit_json",
    "CodeIndex",
    "load_code_index",
    "EnforceReport",
    "enforce",
    "OffsetViolation",
    "assert_exact",
    "EmitReport",
    "emit_document",
    "emit_corpus",
    "audit_dir",
    "dumps",
]
