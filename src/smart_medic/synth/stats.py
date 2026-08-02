"""Đo corpus sinh ra so với **phân bố thật đã đo trên `data/test`**.

★ CỔNG ĐỊNH TUYẾN CỦA PHASE 2 NẰM Ở ĐÂY
────────────────────────────────────────
Không đạt thì **ghi số rồi đi tiếp** (§4.0) — corpus vẫn đem huấn luyện ở Phase
3, chỉ là kỳ vọng thấp hơn, và Phase 5 biết điều đó khi đọc file này.

    nhiễu khớp §3.2 trong ±10 điểm phần trăm
    ≥ 15% span là span âm (cụm gây nhiễu KHÔNG nhãn)
    hai phép đo của 2c (hợp lý y khoa ≥ 80/100 · độ mới ≥ 40%)

★ CẤM BÁO CÁO ĐIỂM TRÊN CHÍNH CORPUS NÀY
Module này đo **tính chất của dữ liệu** (phân bố, mật độ, độ mới), không đo
**năng lực của hệ thống**. Quy tắc §5.1: số đo năng lực chỉ được lấy trên
`gold_real`.
"""

from __future__ import annotations

import statistics
import unicodedata
from collections import Counter

from smart_medic.synth.noise import (
    LEN_MEDIAN,
    P_BULLET,
    P_LABEL,
    P_MASK,
    P_NFD,
    P_QA_VOICE,
)
from smart_medic.synth.schema import SynthDoc

TOLERANCE_PP = 10.0  # điểm phần trăm — ngưỡng đã nới ở §4.1
MIN_DISTRACTOR_SHARE = 0.15


def _share(docs: list[SynthDoc], pred) -> float:
    return sum(1 for d in docs if pred(d)) / len(docs) if docs else 0.0


def measure(docs: list[SynthDoc]) -> dict:
    lens = sorted(len(d.text) for d in docs)
    n_span = sum(len(d.spans) for d in docs)
    n_dis = sum(len(d.distractors) for d in docs)

    observed = {
        "nfd": _share(docs, lambda d: unicodedata.normalize("NFC", d.text) != d.text),
        "mask": _share(docs, lambda d: "***" in d.text),
        "bullet": _share(
            docs,
            lambda d: any(
                ln.lstrip().startswith(("-", "•", "*", "+")) for ln in d.text.split("\n")
            ),
        ),
        "label": _share(
            docs,
            lambda d: any(
                ":" in ln and not ln.lstrip().startswith(("-", "•")) for ln in d.text.split("\n")
            ),
        ),
    }
    target = {"nfd": P_NFD, "mask": P_MASK, "bullet": P_BULLET, "label": P_LABEL}
    noise = {
        k: {
            "target": round(target[k], 3),
            "observed": round(observed[k], 3),
            "delta_pp": round((observed[k] - target[k]) * 100, 1),
            "ok": abs(observed[k] - target[k]) * 100 <= TOLERANCE_PP,
        }
        for k in target
    }

    by_type = Counter(s.type for d in docs for s in d.spans)
    dis_share = n_dis / (n_span + n_dis) if n_span + n_dis else 0.0
    return {
        "n_docs": len(docs),
        "n_spans": n_span,
        "n_distractors": n_dis,
        "distractor_share": {
            "value": round(dis_share, 3),
            "min": MIN_DISTRACTOR_SHARE,
            "ok": dis_share >= MIN_DISTRACTOR_SHARE,
        },
        "length": {
            "median": int(statistics.median(lens)),
            "target_median": LEN_MEDIAN,
            "p10": lens[len(lens) // 10],
            "p90": lens[-max(1, len(lens) // 10)],
        },
        "noise": noise,
        "qa_voice_target": P_QA_VOICE,
        "by_type": dict(by_type.most_common()),
        "assertions": dict(Counter(a for d in docs for s in d.spans for a in s.assertions)),
        "gate_noise_ok": all(v["ok"] for v in noise.values()),
    }
