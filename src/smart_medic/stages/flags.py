"""Cờ bật/tắt thành phần pipeline — nạp `data/curated/pipeline.v1.yaml`.

★ CƠ CHẾ THAY CHO "DỪNG PHASE"
───────────────────────────────
`docs/synth-corpus-plan-v2.md` §4.0: cổng ĐỊNH TUYẾN không bao giờ làm dừng
công việc, nó chỉ quyết định **giá trị mặc định của một cờ**. Thành phần không
qua cổng vẫn được xây, vẫn có test, vẫn được commit — chỉ là mặc định `false`.

Nhờ vậy Phase 5 chọn cấu hình nộp bằng cách bật/tắt cờ, không phải bằng cách
revert code.

★ ÉP KIỂU KHI ĐỌC
Cấu hình sai kiểu (`labtest_extended: "true"` — chuỗi, không phải bool) là loại
lỗi hỏng-im-lặng: Python coi mọi chuỗi khác rỗng là `True`, kể cả `"false"`.
Nên đọc qua `flag()` / `weight()` có ép kiểu tường minh, đừng đọc dict trực tiếp.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

from smart_medic.kb.config import CURATED_DIR

FLAGS_FILE = "pipeline.v1.yaml"

# Mặc định khi thiếu file — bằng đúng hành vi trước Phase 1, để repo vẫn chạy
# được nếu ai đó xoá file cấu hình.
DEFAULTS: dict[str, Any] = {
    "labtest_extended": False,
    "tagger": False,
    "arbiter_model_weight": 0.0,
}

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off", ""})


@functools.lru_cache(maxsize=2)
def load_flags(path: Path | None = None) -> dict[str, Any]:
    p = path or CURATED_DIR / FLAGS_FILE
    if not p.is_file():
        return dict(DEFAULTS)
    return {**DEFAULTS, **(yaml.safe_load(p.read_text(encoding="utf-8")) or {})}


def active_config(path: Path | None = None) -> dict[str, Any]:
    """Cấu hình đang chạy + **NGUỒN của nó**.

    ★ BUG CONTAINER SỐ 4, PHÁT HIỆN Ở PHASE 6.
    Image `runtime` không copy `data/curated/`, nên trong container `load_flags`
    rơi về `DEFAULTS` — tức `labtest_extended=False` — và pipeline âm thầm tụt về
    cấu hình C0, mất đúng 0,053 điểm mà Phase 1 kiếm được. **Không ném lỗi, không
    cảnh báo.**

    Rơi về mặc định vẫn là hành vi ĐÚNG (repo phải chạy được khi thiếu file cấu
    hình). Cái sai là nó **im lặng**. Nên `smk solve` in cấu hình đang chạy ở mọi
    lần chạy, và Dockerfile chốt lại bằng một assert lúc build.
    """
    p = path or CURATED_DIR / FLAGS_FILE
    cfg = dict(load_flags(path))
    cfg["_source"] = str(p) if p.is_file() else "DEFAULTS (THIẾU file cấu hình)"
    cfg["_overrides"] = sorted(
        k for k in DEFAULTS if os.environ.get(f"SMK_{k.upper()}") is not None
    )
    return cfg


def _coerce_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in _TRUTHY:
            return True
        if low in _FALSY:
            return False
    raise ValueError(f"cờ {name!r} phải là bool, nhận {value!r}")


def flag(name: str, *, override: bool | None = None) -> bool:
    """Cờ bool. `override` để test bật/tắt mà không phải sửa file.

    Biến môi trường `SMK_<TÊN_CỜ>` thắng file — dùng khi Phase 5 chấm nhiều cấu
    hình trong một lần chạy mà không muốn ghi đè file cấu hình đang commit.
    """
    if override is not None:
        return override
    env = os.environ.get(f"SMK_{name.upper()}")
    if env is not None:
        return _coerce_bool(env, name)
    return _coerce_bool(load_flags().get(name, DEFAULTS.get(name, False)), name)


def weight(name: str) -> float:
    env = os.environ.get(f"SMK_{name.upper()}")
    raw = env if env is not None else load_flags().get(name, DEFAULTS.get(name, 0.0))
    return float(raw)
