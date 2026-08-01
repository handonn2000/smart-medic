"""Suy luận ngữ cảnh — ConText/NegEx cho bệnh án tiếng Việt.

Chiếm **0.3 điểm**. PRD §4 xếp hướng này ở mức "trung cấp" và khuyến nghị đích
danh ConText/NegEx: chuẩn mực, giải thích được, chạy offline — khớp cả ba ràng
buộc của đề.

★ MẶC ĐỊNH RỖNG LÀ NƯỚC ĐI ĐÚNG, KHÔNG PHẢI LƯỜI
─────────────────────────────────────────────────
`assertions_score` dùng Jaccard với quy ước **cả hai rỗng ⇒ J = 1** (PRD §6).
Trên bộ gold, 230/268 mục có assertion rỗng. Nên mỗi lần bật cờ sai là biến một
`J = 1` cho không thành `J = 0` — over-predict đắt hơn under-predict rất nhiều.

Hệ quả thiết kế: chỉ bật cờ khi có **từ khoá tường minh**, và phạm vi phải hẹp.

★ PHẠM VI BÁM THEO DÒNG, KHÔNG THEO CÂU
────────────────────────────────────────
Đo trên gold: bệnh án Việt gom khái niệm cùng ngữ cảnh vào **một dòng**.

    Tiền sử suy tim, tăng huyết áp, rung nhĩ.⏎Khám: mạch không đều
    ← cả ba đều isHistorical, còn "mạch không đều" ở dòng sau thì không

Nên phạm vi mặc định = từ từ khoá tới **hết dòng**. Riêng tiêu đề mục
(`3. Tiền sử:`) thì trải tới mục đánh số kế tiếp, vì nội dung nằm ở dòng dưới.

★ TỪ KHOÁ DÀI THẮNG TỪ KHOÁ NGẮN
`"Tiền sử gia đình:"` phải thắng `"Tiền sử"` — nếu không thì
`"mẹ mắc đái tháo đường"` bị gán `isHistorical` thay vì `isFamily`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from smart_medic.stages.scoring import Entity

NEGATED = "isNegated"
FAMILY = "isFamily"
HISTORICAL = "isHistorical"

# Nhãn được phép mang assertion (PRD §3.2).
TYPES_WITH_ASSERTIONS = frozenset({"CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG"})

# ── Từ khoá, xếp DÀI TRƯỚC để khớp tham lam ra đúng cái cụ thể nhất ──────
TRIGGERS: tuple[tuple[str, str], ...] = (
    # Người nhà — phải đứng trước "tiền sử" để không bị nó nuốt.
    (r"tiền sử gia đình", FAMILY),
    (r"gia đình có ai", FAMILY),
    (r"bố|mẹ|cha|anh trai|chị gái|em trai|em gái|ông|bà|con trai|con gái", FAMILY),
    # Phủ định.
    (r"không dùng|không tự ý dùng|không ai mắc|không có|không", NEGATED),
    (r"chưa từng|chưa có|chưa", NEGATED),
    (r"tránh dùng|tránh", NEGATED),
    (r"loại trừ|không nghĩ tới|đã loại", NEGATED),
    (r"ngưng|ngừng|tạm ngưng", NEGATED),
    # Tiền sử.
    (r"tiền sử|bệnh sử cũ|chẩn đoán cũ|đã từng|trước đây|nhiều năm nay", HISTORICAL),
    (r"thuốc đang dùng|đang dùng|thuốc hiện tại|duy trì", HISTORICAL),
)

_TRIGGER_RE = re.compile("|".join(f"(?P<g{i}>{pat})" for i, (pat, _) in enumerate(TRIGGERS)), re.I)
_LABEL_OF_GROUP = {f"g{i}": label for i, (_pat, label) in enumerate(TRIGGERS)}

# ── Ranh giới phạm vi, KHÁC NHAU theo loại cờ ────────────────────────────
#
# ★ Phủ định có phạm vi HẸP, tiền sử/gia đình có phạm vi RỘNG. Dùng chung một
#   bộ ranh giới thì hỏng cả hai chiều — đo được trên gold:
#
#   `"Không dùng tramadol vì có thể hạ ngưỡng co giật"`
#       `co giật` nằm sau `vì` ⇒ phải CẮT, nếu không nó bị phủ định oan.
#
#   `"Tiền sử gia đình: bố mất vì nhồi máu cơ tim"`
#       `nhồi máu cơ tim` cũng nằm sau `vì` ⇒ KHÔNG được cắt, nó vẫn là của
#       người nhà. Cắt ở đây làm mất 1 ca isFamily.
# Dấu phẩy CẮT phạm vi phủ định. An toàn vì bệnh án Việt lặp lại từ phủ định ở
# mỗi vế (`"Không đau ngực, không chóng mặt"`), nên cắt không làm mất ca nào; mà
# nó chặn được phạm vi tràn: `"không thấy xuất huyết nội sọ, nghi nhồi máu não"`
# — `nhồi máu não` KHÔNG bị phủ định. Đo được: +3 ca.
#
# `dị ứng` là **pseudo-negation** theo đúng nghĩa của NegEx: `"Không dị ứng
# aspirin"` phủ định *tình trạng dị ứng*, còn thuốc thì vẫn được dùng.
_BREAK_NEGATED = re.compile(r"[.;,]|\b(vì|do|nếu|nhưng|tuy|song|mà|dị ứng)\b", re.I)

# ★ `"khi"` KHÔNG phải ranh giới: `"khi cần"` là cách viết PRN chuẩn trong đơn
#   thuốc. Đưa nó vào làm mất 3 ca — `"Thuốc đang dùng: salbutamol khi cần,
#   montelukast…"` bị cắt ngay sau thuốc đầu tiên.
#
# `"nghi"` thì ngược lại, nó CẮT tiền sử: `"Tiền sử viêm dạ dày, nghi bệnh trào
# ngược"` — bệnh nghi ngờ không phải tiền sử.
_BREAK_CONTEXT = re.compile(r"[.;]|\b(nghi|nghĩ tới|theo dõi|chẩn đoán)\b", re.I)

# Tiêu đề mục: `3. Tiền sử:` hoặc `Tiền sử gia đình:` đứng đầu dòng và kết thúc
# bằng dấu hai chấm — nội dung của nó nằm ở các dòng SAU.
_SECTION_HEAD = re.compile(r"^\s*(?:\d+\.\s*)?[^:\n]{0,40}:\s*$")
_NEXT_SECTION = re.compile(r"^\s*\d+\.\s", re.M)


@dataclass(slots=True)
class Scope:
    label: str
    start: int
    end: int

    def covers(self, entity: Entity) -> bool:
        return self.start <= entity.start < self.end


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    nl = text.find("\n", pos)
    return start, len(text) if nl < 0 else nl


def find_scopes(text: str) -> list[Scope]:
    """Mọi phạm vi ngữ cảnh trong văn bản.

    Phạm vi chạy TỚI TRƯỚC từ khoá thì không tính — ConText chỉ nhìn xuôi.
    """
    scopes: list[Scope] = []
    for m in _TRIGGER_RE.finditer(text):
        label = next(_LABEL_OF_GROUP[g] for g, v in m.groupdict().items() if v)
        line_start, line_end = _line_bounds(text, m.start())
        line = text[line_start:line_end]

        if _SECTION_HEAD.match(line):
            # Tiêu đề mục: nội dung ở các dòng sau, tới mục đánh số kế tiếp.
            nxt = _NEXT_SECTION.search(text, line_end + 1)
            scopes.append(Scope(label, line_end, nxt.start() if nxt else len(text)))
            continue

        # Trong dòng: từ sau từ khoá tới ranh giới gần nhất.
        after = m.end()
        breaker = _BREAK_NEGATED if label == NEGATED else _BREAK_CONTEXT
        brk = breaker.search(text, after, line_end)
        scopes.append(Scope(label, after, brk.start() if brk else line_end))
    return scopes


def assign(text: str, entities: list[Entity]) -> list[Entity]:
    """Gán `assertions` cho từng entity. Mặc định rỗng.

    Ưu tiên khi nhiều phạm vi cùng phủ:

    1. **Phủ định thắng** — `"Tiền sử gia đình: không ai mắc viêm khớp dạng
       thấp"` là `isNegated`, không phải `isFamily`. Gold ghi đúng như vậy.
    2. Còn lại lấy phạm vi **hẹp nhất** (từ khoá gần entity nhất).
    """
    scopes = find_scopes(text)
    for e in entities:
        if e.type not in TYPES_WITH_ASSERTIONS:
            e.assertions = ()
            continue
        hits = [s for s in scopes if s.covers(e)]
        if not hits:
            e.assertions = ()
            continue
        if any(s.label == NEGATED for s in hits):
            e.assertions = (NEGATED,)
            continue
        best = min(hits, key=lambda s: (s.end - s.start, -s.start))
        e.assertions = (best.label,)
    return entities
