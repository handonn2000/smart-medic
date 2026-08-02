"""Nguồn cách nói cho nhánh XÉT NGHIỆM — **tất định, không gọi LLM**.

★ VÌ SAO ĐÂY LÀ NGUỒN CHÍNH CỦA CẢ BỘ SINH
───────────────────────────────────────────
Trần theo nhánh đo trên `gold_real` (thay từng nhánh bằng đáp án):

    TÊN_XN + KẾT_QUẢ_XN   +0,154   ← lớn nhất
    TRIỆU_CHỨNG           +0,134
    CHẨN_ĐOÁN             +0,096
    THUỐC                 +0,057   ← nhỏ nhất, và đã đạt P 0,942

Và hai nhãn xét nghiệm **bắt buộc `candidates` rỗng**, mà Jaccard cho
rỗng-gặp-rỗng bằng 1,0 — nên bắt đúng span là ăn trọn cả ba thành phần điểm.
Không cần KB, không cần linking, không cần assertion. Đây là nhánh vừa đáng giá
nhất vừa rẻ nhất, và là nhánh **duy nhất sinh được hoàn toàn không cần LLM**.

★ NGUỒN
`data/curated/lab_panels.v1.yaml` — dựng ở Phase 1 từ ba nguồn hợp lệ (panel
chuẩn, mẫu `^NHÃN:` của 91 file `data/test` ngoài `gold_real`, và
`gold_batch1`). `gold_real` **không** được dùng làm nguồn: nó là cổng.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import yaml

from smart_medic.kb.config import CURATED_DIR
from smart_medic.stages.labcatalog import CATALOG_FILE
from smart_medic.synth.schema import TYPE_RESULT, TYPE_TEST, Concept


@dataclass(slots=True)
class LabTest:
    """Một xét nghiệm: các cách gọi, và cách sinh ra một giá trị hợp lý."""

    names: tuple[str, ...]
    abbrs: tuple[str, ...]
    panel: str

    def surface(self, rng: random.Random) -> str:
        """Một cách gọi. Viết tắt được rút ngang hàng với tên đầy đủ.

        Đo trên `gold_real`: `BC` · `N` · `HBsAg` · `GPT` · `tbr` — viết tắt
        chiếm phần lớn tên xét nghiệm trong bệnh án Việt thật, nên nếu chỉ sinh
        tên đầy đủ thì corpus lệch đúng chỗ quan trọng.
        """
        pool = [*self.names, *self.abbrs]
        return rng.choice(pool)


@dataclass(slots=True)
class LabVocab:
    tests: tuple[LabTest, ...]
    qualitative: tuple[str, ...]
    normal: tuple[str, ...]
    trend_heads: tuple[str, ...]
    pending: tuple[str, ...]
    units: tuple[str, ...]
    prose_separators: tuple[str, ...]


def load_lab_vocab(path=None) -> LabVocab:
    p = path or CURATED_DIR / CATALOG_FILE
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    tests: list[LabTest] = []
    for panel in raw.get("panels") or []:
        for t in panel.get("tests") or []:
            names = tuple(n for n in (t.get("names") or []) if n.strip())
            abbrs = tuple(a for a in (t.get("abbr") or []) if a.strip())
            if names or abbrs:
                tests.append(LabTest(names, abbrs, panel.get("id", "")))
    v = raw.get("result_vocab") or {}
    return LabVocab(
        tests=tuple(tests),
        qualitative=tuple(v.get("qualitative") or ()),
        normal=tuple(v.get("normal") or ()),
        trend_heads=tuple(v.get("trend_heads") or ()),
        pending=tuple(v.get("pending") or ()),
        units=tuple(raw.get("extra_units") or ()),
        prose_separators=tuple(raw.get("prose_separators") or ()),
    )


# Sáu lớp giá trị đã đo ở `gold_real`/`gold_batch1` (§2.3 của kế hoạch). Trọng số
# nghiêng về `numeric` vì đó là lớp nhiều lượt nhất, nhưng năm lớp còn lại phải
# có mặt — chúng chính là chỗ `_MEASURE` không chạm tới và recall tụt về 0,424.
_VALUE_KINDS = (
    ("numeric", 40),
    ("qualitative", 15),
    ("normal", 15),
    ("trend", 12),
    ("pending", 8),
    ("bare", 10),
)


def make_result(rng: random.Random, vocab: LabVocab) -> str:
    kind = rng.choices([k for k, _ in _VALUE_KINDS], [w for _, w in _VALUE_KINDS])[0]
    if kind == "numeric":
        val = f"{rng.uniform(0.1, 500):.{rng.choice((0, 1, 2))}f}"
        if rng.random() < 0.4:  # dấu phẩy thập phân — gặp thật ở bệnh án Việt
            val = val.replace(".", ",")
        return f"{val} {rng.choice(vocab.units)}" if vocab.units else val
    if kind == "qualitative":
        return rng.choice(vocab.qualitative)
    if kind == "normal":
        return rng.choice(vocab.normal)
    if kind == "pending":
        return rng.choice(vocab.pending)
    if kind == "trend":
        tail = rng.choice(("nhẹ", "rõ", "so với lần trước", "dần", ""))
        return f"{rng.choice(vocab.trend_heads)} {tail}".strip()
    return f"{rng.uniform(0.1, 300):.1f}"  # bare — số trần, không đơn vị


def sample_pair(rng: random.Random, vocab: LabVocab) -> tuple[Concept, Concept]:
    """Một cặp `(TÊN_XN, KẾT_QUẢ_XN)`. Cả hai `codes` rỗng — đề bài quy định."""
    t = rng.choice(vocab.tests)
    return (
        Concept(TYPE_TEST, (t.surface(rng),), origin="lab_panel"),
        Concept(TYPE_RESULT, (make_result(rng, vocab),), origin="lab_panel"),
    )
