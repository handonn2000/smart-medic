"""Sinh "hệ giả lập" bằng cách làm hỏng gold theo tham số đã biết.

Vì sao cần: một benchmark chưa được kiểm chứng cũng vô dụng như không có
benchmark. Ở đây ta biết chính xác recall/precision/nhiễu biên đã bơm vào, nên
có thể **đối chiếu số benchmark đo được với số đã bơm** — nếu lệch thì lỗi nằm
ở benchmark chứ không phải ở model.

Lợi ích thứ hai: chạy được ngay khi chưa có hệ thật nào. Các hệ giả lập cũng
đóng vai trò **đường cơ sở tham chiếu** — một giải pháp mới mà thua
``recall=0.6, precision=0.9`` thì chưa đáng triển khai.

**Common random numbers.** Mỗi loại quyết định (giữ/bỏ mention, nhiễu biên, sai
type, bỏ mã…) rút từ một **luồng ngẫu nhiên riêng**, gieo bằng
``hash(seed, file, chỉ số mention, tên luồng)``. Nếu dùng chung một luồng thì
đổi ``boundary_noise`` sẽ làm lệch cả dãy số phía sau và mặt nạ recall đổi
theo — hai hồ sơ khác nhau sẽ bỏ những mention khác nhau, nên chênh lệch đo
được lẫn lộn giữa "do tham số" và "do rút thăm khác". Tách luồng biến bảng so
sánh thành **thí nghiệm ghép cặp**: đúng cùng tập mention bị bỏ, chỉ khác đúng
thứ ta cố ý đổi.
"""

from __future__ import annotations

import hashlib
import random
import struct
from dataclasses import dataclass

TYPES = ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"]
ASSERTIONS = ["isNegated", "isFamily", "isHistorical"]


@dataclass
class Profile:
    """Hồ sơ một hệ giả lập. Mọi tham số là xác suất trên từng mention."""

    name: str
    recall: float = 1.0
    #: số mention thừa sinh thêm, tính theo bội số của |gold|
    spurious_rate: float = 0.0
    #: xác suất cắt/nới biên span đi 1 từ (nguồn lỗi WER lớn nhất đo được)
    boundary_noise: float = 0.0
    #: xác suất gán sai type
    type_noise: float = 0.0
    #: xác suất bỏ mã đúng (bỏ phiếu trắng)
    cand_abstain: float = 0.0
    #: xác suất trả mã sai khi có trả
    cand_wrong: float = 0.0
    #: luôn trả thêm mã thứ hai (mô phỏng lời khuyên "trả 1–2 mã")
    cand_pad_second: bool = False
    #: xác suất bật cờ assertion không có trong gold
    assert_over: float = 0.0


def _u01(seed: int, *parts) -> float:
    """Số giả ngẫu nhiên trong [0,1) phụ thuộc TẤT ĐỊNH vào ``parts``.

    Dùng BLAKE2b thay vì ``random.Random`` để giá trị chỉ phụ thuộc khóa, không
    phụ thuộc *thứ tự gọi* — đó là điều kiện đủ để có common random numbers.
    """
    key = "|".join(str(p) for p in (seed, *parts)).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return struct.unpack("<Q", digest)[0] / 2**64


def _shrink(text: str, position: list[int], rng: random.Random) -> tuple[str, list[int]]:
    """Cắt một từ ở đầu hoặc cuối, giữ nguyên bất biến raw[start:end] == text."""
    words = text.split()
    if len(words) < 2:
        return text, position
    start, end = position
    if rng.random() < 0.5:
        head = words[0]
        cut = text.index(head) + len(head)
        while cut < len(text) and text[cut].isspace():
            cut += 1
        return text[cut:], [start + cut, end]
    tail = words[-1]
    cut = text.rindex(tail)
    while cut > 0 and text[cut - 1].isspace():
        cut -= 1
    return text[:cut], [start, start + cut]


def degrade(
    gold: dict[str, list[dict]],
    profile: Profile,
    *,
    seed: int = 20260728,
) -> dict[str, list[dict]]:
    all_codes = sorted({c for ms in gold.values() for m in ms for c in (m.get("candidates") or [])})
    out: dict[str, list[dict]] = {}

    for key, mentions in sorted(gold.items()):
        emitted: list[dict] = []
        for i, m in enumerate(mentions):
            u = lambda stream: _u01(seed, key, i, stream)  # noqa: E731
            if u("recall") > profile.recall:
                continue
            rng = random.Random(_u01(seed, key, i, "aux") * 2**32)
            text, position = m["text"], list(m["position"])
            if u("boundary") < profile.boundary_noise:
                text, position = _shrink(text, position, rng)
            ctype = m["type"]
            if u("type") < profile.type_noise:
                others = [t for t in TYPES if t != ctype]
                ctype = others[int(u("type_pick") * len(others))]
            cands = list(m.get("candidates") or [])
            if cands:
                if u("abstain") < profile.cand_abstain:
                    cands = []
                elif u("wrong") < profile.cand_wrong and all_codes:
                    cands = [all_codes[int(u("wrong_pick") * len(all_codes))]]
                elif profile.cand_pad_second and all_codes:
                    cands = cands + [all_codes[int(u("pad_pick") * len(all_codes))]]
            asserts = list(m.get("assertions") or [])
            if u("assert") < profile.assert_over:
                extra = ASSERTIONS[int(u("assert_pick") * len(ASSERTIONS))]
                if extra not in asserts:
                    asserts.append(extra)
            emitted.append(
                {
                    "text": text,
                    "type": ctype,
                    "candidates": cands,
                    "assertions": asserts,
                    "position": position,
                }
            )

        n_spur = int(round(profile.spurious_rate * len(mentions)))
        for j in range(n_spur):
            anchor = int(_u01(seed, key, j, "spur_pos") * 2000)
            rng = random.Random(_u01(seed, key, j, "spur_type") * 2**32)
            emitted.append(
                {
                    "text": "nhiễu",
                    "type": rng.choice(TYPES),
                    "candidates": [],
                    "assertions": [],
                    "position": [anchor, anchor + 5],
                }
            )
        out[key] = emitted
    return out


#: Bộ hồ sơ tham chiếu. Ba cái đầu tái hiện các chế độ đã ĐO ĐƯỢC trên dự án
#: (v3.3 ≈ recall 0,37/precision 0,75; v4 ≈ recall 0,58), ba cái sau là các
#: chính sách gây tranh cãi cần một con số thay vì một ý kiến.
PROFILES: list[Profile] = [
    Profile("oracle (= gold)"),
    Profile("v3-like  R.37 P.75", recall=0.37, spurious_rate=0.12,
            boundary_noise=0.15, cand_abstain=0.55, assert_over=0.05),
    Profile("v4-like  R.58 P.80", recall=0.58, spurious_rate=0.15,
            boundary_noise=0.30, cand_abstain=0.40, assert_over=0.05),
    Profile("recall cao  R.85 P.60", recall=0.85, spurious_rate=0.55,
            boundary_noise=0.30, cand_abstain=0.30, assert_over=0.05),
    Profile("precision cao  R.45 P.95", recall=0.45, spurious_rate=0.02,
            boundary_noise=0.10, cand_abstain=0.60, assert_over=0.02),
    Profile("biên span hoàn hảo  R.58", recall=0.58, spurious_rate=0.15,
            boundary_noise=0.0, cand_abstain=0.40, assert_over=0.05),
    Profile("luôn trả 2 mã  R.58", recall=0.58, spurious_rate=0.15,
            boundary_noise=0.30, cand_abstain=0.0, cand_pad_second=True, assert_over=0.05),
    Profile("mã hoàn hảo  R.58", recall=0.58, spurious_rate=0.15,
            boundary_noise=0.30, cand_abstain=0.0, assert_over=0.05),
]
