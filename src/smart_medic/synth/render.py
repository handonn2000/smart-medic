"""Kết xuất đồ thị bệnh án ra văn bản — **ghi offset lúc chèn**, không tìm lại.

★ HAI THỨ MODULE NÀY BẢO ĐẢM THEO KIẾN TẠO
───────────────────────────────────────────
1. **Offset đúng.** Mọi span đi qua `DocBuilder.span()`, nhận vị trí ngay lúc
   được nối vào tài liệu. Không có `index()`, không có `find()` ở bất kỳ đâu.
2. **Mã hợp lệ.** Khái niệm nào KB không tra ra mã thì bị **lọc ở đây**, trước
   khi vào corpus. Sinh một mã mà `linking.py` không thể trả về là tự dựng trần
   điểm cho chính mình (v1 §7.1) — dạy model nhắm vào thứ pipeline không với tới.

★ TỈ LỆ NỘI DUNG THEO TRẦN ĐÃ ĐO, KHÔNG THEO TRỰC GIÁC
    XÉT NGHIỆM  +0,154  →  nguồn chính
    TRIỆU_CHỨNG +0,134  →  nhiều thứ hai
    CHẨN_ĐOÁN   +0,096
    THUỐC       +0,057  →  chỉ ~10% tài liệu (§2.4)
"""

from __future__ import annotations

import functools
import random
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.query import KBStore
from smart_medic.synth import distractor, frames
from smart_medic.synth.noise import LEN_MEDIAN, DocNoise, ocr_junk
from smart_medic.synth.schema import (
    TYPE_DIAGNOSIS,
    TYPE_DRUG,
    TYPE_RESULT,
    TYPE_SYMPTOM,
    TYPE_TEST,
    Concept,
    DocBuilder,
    SynthDoc,
)
from smart_medic.synth.surface import drug as drug_src
from smart_medic.synth.surface import lab as lab_src
from smart_medic.synth.surface.frozen import FrozenSurfaces, load_frozen

# Tỉ lệ span theo nhãn — suy từ bảng trần §0.2, không phải từ `gold_real`.
TYPE_MIX = (
    (TYPE_TEST, 26),
    (TYPE_RESULT, 24),
    (TYPE_SYMPTOM, 26),
    (TYPE_DIAGNOSIS, 16),
    (TYPE_DRUG, 8),
)
P_DOC_HAS_DRUG = 0.10  # §2.4 — nhánh THUỐC cố ý giữ nhỏ
P_DISTRACTOR = 0.30  # xác suất một mục là cụm gây nhiễu KHÔNG nhãn
P_OCR_JUNK = 0.08


@dataclass(slots=True)
class Sources:
    frozen: FrozenSurfaces
    lab: lab_src.LabVocab
    drug: drug_src.DrugVocab
    layout: frames.LayoutStats
    drug_codes: dict[str, str]  # tên tiếng Việt → RxCUI, ĐÃ tra được trong KB


@functools.lru_cache(maxsize=2)
def load_sources(db: Path | None = None) -> Sources:
    """Nạp mọi nguồn, và **giải mã thuốc bằng KB ngay tại đây**.

    Tên nào không ra RxCUI thì không vào từ điển `drug_codes` — nhánh lọc của
    bảo đảm (2) ở docstring module.

    ★ Có cache: mỗi lần nạp phải dựng gazetteer từ KB, quét 71 file khuôn và tra
    739 mã — vài giây. Nguồn là dữ liệu đóng băng nên nạp lại không bao giờ cho
    kết quả khác; không cache thì bộ test sinh 5 corpus mất vài phút.
    """
    dv = drug_src.load_ddd()
    codes: dict[str, str] = {}
    with KBStore(db) as store:
        for name_vi, _atc in dv.ingredients:
            row = store.conn.execute(
                """
                SELECT c.code FROM concepts c JOIN terms t USING(concept_id)
                WHERE c.vocab='rxnorm' AND c.is_active=1 AND t.term=? LIMIT 1
                """,
                (name_vi,),
            ).fetchone()
            if row:
                codes[name_vi] = row[0]
    return Sources(load_frozen(), lab_src.load_lab_vocab(), dv, frames.mine_layout(), codes)


def _sample_concept(
    rng: random.Random, src: Sources, type_: str, *, allow_mask: bool = True
) -> Concept | list[Concept]:
    if type_ in (TYPE_TEST, TYPE_RESULT):
        return list(lab_src.sample_pair(rng, src.lab))
    if type_ == TYPE_SYMPTOM:
        return src.frozen.sample_symptom(rng)
    if type_ == TYPE_DIAGNOSIS:
        return src.frozen.sample_diagnosis(rng)
    c = drug_src.sample_drug(rng, src.drug, allow_mask=allow_mask)
    if c.origin == "atc":
        code = src.drug_codes.get(c.surfaces[0].split(" ")[0])
        # Không tra được mã → vẫn giữ mention nhưng ĐỂ TRỐNG `candidates`.
        # Đó là đáp án đúng cho biệt dược ngoài RxNorm, không phải thiếu sót.
        return Concept(TYPE_DRUG, c.surfaces, (code,) if code else (), origin=c.origin)
    return c


def _emit_span(b: DocBuilder, c: Concept, rng: random.Random, assertions: tuple[str, ...]) -> None:
    from smart_medic.synth.schema import TYPES_WITH_ASSERTIONS

    b.span(
        rng.choice(c.surfaces),
        c.type,
        codes=c.codes,
        assertions=assertions if c.type in TYPES_WITH_ASSERTIONS else (),
    )


# ★ Khung mang assertion chỉ nhận ba nhãn ĐƯỢC PHÉP có assertion.
#
#   Không ràng buộc thì bộ sinh cho ra `"Bệnh nhân có tiền sử Xét nghiệm chức
#   năng gan 428.49 nmol/L"` — vô nghĩa về lâm sàng, và tệ hơn: nó dạy model
#   rằng sau `"tiền sử"` có thể là bất cứ thứ gì. Mạch lạc ở đây không phải để
#   văn bản đẹp, nó là để tín hiệu không bị pha loãng.
_ASSERTION_TYPE_MIX = ((TYPE_SYMPTOM, 50), (TYPE_DIAGNOSIS, 38), (TYPE_DRUG, 12))


def _render_section(b: DocBuilder, rng: random.Random, src: Sources, nz: DocNoise) -> None:
    """Một mục: chọn họ khung, chèn 1–6 span, rắc cụm gây nhiễu."""
    fam = frames.pick_family(rng)
    if fam == "gach_dau_dong" and not nz.bullets:
        fam = "liet_ke"
    if fam == "nhan_hai_cham" and not nz.labels:
        fam = "liet_ke"
    if fam == "hoi_dap" and not nz.qa_voice:
        fam = "liet_ke"

    tmpl = rng.choice(frames.FRAME_FAMILIES[fam])
    asserts = frames.FRAME_ASSERTION.get(fam, ())
    mix = _ASSERTION_TYPE_MIX if asserts else TYPE_MIX
    head, _, tail = tmpl.partition("{X}")
    head = head.replace("{B}", rng.choice(src.layout.bullet_markers))
    head = head.replace("{L}", rng.choice(src.layout.labels) if src.layout.labels else "Ghi chú")

    b.plain(head)
    n_items = rng.choices((1, 2, 3, 4, 5, 6), (30, 25, 18, 12, 9, 6))[0]
    for i in range(n_items):
        if i:
            b.plain(rng.choice((", ", ", ", "; ")))
        if rng.random() < P_DISTRACTOR:
            b.distractor(distractor.sample(rng)[1])
            continue
        type_ = rng.choices([t for t, _ in mix], [w for _, w in mix])[0]
        got = _sample_concept(rng, src, type_, allow_mask=nz.mask_drugs)
        if isinstance(got, list):  # cặp TÊN_XN → KẾT_QUẢ_XN
            _emit_span(b, got[0], rng, ())
            b.plain(rng.choice((": ", " ", ": ")))
            _emit_span(b, got[1], rng, ())
        else:
            _emit_span(b, got, rng, asserts)
    b.plain(tail + "\n")


def _length(b: DocBuilder) -> int:
    return sum(len(s) for _, s, _ in b._parts)  # noqa: SLF001 — đo tiến độ nội bộ


def render_doc(name: str, rng: random.Random, src: Sources) -> SynthDoc:
    """Dựng một tài liệu tới ĐỘ DÀI THẬT, không tới độ dài ước lượng.

    Bản đầu ước lượng `60 ký tự × số mảnh` và cho ra tài liệu 224 ký tự trong khi
    trung vị thật là **1.838**. Lệch 8 lần ở đúng chiều nguy hiểm: văn bản ngắn
    thì không có cơ hội chứa liệt kê dài, mà liệt kê dài là mẫu ta đang trượt
    nhiều nhất.
    """
    nz = DocNoise.draw(rng)
    b = DocBuilder()
    target = max(400, int(rng.gauss(LEN_MEDIAN, 600)))
    guard = 0
    while _length(b) < target and guard < 400:
        guard += 1
        _render_section(b, rng, src, nz)
        if rng.random() < P_OCR_JUNK and src.layout.labels:
            b.distractor(ocr_junk(rng, rng.choice(src.layout.labels)))
            b.plain("\n")
    doc = b.build(name, transform=nz.transform)
    doc.meta = {"nfd": nz.nfd, "bullets": nz.bullets, "labels": nz.labels, "qa": nz.qa_voice}
    return doc


def generate(n: int, *, seed: int = 20260802, db: Path | None = None) -> list[SynthDoc]:
    src = load_sources(db)
    rng = random.Random(seed)
    return [render_doc(str(i), rng, src) for i in range(1, n + 1)]
