"""Cách nói bề mặt do LLM sinh — **đã đóng băng**, đọc từ file, không gọi API.

★ RÀNG BUỘC TÁI LẬP (PRD §8, quy tắc §5.3)
───────────────────────────────────────────
Không được gọi API lúc build. Tiền lệ đã có trong dự án: từ đồng nghĩa E5 của KB
sinh một lần rồi đóng băng. Ở đây cũng vậy — `surface_forms.v1.jsonl` kèm
`.sha256`, commit vào git, và từ đó về sau chỉ đọc.

★ CHỈ HAI NHÃN NÀY MỚI HỎI LLM
    CHẨN_ĐOÁN   trần +0,096
    TRIỆU_CHỨNG trần +0,134
Nhánh XÉT NGHIỆM (+0,154, lớn nhất) và nhánh THUỐC (+0,057) đều có nguồn TẤT
ĐỊNH — `lab.py` và `drug.py`. Bớt được chỗ nào phải tin LLM thì bớt.

★ HAI PHÉP ĐO ĐÃ GHI LẠI (`docs/reports/phase2-corpus-stats.json`)
    hợp lý y khoa   92/100 cặp duyệt tay      (ngưỡng ≥ 80)
    độ mới          51,0% không khớp gazetteer (ngưỡng ≥ 40%)

Phép đo *độ mới* là thứ chặn "vòng lặp tự khen": nếu cách nói chỉ lặp lại vốn từ
KB đã có thì model học xong không biết thêm gì, và cả kế hoạch vô ích.

⚠️ Ràng buộc "dùng model KHÁC HỌ với model ở pipeline" **không áp dụng được**:
pipeline hiện tại không dùng LLM ở bất kỳ đâu (luật + KB thuần), nên không có
tương quan sai số nào để tránh. Ghi lại để không ai đi tìm.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.config import CURATED_DIR
from smart_medic.synth.schema import TYPE_DIAGNOSIS, TYPE_SYMPTOM, Concept

FROZEN_FILE = "surface_forms.v1.jsonl"


@dataclass(slots=True)
class FrozenSurfaces:
    diagnoses: tuple[Concept, ...]
    symptoms: tuple[Concept, ...]

    def sample_diagnosis(self, rng: random.Random) -> Concept:
        return rng.choice(self.diagnoses)

    def sample_symptom(self, rng: random.Random) -> Concept:
        return rng.choice(self.symptoms)


def load_frozen(path: Path | None = None) -> FrozenSurfaces:
    p = path or CURATED_DIR / FROZEN_FILE
    dx: list[Concept] = []
    sx: list[Concept] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        surfaces = tuple(r["surfaces"])
        if r["type"] == TYPE_DIAGNOSIS:
            dx.append(Concept(TYPE_DIAGNOSIS, surfaces, (r["code"],), origin="frozen_llm"))
        else:
            # TRIỆU_CHỨNG: `candidates` PHẢI rỗng — đề bài quy định, và Jaccard
            # rỗng-gặp-rỗng bằng 1,0 nên rỗng là đáp án ĐÚNG.
            sx.append(Concept(TYPE_SYMPTOM, surfaces, (), origin="frozen_llm"))
    if not dx or not sx:
        raise ValueError(f"{p} thiếu một trong hai nhãn")
    return FrozenSurfaces(tuple(dx), tuple(sx))


def verify_sha256(path: Path | None = None) -> bool:
    """Nội dung có khớp `.sha256` đã commit không. Lệch ⇒ file đã bị sửa tay."""
    import hashlib

    p = path or CURATED_DIR / FROZEN_FILE
    want = (p.parent / f"{p.name}.sha256").read_text(encoding="utf-8").split()[0]
    return hashlib.sha256(p.read_bytes()).hexdigest() == want
