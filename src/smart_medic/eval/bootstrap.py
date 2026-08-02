"""Khoảng tin cậy bằng **paired bootstrap trên tài liệu**.

★ VÌ SAO PHẢI CÓ MODULE NÀY
────────────────────────────
`gold_real` chỉ có **9 file**. Một con số `final` trên n = 9 mà không có khoảng
tin cậy thì không phân biệt được "cải thiện" với "may". Dự án đã có bằng chứng
đắt về đúng chuyện này: cùng một hệ thống, bộ 3 file cho `0,530` còn bộ 9 file
cho `0,407` — chênh 0,12 hoàn toàn do bộ đo, không do hệ thống.

Vì vậy `docs/synth-corpus-plan-v2.md` §5 quy tắc 8: **không công bố số nào không
kèm khoảng tin cậy**.

★ PAIRED, KHÔNG PHẢI HAI KHOẢNG RỜI
────────────────────────────────────
So hai hệ bằng cách xem hai khoảng tin cậy có chồng lấn không là **phép thử yếu
hơn hẳn** và hay bỏ sót cải thiện thật. Hai hệ chạy trên **cùng bộ tài liệu**,
nên phần lớn phương sai là "file này khó, file kia dễ" — nguồn phương sai *chung*
cho cả hai. Lấy mẫu lại **cùng một danh sách chỉ số file** cho cả hai rồi mới trừ
sẽ khử được nó:

    với mỗi lần lấy mẫu b:
        idx = [rút ngẫu nhiên có hoàn lại n chỉ số]
        Δ_b  = final(mới, idx) − final(gốc, idx)     ← cùng idx cho cả hai
    CI = phân vị 2,5% và 97,5% của {Δ_b}

Tham chiếu: Berg-Kirkpatrick, Burkett & Klein, *An Empirical Investigation of
Statistical Significance in NLP* (EMNLP 2012); Efron & Tibshirani (1993).

★ TẤT ĐỊNH
───────────
`random.Random(SEED)` chứ không phải `random` toàn cục — số không đổi giữa các
lần chạy, giữa các tiến trình, và không bị thư viện khác giành. Không dùng numpy
vì dependency lõi chỉ có PyYAML (ràng buộc tái lập, PRD §5).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Ghim cứng. Đổi giá trị này là đổi mọi con số đã công bố — đừng đổi.
SEED = 20260802
B_DEFAULT = 10_000
ALPHA = 0.05


@dataclass(slots=True)
class Interval:
    """Khoảng tin cậy phân vị, kèm điểm ước lượng trên mẫu gốc."""

    point: float
    lo: float
    hi: float
    b: int = B_DEFAULT
    seed: int = SEED

    @property
    def excludes_zero(self) -> bool:
        """Toàn khoảng nằm cùng một phía của 0 — dấu hiệu Δ không phải nhiễu."""
        return self.lo > 0.0 or self.hi < 0.0

    def as_dict(self) -> dict:
        return {
            "point": round(self.point, 6),
            "lo": round(self.lo, 6),
            "hi": round(self.hi, 6),
            "excludes_zero": self.excludes_zero,
            "B": self.b,
            "seed": self.seed,
        }


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Phân vị kiểu nội suy tuyến tính. `sorted_vals` phải đã sắp tăng."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _resample_indices(n: int, b: int, seed: int) -> list[list[int]]:
    """`b` mẫu bootstrap, mỗi mẫu `n` chỉ số rút có hoàn lại.

    Sinh **một lần** rồi dùng chung cho cả hai hệ — đó chính là chữ *paired*.
    """
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(b)]


def _mean(values: list[float], idx: list[int]) -> float:
    return sum(values[i] for i in idx) / len(idx)


def ci_mean(values: list[float], *, b: int = B_DEFAULT, seed: int = SEED) -> Interval:
    """CI 95% cho trung bình của một dãy điểm theo file."""
    if not values:
        return Interval(0.0, 0.0, 0.0, b, seed)
    point = sum(values) / len(values)
    draws = sorted(_mean(values, idx) for idx in _resample_indices(len(values), b, seed))
    return Interval(
        point, _percentile(draws, ALPHA / 2), _percentile(draws, 1 - ALPHA / 2), b, seed
    )


def ci_paired_delta(
    base: list[float], new: list[float], *, b: int = B_DEFAULT, seed: int = SEED
) -> Interval:
    """CI 95% cho `mean(new) − mean(base)`, lấy mẫu lại **cùng danh sách file**.

    `base` và `new` phải cùng độ dài và **cùng thứ tự file** — người gọi có trách
    nhiệm căn theo tên, xem `harness.paired_finals`.
    """
    if len(base) != len(new):
        raise ValueError(f"hai dãy khác độ dài: {len(base)} vs {len(new)}")
    if not base:
        return Interval(0.0, 0.0, 0.0, b, seed)
    point = sum(new) / len(new) - sum(base) / len(base)
    draws = sorted(
        _mean(new, idx) - _mean(base, idx) for idx in _resample_indices(len(base), b, seed)
    )
    return Interval(
        point, _percentile(draws, ALPHA / 2), _percentile(draws, 1 - ALPHA / 2), b, seed
    )
