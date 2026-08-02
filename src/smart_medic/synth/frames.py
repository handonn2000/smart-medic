"""Khung câu — nơi có tín hiệu học được nhiều nhất, và ranh giới với PRD §5.

★ VÌ SAO KHUNG CÂU QUAN TRỌNG HƠN NÓ TRÔNG
───────────────────────────────────────────
Xem ngữ cảnh các span đang bỏ sót:

    không thấy  buồn nôn, ⟦nôn⟧, ⟦ớn lạnh⟧, ⟦thay đổi chức năng ruột⟧
                    ↑ BẮT được       ↑ ba cái sau đều TRƯỢT

Ta bắt mục ĐẦU của danh sách rồi trượt phần còn lại. Đó là mẫu *liệt kê đồng
vị*, và một template sinh ra vô hạn biến thể độ dài danh sách dạy nó rất rẻ.

★ RANH GIỚI VỚI PRD §5 — ĐỌC KỸ TRƯỚC KHI SỬA
──────────────────────────────────────────────
Kế hoạch (§4 Phase 2d) cho phép khai thác 91 file `data/test` ngoài `gold_real`
làm khuôn. Nhưng PRD §5 cấm hard-code output theo input, và có private test.
Ranh giới áp ở đây, chặt hơn kế hoạch một bậc:

    LẤY   giàn giáo CẤU TRÚC — nhãn `^NHÃN:`, kiểu gạch đầu dòng, độ dài dòng,
          mật độ đoạn. Đây là *hình thức*, quan sát được từ ngoài, và là thứ
          quyết định phân bố §3.2.
    KHÔNG lấy câu nào CHỨA khái niệm y tế. Không copy mệnh đề. Không lấy văn
          phong đặc thù của một file cụ thể.

Nói cách khác: mượn cái **khuôn**, không mượn cái **đúc ra từ khuôn**. Giữ thêm
20 file làm holdout để đo được rằng ta không vô tình học thuộc.

Các họ khung nội dung (`FRAME_FAMILIES`) thì **tự viết**, không lấy từ đâu cả.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from smart_medic.kb.config import DATA_DIR
from smart_medic.stages.textio import read_document

# 9 file này đã thành `gold_real` — **cổng**, tuyệt đối không đụng (quy tắc §5.7).
GOLD_REAL_STEMS = frozenset({"1", "7", "18", "24", "30", "45", "53", "65", "100"})
# Giữ lại làm holdout khung: đo được rằng bộ sinh không học thuộc bố cục.
HOLDOUT_N = 20

_LABEL = re.compile(r"(?m)^[ \t]*([^:\n]{2,45}?):[ \t]")
_BULLET = re.compile(r"(?m)^[ \t]*([-•+*•])\s")


@dataclass(slots=True)
class LayoutStats:
    """Giàn giáo CẤU TRÚC trích từ `data/test`. Không chứa nội dung y khoa."""

    labels: tuple[str, ...] = ()
    bullet_markers: tuple[str, ...] = ("-",)
    donor_files: tuple[str, ...] = ()
    holdout_files: tuple[str, ...] = ()
    counts: dict = field(default_factory=dict)


_LABEL_STOP = re.compile(r"\d")
_LEADING_BULLET = re.compile(r"^[-•+*•]\s*")


def _is_medical(name: str, gaz) -> bool:
    """Nhãn có chứa khái niệm y tế không — tra bằng chính gazetteer của pipeline.

    ★ Đây là chốt chặn của ranh giới ở docstring module. Không có nó thì mẻ trích
    đầu tiên đã cho ra nhãn `"- khó thở"` — một TRIỆU CHỨNG, tức đúng thứ bị cấm
    mang từ `data/test` sang. Hình thức thì được, nội dung thì không.
    """
    from smart_medic.stages.ner import norm_key, tokens_with_offset

    toks = [w[0] for w in tokens_with_offset(name)]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks) + 1):
            if gaz.lookup(norm_key(toks[i:j])):
                return True
    return False


def mine_layout(test_dir: Path | None = None, *, seed: int = 20260802) -> LayoutStats:
    from smart_medic.kb.query import KBStore
    from smart_medic.stages.ner import Gazetteer

    d = test_dir or DATA_DIR / "test"
    files = sorted(
        (f for f in d.glob("*.txt") if f.stem not in GOLD_REAL_STEMS),
        key=lambda p: (len(p.stem), p.stem),
    )
    rng = random.Random(seed)
    holdout = set(rng.sample([f.stem for f in files], min(HOLDOUT_N, len(files))))
    donors = [f for f in files if f.stem not in holdout]

    # ★ Đếm theo SỐ TÀI LIỆU, không theo số lần xuất hiện.
    #
    #   Lọc bằng gazetteer thôi thì không đủ — mẻ đầu vẫn cho ra `"nhìn mờ"`,
    #   một triệu chứng dân dã mà từ điển KB không biết. Mà "từ điển KB không
    #   biết cách nói dân dã" **chính là vấn đề cả dự án đang giải**, nên không
    #   thể lấy nó làm hàng rào.
    #
    #   Tiêu chí đúng là tiêu chí CẤU TRÚC: giàn giáo của một thể loại văn bản
    #   thì lặp qua nhiều tài liệu khác nhau; một cụm nội dung thì không. Ngưỡng
    #   ≥ 3 tài liệu vừa loại được nội dung lọt lưới, vừa không cần từ điển y
    #   khoa nào — nên nó không bao giờ mục nát theo KB.
    labels: Counter[str] = Counter()
    doc_freq: Counter[str] = Counter()
    bullets: Counter[str] = Counter()
    for f in donors:
        t = read_document(f)
        seen: set[str] = set()
        for m in _LABEL.finditer(t):
            name = _LEADING_BULLET.sub("", m.group(1).strip())
            if 2 <= len(name) <= 30 and not _LABEL_STOP.search(name):
                labels[name] += 1
                seen.add(name)
        doc_freq.update(seen)
        for m in _BULLET.finditer(t):
            bullets[m.group(1)] += 1

    MIN_DOCS = 3
    with KBStore(None) as store:
        gaz = Gazetteer.from_kb(store)
        kept = tuple(
            n
            for n, _ in labels.most_common(120)
            if doc_freq[n] >= MIN_DOCS and not _is_medical(n, gaz)
        )

    return LayoutStats(
        labels=kept,
        bullet_markers=tuple(b for b, _ in bullets.most_common(4)) or ("-",),
        donor_files=tuple(f.stem for f in donors),
        holdout_files=tuple(sorted(holdout, key=lambda s: (len(s), s))),
        counts={
            "donors": len(donors),
            "holdout": len(holdout),
            "labels_seen": len(labels),
            "labels_kept": len(kept),
            "min_docs_for_label": MIN_DOCS,
        },
    )


# ── Họ khung — TỰ VIẾT, không lấy từ `data/test` ──────────────────────────
#
# `{X}` là chỗ chèn span. Thứ tự trong bảng phản ánh ưu tiên đã đo:
# liệt kê đồng vị đứng đầu vì đó là mẫu ta đang trượt nhiều nhất.

FRAME_FAMILIES: dict[str, tuple[str, ...]] = {
    # ★ ưu tiên cao nhất — bắt mục đầu rồi trượt phần còn lại
    "liet_ke": (
        "Bệnh nhân có {X}.",
        "Ghi nhận {X}.",
        "Khám thấy {X}.",
        "Người bệnh than phiền {X}.",
    ),
    "gach_dau_dong": ("{B} {X}",),
    "nhan_hai_cham": ("{L}: {X}",),
    "phu_dinh": (
        "Không thấy {X}.",
        "Chưa ghi nhận {X}.",
        "Loại trừ {X}.",
        "Không có {X}.",
    ),
    "tien_su": (
        "Tiền sử {X}.",
        "Bệnh nhân có tiền sử {X}.",
        "Đã từng được chẩn đoán {X}.",
        "Trước đây điều trị {X}.",
    ),
    "nguoi_nha": (
        "Tiền sử gia đình: mẹ mắc {X}.",
        "Bố bệnh nhân bị {X}.",
        "Trong gia đình có người mắc {X}.",
        "Chị gái bệnh nhân được chẩn đoán {X}.",
    ),
    "hoi_dap": (
        "Chào bác sĩ, em bị {X} khoảng một tuần nay ạ.",
        "Thưa bác sĩ, mẹ em có {X} thì nên làm gì ạ?",
        "Em đang lo vì gần đây hay {X}.",
        "Bác sĩ cho em hỏi {X} có nguy hiểm không ạ?",
    ),
    "giao_duc": (
        "{X} là tình trạng thường gặp.",
        "Người mắc {X} nên đi khám sớm.",
        "Các biểu hiện thường gặp gồm {X}.",
        "{X} có thể xuất hiện ở mọi lứa tuổi.",
    ),
}

# Khung nào gán assertion nào — assertion là **thuộc tính của khung**, không phải
# phán đoán. Đó là điểm mạnh của annotation-first: nhãn sạch tuyệt đối.
FRAME_ASSERTION: dict[str, tuple[str, ...]] = {
    "phu_dinh": ("isNegated",),
    "tien_su": ("isHistorical",),
    "nguoi_nha": ("isFamily",),
}

# ★ `isFamily` thật chỉ có **1 span/333** ở `gold_real` và **1/858** ở
# `gold_batch1`. Khan hiếm ở cả hai bộ độc lập ⇒ đó là tính chất của dữ liệu
# thật, không phải rủi ro lấy mẫu. Template sinh được bao nhiêu cũng có.
FRAME_WEIGHTS: dict[str, int] = {
    "liet_ke": 26,
    "gach_dau_dong": 22,
    "nhan_hai_cham": 20,
    "phu_dinh": 8,
    "tien_su": 8,
    "nguoi_nha": 4,
    "hoi_dap": 6,
    "giao_duc": 6,
}


def pick_family(rng: random.Random) -> str:
    names = list(FRAME_WEIGHTS)
    return rng.choices(names, [FRAME_WEIGHTS[n] for n in names])[0]
