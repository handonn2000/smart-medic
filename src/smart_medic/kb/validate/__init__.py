"""Pha 4 — cổng chất lượng. FAIL HARD, không cảnh báo suông."""

from __future__ import annotations

from smart_medic.kb.validate import report, rules

__all__ = ["report", "rules", "run"]


def run(db=None) -> int:
    return report.run(db)
