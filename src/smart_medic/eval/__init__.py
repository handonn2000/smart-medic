"""Hạ tầng đánh giá pipeline giải bài — Phase 0 của `docs/synth-corpus-plan-v2.md`.

Tách khỏi `stages/` có chủ đích: đây là **cái thước**, không phải thứ được đo.
Trộn hai thứ vào một package là cách chắc chắn nhất để một ngày nào đó phép đo
đi vay hàm của pipeline rồi cùng sai theo.
"""

from smart_medic.eval.bootstrap import (
    B_DEFAULT,
    SEED,
    Interval,
    ci_mean,
    ci_paired_delta,
)
from smart_medic.eval.harness import (
    SetResult,
    build_report,
    compare_reports,
    load_gold,
    score_gold_set,
)

__all__ = [
    "B_DEFAULT",
    "SEED",
    "Interval",
    "SetResult",
    "build_report",
    "ci_mean",
    "ci_paired_delta",
    "compare_reports",
    "load_gold",
    "score_gold_set",
]
