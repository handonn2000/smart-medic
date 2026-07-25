"""Assertion — mặc định RỖNG, chỉ bật khi có bằng chứng trực tiếp.

Ba kết luận đo được trên 100 file, cả ba đều thành luật ở đây:

1. ~80% concept có assertion rỗng, và metric quy ước J=1 khi cả gold lẫn pred
   đều rỗng ⇒ mặc định rỗng vừa an toàn vừa ăn điểm.

2. Cue "không" xuất hiện 561 lần nhưng ≥21% nằm trong cụm KHÔNG phủ định gì.
   Nguy hiểm nhất là "không đặc hiệu" — nó là một phần tên bệnh trong chính
   bảng ICD-10 (2.487 dòng chứa cụm này, ví dụ "Suy tim, không đặc hiệu"
   I50.9). Matcher ngây thơ vừa gắn isNegated sai, vừa cắt span mất mã.

3. isFamily TẮT mặc định. Cue "ông " xuất hiện 644 lần nhưng 630 (98%) là
   mảnh của chữ "kh-ông". Sau khi sửa ranh giới từ chỉ còn 80 cue/36 file, và
   soi tay thì phần lớn vẫn là bẫy: cơ chế di truyền ("nhận gen lặn từ bố
   và/hoặc mẹ"), lời khuyên ("cha mẹ cần đưa trẻ..."), "bà ấy" = chính bệnh
   nhân, "người nhà nhận thấy" = người quan sát. isFamily thật ≈ 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import Assertion, ConceptType, Span
from ..textref import TextRef

# ── Negation ──────────────────────────────────────────────────────────────────

#: Cụm chứa "không" nhưng KHÔNG phủ định khái niệm y tế nào.
NON_NEGATING = (
    "không đặc hiệu", "không rõ", "không xác định", "không nên", "không được",
    "không thể", "không chỉ", "không phải", "không khí", "không gian",
    "không may", "không ít", "không còn nghi", "không bào",
)

NEG_CUES = ("không", "chưa", "chẳng", "phủ nhận", "loại trừ", "âm tính")

#: Phạm vi phủ định kết thúc ở dấu câu hoặc liên từ (kiểu ConText/NegEx).
SCOPE_BREAK = re.compile(r"[.;:!?\n]|\bnhưng\b|\btuy nhiên\b|\bmà\b|\bcòn\b")

#: Cửa sổ tối đa (ký tự) từ cue tới concept.
NEG_WINDOW = 60

# ── Historical ────────────────────────────────────────────────────────────────

#: Tiêu đề mục — tín hiệu mạnh hơn nhiều so với cue cục bộ. Đo được: 58 file có
#: mục "tiền sử", 55 "tiền sử bệnh", 23 "bệnh sử", 22 "thuốc trước khi nhập viện".
SECTION_HISTORICAL = (
    "tiền sử bệnh", "tiền sử", "tiền căn", "bệnh sử",
    "thuốc trước khi nhập viện", "thuốc trước nhập viện",
    "danh sách thuốc trước nhập viện",
)
#: Tiêu đề kết thúc phạm vi tiền sử.
SECTION_OTHER = (
    "khám bệnh", "khám lâm sàng", "lý do vào viện", "chẩn đoán", "điều trị",
    "kết quả xét nghiệm", "cận lâm sàng", "tóm tắt bệnh án", "diễn biến",
    "quá trình bệnh lý", "thuốc điều trị", "y lệnh",
)

def _heading_re(names: tuple[str, ...]) -> re.Pattern[str]:
    """Khớp '<tên mục>:' ở bất cứ đâu, có kiểm tra ranh giới từ.

    KHÔNG neo vào '\\n': norm_text() gộp mọi khoảng trắng (kể cả xuống dòng)
    thành một dấu cách, nên chuỗi norm không còn ký tự xuống dòng nào. Đây là
    lỗi đã mắc một lần — regex neo '\\n' chỉ khớp được tiêu đề đầu tiên.

    Đổi lại phải yêu cầu dấu ':' để tránh dương tính giả: "được chẩn đoán mắc…"
    trong câu văn xuôi không phải tiêu đề mục.
    """
    alt = "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
    return re.compile(rf"(?<![\wăâđêôơư])({alt})\s*:")


HEADING_HIST_RE = _heading_re(SECTION_HISTORICAL)
HEADING_OTHER_RE = _heading_re(SECTION_OTHER)


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    historical: bool


class SectionMap:
    """Cây khoảng phẳng cho các mục của văn bản (tính trên chuỗi norm)."""

    def __init__(self, norm: str) -> None:
        marks: list[tuple[int, bool]] = []
        marks += [(m.start(), True) for m in HEADING_HIST_RE.finditer(norm)]
        marks += [(m.start(), False) for m in HEADING_OTHER_RE.finditer(norm)]
        marks.sort()

        # Tiêu đề dài thắng tiêu đề ngắn lồng trong nó ("tiền sử bệnh" vs "tiền sử").
        dedup: list[tuple[int, bool]] = []
        for pos, hist in marks:
            if dedup and pos - dedup[-1][0] < 3:
                continue
            dedup.append((pos, hist))

        self.sections: list[Section] = []
        for k, (pos, hist) in enumerate(dedup):
            end = dedup[k + 1][0] if k + 1 < len(dedup) else len(norm)
            self.sections.append(Section(pos, end, hist))

    def is_historical(self, ns: int) -> bool:
        for s in self.sections:
            if s.start <= ns < s.end:
                return s.historical
        return False


# ── API ───────────────────────────────────────────────────────────────────────


class AssertionTagger:
    def __init__(
        self,
        tref: TextRef,
        *,
        enable_negated: bool = True,
        enable_historical: bool = True,
        enable_family: bool = False,   # xem docstring module
    ) -> None:
        self.tref = tref
        self.sections = SectionMap(tref.norm)
        self.enable_negated = enable_negated
        self.enable_historical = enable_historical
        self.enable_family = enable_family

    def tag(self, span: Span, ctype: ConceptType) -> tuple[frozenset[Assertion], dict]:
        from ..schema import ASSERTABLE

        if ctype not in ASSERTABLE:
            return frozenset(), {}

        ns = self._norm_start(span)
        if ns is None:
            return frozenset(), {}

        flags: set[Assertion] = set()
        evidence: dict[str, str] = {}

        if self.enable_historical and self.sections.is_historical(ns):
            flags.add(Assertion.HISTORICAL)
            evidence["isHistorical"] = "phạm vi mục tiền sử"

        if self.enable_negated:
            cue = self._negation_cue(ns)
            if cue:
                flags.add(Assertion.NEGATED)
                evidence["isNegated"] = cue

        return frozenset(flags), evidence

    # -- nội bộ --

    def _norm_start(self, span: Span) -> int | None:
        """Ánh xạ offset raw → offset norm bằng tìm nhị phân trên n2r."""
        lo, hi = 0, len(self.tref.n2r) - 1
        if hi < 0:
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            if self.tref.n2r[mid] < span.start:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _negation_cue(self, ns: int) -> str | None:
        lo = max(0, ns - NEG_WINDOW)
        window = self.tref.norm[lo:ns]

        brk = None
        for m in SCOPE_BREAK.finditer(window):
            brk = m.end()
        if brk is not None:
            window = window[brk:]     # phủ định không vượt qua dấu câu/liên từ

        for m in re.finditer(r"(?<![\wăâđêôơư])(%s)" % "|".join(NEG_CUES), window):
            cue = m.group(1)
            tail = window[m.start():m.start() + 24]
            if any(tail.startswith(p) for p in NON_NEGATING):
                continue              # "không đặc hiệu" là tên bệnh, không phải phủ định
            return cue
        return None
