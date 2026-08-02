"""Hiệu chỉnh ngưỡng tin cậy của tagger — **không bao giờ trên `gold_real`**.

★ MỘT DỰ ĐOÁN SAI, VÀ SỐ ĐO ĐÃ SỬA NÓ
──────────────────────────────────────
Sau kết quả âm của Phase 4, dự đoán ban đầu là *"ngưỡng sẽ không cứu được gì:
model **tự tin sai** trên văn bản ngoài miền chứ không phải thiếu tự tin"*.

Đo trên `gold_batch1`, biên độ `logP(nhãn thắng) − logP(O)` trung bình trên
token của mỗi span:

    span ĐÚNG  n=535   p10 4,11   trung vị 7,59   p90 9,47
    span THỪA  n=249   p10 0,65   trung vị 4,82   p90 8,06

Hai phân bố **tách nhau rõ**. Cắt ở 5,0 nâng precision 0,682 → 0,788 mà vẫn giữ
439/535 span đúng. Dự đoán sai; ngưỡng là knob thật.

★ HIỆU CHỈNH TRÊN ĐÂU
`gold_real` là **cổng** — quy tắc §5.7 cấm dùng nó làm nguồn. Dev tổng hợp thì
vô dụng ở đây: model đạt F1 0,97 trên đó nên mọi ngưỡng > 0 đều làm tệ đi, và nó
**không thể nhìn thấy** hiện tượng bắn thừa vốn chỉ xuất hiện ngoài miền.

Nên quét trên **`gold_batch1`**: văn bản lâm sàng thật, ngoài miền, 858 span, và
**không phải cổng**. Đây đúng vai trò kế hoạch giao cho nó (§1.3).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.config import DATA_DIR

CALIB_GOLD = DATA_DIR / "probe" / "gold_batch1"
GRID = (0.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)


@dataclass(slots=True)
class Point:
    threshold: float
    final: float
    precision: float
    recall: float


def sweep(
    grid: tuple[float, ...] = GRID,
    *,
    gold: Path | None = None,
    model_weight: float = 1.0,
) -> list[Point]:
    """Quét ngưỡng, chấm bằng chính bộ chấm thật (arbiter + enricher đầy đủ)."""
    from smart_medic.eval.harness import score_gold_set

    out: list[Point] = []
    prev_thr = os.environ.get("SMK_TAGGER_THRESHOLD")
    prev_w = os.environ.get("SMK_ARBITER_MODEL_WEIGHT")
    try:
        os.environ["SMK_ARBITER_MODEL_WEIGHT"] = str(model_weight)
        for t in grid:
            os.environ["SMK_TAGGER_THRESHOLD"] = str(t)
            _reset_caches()
            r = score_gold_set(gold or CALIB_GOLD, b=200)
            out.append(
                Point(
                    t,
                    round(r.report.final, 4),
                    round(r.report.precision, 4),
                    round(r.report.recall, 4),
                )
            )
            print(
                f"  ngưỡng {t:4.1f}: final {out[-1].final:.4f} · P {out[-1].precision:.3f}"
                f" · R {out[-1].recall:.3f}"
            )
    finally:
        _restore("SMK_TAGGER_THRESHOLD", prev_thr)
        _restore("SMK_ARBITER_MODEL_WEIGHT", prev_w)
        _reset_caches()
    return out


def _reset_caches() -> None:
    from smart_medic.stages import flags, tagger

    tagger.load.cache_clear()
    flags.load_flags.cache_clear()


def _restore(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def best(points: list[Point]) -> Point:
    """Ngưỡng cho `final` cao nhất; hoà thì lấy ngưỡng THẤP hơn (ít can thiệp hơn)."""
    return max(points, key=lambda p: (p.final, -p.threshold))


def write_threshold(threshold: float, ckpt: Path) -> None:
    """Ghi ngưỡng vào `smk_meta.json` — không đụng weights."""
    p = ckpt / "smk_meta.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    meta["threshold"] = threshold
    meta["threshold_calibrated_on"] = "gold_batch1"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
