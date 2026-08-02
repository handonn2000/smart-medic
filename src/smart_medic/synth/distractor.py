"""Span ÂM — cụm chèn vào văn bản và **cố ý không gán nhãn**.

★ THÀNH PHẦN MÀ KẾ HOẠCH v1 THIẾU HOÀN TOÀN
────────────────────────────────────────────
Precision là đòn bẩy lớn thứ hai (+0,120 trên `gold_real`), và đo được **102
span thừa**. Nhưng bộ sinh của v1 chỉ chèn span DƯƠNG. Model học trên văn bản mà
*mọi* cụm y khoa đều có nhãn sẽ suy ra "cứ thấy thuật ngữ y khoa là bắn" — đúng
lớp lỗi mà giám sát xa từ từ điển nổi tiếng mắc phải (AutoNER, EMNLP 2018).

★ LẤY *LỚP* CỦA BẪY, KHÔNG LẤY *THỰC THỂ*
`data/probe/gold_real/README.md` có sẵn danh mục bẫy hoàn chỉnh — nhưng nó là
**file cổng**. Chép thực thể từ đó rồi đem chấm trên chính nó thì phép đo thành
tự khen (quy tắc §5.7). Nên ở đây lấy **loại hình** của bẫy (kiến thức chung về
thể loại văn bản y khoa) và tự sinh thực thể mới.

Sáu lớp, theo §2.5 của kế hoạch. Mỗi lớp trả lời một câu "vì sao model dễ nhầm":

    thủ thuật       có động từ y khoa nhưng không phải bệnh/thuốc
    thiết bị        danh từ y khoa, không thuộc 5 nhãn nào
    thực phẩm       tên gọi giống thuốc, đặc biệt thực phẩm chức năng
    enzyme/protein  tên viết hoa + viết tắt, rất giống tên xét nghiệm
    lớp thuốc chung `guideline` loại — không định danh được một thuốc cụ thể
    vị trí giải phẫu danh từ đi kèm triệu chứng, dễ bị nuốt vào span
"""

from __future__ import annotations

import random

from smart_medic.kb.config import CURATED_DIR

# ── Sáu lớp. Thực thể tự sinh, KHÔNG chép từ `gold_real/README.md`. ──────────

PROCEDURES = (
    "đặt catheter tĩnh mạch trung tâm", "chọc dò màng phổi", "nội khí quản",
    "truyền dịch", "thay băng", "phẫu thuật nội soi", "đặt sonde tiểu",
    "chọc hút dịch màng bụng", "cắt lọc vết thương", "tiêm truyền tĩnh mạch",
)  # fmt: skip

DEVICES = (
    "máy thở", "ống thông tiểu", "máy tạo nhịp", "kim luồn", "bơm tiêm điện",
    "monitor theo dõi", "giường bệnh", "xe lăn", "nạng chống",
)  # fmt: skip

FOODS = (
    "sữa chua", "nhân sâm", "mật ong", "nghệ mật ong", "yến sào", "trà gừng",
    "nước cam", "sữa đậu nành", "cháo loãng", "men vi sinh",
)  # fmt: skip

ENZYMES = (
    "men gan", "protein C", "protein S", "men tiêu hoá", "enzym chuyển hoá",
    "kháng thể kháng nhân", "yếu tố đông máu VIII", "men amylase tuyến tuỵ",
)  # fmt: skip

ANATOMY = (
    "vùng thượng vị", "hạ sườn phải", "hố chậu trái", "vùng thắt lưng",
    "khoang màng phổi", "trung thất", "vùng chẩm", "hố nách",
)  # fmt: skip

# ★ Lớp thuốc chung — nguồn TẤT ĐỊNH: 29 nhóm thuốc tiếng Việt của bảng ATC/DDD.
# `guideline` §3.2 loại chúng vì không định danh được một thuốc cụ thể, nhưng
# chúng trông y hệt tên thuốc nên model rất dễ bắn nhầm.
_GROUPS_FILE = "drug_groups_vi.v1.txt"
_FALLBACK_GROUPS = ("thuốc lợi tiểu", "kháng sinh", "thuốc giảm đau", "corticoid")


def load_drug_groups() -> tuple[str, ...]:
    p = CURATED_DIR / _GROUPS_FILE
    if not p.is_file():
        return _FALLBACK_GROUPS
    return tuple(x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip())


def all_classes() -> dict[str, tuple[str, ...]]:
    return {
        "thu_thuat": PROCEDURES,
        "thiet_bi": DEVICES,
        "thuc_pham": FOODS,
        "enzyme": ENZYMES,
        "giai_phau": ANATOMY,
        "lop_thuoc_chung": load_drug_groups(),
    }


def sample(rng: random.Random) -> tuple[str, str]:
    """Một cụm gây nhiễu: `(lớp, chuỗi)`."""
    classes = all_classes()
    name = rng.choice(list(classes))
    return name, rng.choice(classes[name])
