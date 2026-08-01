"""Pha 3 — staging/norm/ → kb.sqlite + manifest.json."""

from __future__ import annotations

from pathlib import Path

from smart_medic.kb.load import manifest, writer

__all__ = ["manifest", "run", "writer"]


def run(*, out: str | None = None) -> dict:
    out_path = Path(out) if out else None
    stats = writer.build(out_path)
    mf = manifest.write(out_path)
    return {"stats": stats, "manifest": mf}
