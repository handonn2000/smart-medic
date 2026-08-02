"""Nguồn cách nói cho nhánh THUỐC — tất định, và **cố ý giữ nhỏ**.

★ VÌ SAO NHÁNH NÀY CHỈ CHIẾM 10% TÀI LIỆU
──────────────────────────────────────────
Kế hoạch v1 dồn công vào đây (cả một mục §4.4, cột giữa §4.1, bước 2a, mục rủi
ro §7.1). Đo lại thì THUỐC là nhánh **đã mạnh nhất và có trần thấp nhất**:

    THUỐC   R 0,865 · P 0,942 · trần chỉ +0,057

Và bảng ATC gần như vô giá trị trên phân bố đích: 346/608 tên tiếng Việt xuất
hiện **0 lần** ở `gold_real`, **0 lần** ở `gold_batch1`, đúng **3 tên trên
4/100 file** `data/test`. Khớp với `docs/reports/atc-vi-enrich.json`
(delta = 0,000 tuyệt đối trên cả 5 bộ probe).

★ THỨ NHÁNH THUỐC THẬT SỰ CẦN HỌC
Đo trên `gold_real`: **50/74 mention THUỐC KHÔNG có mã**.

    ***********      token bị che — 30/100 file `data/test`, độ dài trung vị 12
    Aquima · Simenic · Pimperam    biệt dược Việt KHÔNG có trong RxNorm

Với cả hai lớp đó, `candidates` rỗng **là đáp án đúng**, không phải là thiếu sót
— Jaccard rỗng-gặp-rỗng bằng 1,0. Nên bộ sinh phải dạy model **khoanh đúng span
rồi để trống mã**, chứ không phải dạy nó đoán mã.

★ CẤM SINH BIỆT DƯỢC MÀ KB KHÔNG TRA ĐƯỢC KÈM MÃ
Sinh mã mà `linking.py` không thể trả về là tự dựng trần điểm cho chính mình
(v1 §7.1). Lọc nằm ở `render.py`, không phải ở đây.
"""

from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.config import CURATED_DIR, RAW_DIR
from smart_medic.synth.noise import mask_token
from smart_medic.synth.schema import TYPE_DRUG, Concept

DDD_CSV = RAW_DIR / "atc" / "ddd.csv"
HEADER_KEY = "Mã ATC"

# Ký hiệu danh mục BHYT, không phải tên thuốc. `+` là thuốc phối hợp — gán một
# mã cho chúng là sai. Đo được: 558/2019 dòng rơi vào các nhóm này.
_NOT_SINGLE = re.compile(r"[+*(]")

# Biệt dược Việt KHÔNG có trong RxNorm. Không chép từ `gold_real` (nó là cổng):
# đây là quy tắc CẤU TẠO — tên thương mại Việt thường là ghép âm tiết Latin hoá.
_BRAND_STEMS = ("Ame", "Vina", "Nam", "Sti", "Meko", "Dopha", "Phil", "Agi", "Hasan", "Tv")
_BRAND_TAILS = ("mol", "cin", "dine", "zol", "prid", "vit", "gel", "cort", "flu", "pram")


@dataclass(slots=True)
class DrugVocab:
    ingredients: tuple[tuple[str, str], ...]  # (tên tiếng Việt, mã ATC)
    dose_forms: tuple[str, ...]
    groups: tuple[str, ...]


def load_ddd(path: Path | None = None) -> DrugVocab:
    """Đọc bảng DDD của Bộ Y tế. Tự dò dòng tiêu đề — file có 2 dòng rác ở đầu."""
    rows = list(csv.reader((path or DDD_CSV).open(encoding="utf-8-sig")))
    head = next(i for i, r in enumerate(rows) if HEADER_KEY in r)
    cols = {name.strip(): i for i, name in enumerate(rows[head])}
    ci, cn = cols[HEADER_KEY], cols["Thuốc"]
    cf, cg = cols.get("Dạng bào chế"), cols.get("Nhóm Thuốc")

    ing: dict[str, str] = {}
    forms: set[str] = set()
    groups: set[str] = set()
    for r in rows[head + 1 :]:
        if len(r) <= max(ci, cn):
            continue
        atc, name = r[ci].strip(), r[cn].strip()
        if cf is not None and len(r) > cf and r[cf].strip():
            forms.add(r[cf].strip())
        if cg is not None and len(r) > cg and r[cg].strip():
            groups.add(re.sub(r"^\d+\.", "", r[cg]).strip())
        if not name or not atc or _NOT_SINGLE.search(name):
            continue
        ing.setdefault(name, atc)
    return DrugVocab(tuple(sorted(ing.items())), tuple(sorted(forms)), tuple(sorted(groups)))


def freeze_curated(vocab: DrugVocab, out_dir: Path | None = None) -> dict[str, int]:
    """Đóng băng ba file phái sinh vào `data/curated/`.

    ⚠️ `dose_forms` và `groups` **KHÔNG nạp vào KB** — chúng không phục vụ 4 hàm
    API của KB. Chỉ bộ sinh dùng.
    """
    import json

    d = out_dir or CURATED_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "drug_surface_atc.v1.jsonl").write_text(
        "".join(
            json.dumps({"name_vi": n, "atc": a}, ensure_ascii=False) + "\n"
            for n, a in vocab.ingredients
        ),
        encoding="utf-8",
    )
    (d / "dose_forms_vi.v1.txt").write_text("\n".join(vocab.dose_forms) + "\n", encoding="utf-8")
    (d / "drug_groups_vi.v1.txt").write_text("\n".join(vocab.groups) + "\n", encoding="utf-8")
    return {
        "ingredients": len(vocab.ingredients),
        "dose_forms": len(vocab.dose_forms),
        "groups": len(vocab.groups),
    }


def fake_brand(rng: random.Random) -> str:
    """Biệt dược Việt kiểu ghép âm tiết — KHÔNG có mã, và đó là đáp án ĐÚNG."""
    return rng.choice(_BRAND_STEMS) + rng.choice(_BRAND_TAILS)


# Ba lớp bề mặt, trọng số theo tỉ lệ đo được ở `gold_real` (50/74 không có mã).
_DRUG_KINDS = (("masked", 40), ("brand_no_code", 25), ("ingredient", 35))


def sample_drug(rng: random.Random, vocab: DrugVocab, *, allow_mask: bool = True) -> Concept:
    """Một mention THUỐC. `codes` rỗng với hai lớp đầu — đúng theo đề bài.

    `allow_mask` do TÀI LIỆU quyết định, không phải mention — xem `noise.DocNoise`.
    """
    kinds = [(k, w) for k, w in _DRUG_KINDS if allow_mask or k != "masked"]
    kind = rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
    if kind == "masked":
        return Concept(TYPE_DRUG, (mask_token(rng),), origin="mask")
    if kind == "brand_no_code":
        return Concept(TYPE_DRUG, (fake_brand(rng),), origin="brand_no_code")
    name = rng.choice(vocab.ingredients)[0]
    if rng.random() < 0.5 and vocab.dose_forms:  # mention có hàm lượng/dạng dùng
        name = f"{name} {rng.choice((5, 10, 20, 40, 50, 100, 500))}mg"
    return Concept(TYPE_DRUG, (name,), origin="atc")
