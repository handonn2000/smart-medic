"""Thống kê suy diễn cho so sánh A/B.

Vì sao bắt buộc phải có: dev set là **20 file**. Một chênh lệch 0,02 giữa hai
hệ nằm gọn trong nhiễu lấy mẫu, và đội nào cũng từng "cải tiến" một thứ rồi
thấy điểm nhích lên rồi kết luận sai. Bootstrap trả về khoảng, permutation test
trả về xác suất chênh lệch là ngẫu nhiên.

Cả hai đều **tất định theo seed** — cùng seed cho cùng con số trên mọi máy,
đúng ràng buộc NFR3 của dự án.
"""

from __future__ import annotations

import random
from typing import Callable, Sequence

Agg = Callable[[Sequence], float]


def bootstrap_ci(
    units: Sequence,
    agg: Agg,
    *,
    n_resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 20260728,
) -> tuple[float, float, float]:
    """Khoảng tin cậy percentile bootstrap, lấy mẫu lại **theo file**.

    Đơn vị lấy mẫu lại là file chứ không phải mention: các mention trong cùng
    một file tương quan mạnh (cùng thể loại, cùng bệnh, cùng người viết), coi
    chúng độc lập sẽ cho khoảng hẹp giả tạo.

    Trả ``(điểm, cận dưới, cận trên)``.
    """
    if not units:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(units)
    point = agg(units)
    draws = []
    for _ in range(n_resamples):
        sample = [units[rng.randrange(n)] for _ in range(n)]
        draws.append(agg(sample))
    draws.sort()
    lo = draws[int(alpha / 2 * n_resamples)]
    hi = draws[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    return point, lo, hi


def paired_permutation(
    units_a: Sequence,
    units_b: Sequence,
    agg: Agg,
    *,
    n_resamples: int = 10_000,
    seed: int = 20260728,
) -> tuple[float, float]:
    """Kiểm định hoán vị theo cặp cho ``agg(A) − agg(B)``.

    Cùng một tập file được chấm bởi hai hệ ⇒ dữ liệu **ghép cặp**. Giả thuyết
    H0: nhãn hệ A/hệ B trên mỗi file là hoán đổi được. Mỗi lần lặp, đảo ngẫu
    nhiên nhãn của từng file rồi tính lại chênh lệch.

    Trả ``(chênh lệch quan sát, p-value hai phía)``.
    """
    assert len(units_a) == len(units_b), "phải chấm trên cùng tập file"
    if not units_a:
        return 0.0, 1.0
    rng = random.Random(seed)
    observed = agg(units_a) - agg(units_b)
    n = len(units_a)
    hits = 0
    for _ in range(n_resamples):
        left, right = [], []
        for i in range(n):
            if rng.random() < 0.5:
                left.append(units_a[i])
                right.append(units_b[i])
            else:
                left.append(units_b[i])
                right.append(units_a[i])
        if abs(agg(left) - agg(right)) >= abs(observed) - 1e-12:
            hits += 1
    return observed, (hits + 1) / (n_resamples + 1)


def mde(units: Sequence, agg: Agg, *, seed: int = 20260728, n_resamples: int = 4000) -> float:
    """Minimum detectable effect thô: 2·độ lệch chuẩn bootstrap.

    Trả lời câu hỏi thực dụng "cải tiến phải lớn cỡ nào thì dev set 20 file mới
    nhìn thấy được". Nếu MDE = 0,04 thì đừng tin bất kỳ báo cáo +0,01 nào.
    """
    if not units:
        return 0.0
    rng = random.Random(seed)
    n = len(units)
    draws = [agg([units[rng.randrange(n)] for _ in range(n)]) for _ in range(n_resamples)]
    mu = sum(draws) / len(draws)
    var = sum((d - mu) ** 2 for d in draws) / max(1, len(draws) - 1)
    return 2.0 * var**0.5
