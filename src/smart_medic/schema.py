"""Schema output + cưỡng chế type gate bằng hệ thống kiểu.

Hai lỗi đắt giá đã ghi nhận trong lịch sử dự án, cả hai đều được chặn ở đây:

1. Nhãn viết tắt (``TÊN_XN`` thay vì ``TÊN_XÉT_NGHIỆM``) làm hỏng toàn bộ
   471 record một lần. → ConceptType là enum, không phải chuỗi tự do.

2. Điền ``candidates`` cho TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM / KẾT_QUẢ_XÉT_NGHIỆM.
   Đo được: 27% mention khớp gazetteer ICD nguyên văn rơi vào chương R (triệu
   chứng), nên đây không phải rủi ro lý thuyết. → chỉ DiagnosisMention và
   DrugMention mới có trường candidates; ba loại còn lại KHÔNG CÓ ĐƯỜNG NÀO
   chạm tới KB vì kiểu không cho.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class ConceptType(str, Enum):
    """5 nhãn. Viết đầy đủ, có dấu — tuyệt đối không viết tắt."""

    TRIEU_CHUNG = "TRIỆU_CHỨNG"
    TEN_XET_NGHIEM = "TÊN_XÉT_NGHIỆM"
    KET_QUA_XET_NGHIEM = "KẾT_QUẢ_XÉT_NGHIỆM"
    CHAN_DOAN = "CHẨN_ĐOÁN"
    THUOC = "THUỐC"


class Assertion(str, Enum):
    NEGATED = "isNegated"
    FAMILY = "isFamily"
    HISTORICAL = "isHistorical"


#: Chỉ hai type này được phép có candidates (đề bài §3.2).
MAPPABLE = frozenset({ConceptType.CHAN_DOAN, ConceptType.THUOC})
#: Chỉ ba type này được phép có assertions (đề bài §3.2).
ASSERTABLE = frozenset(
    {ConceptType.CHAN_DOAN, ConceptType.THUOC, ConceptType.TRIEU_CHUNG}
)


@dataclass(frozen=True)
class Span:
    """Bất biến trung tâm: ``raw[start:end] == text``."""

    start: int
    end: int
    text: str

    def verify(self, raw: str) -> bool:
        return raw[self.start : self.end] == self.text

    def overlaps(self, other: "Span") -> bool:
        return not (self.end <= other.start or self.start >= other.end)


@dataclass
class Provenance:
    """Vết truy nguyên. KHÔNG xuất ra JSON — dùng để debug và chặn mã bịa.

    Không có nhãn vàng nên provenance là công cụ debug chính. Quy tắc cứng:
    mã nào không truy được về một dòng cụ thể trong KB thì bị loại.
    """

    extractor: str = ""
    locate_method: str = ""
    link_path: str = ""
    kb_rows: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    #: ``p_t`` = P(nhãn vàng của span này thuộc MAPPABLE), tức là P(gold có
    #: candidates KHÔNG rỗng).  Đây là trục quyết định bỏ trống candidates —
    #: KHÔNG phải điểm rerank.  Bỏ trống chỉ đúng khi gold cũng rỗng, mà gold
    #: rỗng là chuyện của TYPE (TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM /
    #: KẾT_QUẢ_XÉT_NGHIỆM), không phải chuyện retrieval chắc hay không.
    #: Xem :func:`smart_medic.pipeline.select_candidate_set`.
    #:
    #: Mặc định 1.0 = "provider này khẳng định type"; provider nào có bằng
    #: chứng ngược lại thì hạ xuống.
    type_confidence: float = 1.0


@dataclass
class Mention:
    """Một khái niệm đã phát hiện."""

    span: Span
    type: ConceptType
    assertions: frozenset[Assertion] = frozenset()
    candidates: tuple[str, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        # Cưỡng chế ngay tại điểm dựng object, không đợi tới lúc emit.
        if self.candidates and self.type not in MAPPABLE:
            raise ValueError(
                f"{self.type.value} không được có candidates "
                f"(nhận {list(self.candidates)})"
            )
        if self.assertions and self.type not in ASSERTABLE:
            raise ValueError(
                f"{self.type.value} không được có assertions "
                f"(nhận {[a.value for a in self.assertions]})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Thứ tự trường theo đúng ví dụ trong đề bài."""
        return {
            "text": self.span.text,
            "type": self.type.value,
            "candidates": list(self.candidates),
            "assertions": sorted(a.value for a in self.assertions),
            "position": [self.span.start, self.span.end],
        }


# --- Lớp con cho type gate ----------------------------------------------------


@dataclass
class DiagnosisMention(Mention):
    """CHẨN_ĐOÁN — nhánh duy nhất được tra ICD-10."""

    type: ConceptType = ConceptType.CHAN_DOAN

    def __post_init__(self) -> None:
        self.type = ConceptType.CHAN_DOAN
        super().__post_init__()


@dataclass
class DrugMention(Mention):
    """THUỐC — nhánh duy nhất được tra RxNorm."""

    type: ConceptType = ConceptType.THUOC

    def __post_init__(self) -> None:
        self.type = ConceptType.THUOC
        super().__post_init__()


# --- Validate -----------------------------------------------------------------

_VALID_TYPES = {t.value for t in ConceptType}
_VALID_ASSERTS = {a.value for a in Assertion}


def validate_record(rec: Any, raw: str | None = None) -> list[str]:
    """Kiểm một dictionary concept. Trả về danh sách lỗi (rỗng = hợp lệ)."""
    errs: list[str] = []
    if not isinstance(rec, dict):
        return [f"không phải dict: {type(rec).__name__}"]

    for key in ("text", "type", "candidates", "assertions", "position"):
        if key not in rec:
            errs.append(f"thiếu trường '{key}'")
    if errs:
        return errs

    t = rec["type"]
    if t not in _VALID_TYPES:
        errs.append(f"type không hợp lệ: {t!r} (có viết tắt không?)")

    pos = rec["position"]
    if not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(x, int) for x in pos)):
        errs.append(f"position phải là [int, int], nhận {pos!r}")
    elif pos[0] < 0 or pos[1] <= pos[0]:
        errs.append(f"position không hợp lệ: {pos!r}")
    elif raw is not None:
        if pos[1] > len(raw):
            errs.append(f"position vượt độ dài văn bản: {pos!r} > {len(raw)}")
        elif raw[pos[0] : pos[1]] != rec["text"]:
            errs.append(
                f"BẤT BIẾN VỠ: raw[{pos[0]}:{pos[1]}]="
                f"{raw[pos[0]:pos[1]]!r} != text={rec['text']!r}"
            )

    cands = rec["candidates"]
    if not isinstance(cands, list):
        errs.append("candidates phải là list")
    elif cands and t not in {c.value for c in MAPPABLE}:
        errs.append(f"{t} không được có candidates (nhận {cands})")

    asserts = rec["assertions"]
    if not isinstance(asserts, list):
        errs.append("assertions phải là list")
    else:
        bad = set(asserts) - _VALID_ASSERTS
        if bad:
            errs.append(f"assertion không hợp lệ: {sorted(bad)}")
        if len(asserts) > 3:
            errs.append(f"tối đa 3 assertion, nhận {len(asserts)}")
        if asserts and t not in {c.value for c in ASSERTABLE}:
            errs.append(f"{t} không được có assertions (nhận {asserts})")

    return errs


def validate_file(records: Iterable[Any], raw: str | None = None) -> list[str]:
    errs: list[str] = []
    for i, rec in enumerate(records):
        errs.extend(f"[#{i}] {e}" for e in validate_record(rec, raw))
    return errs


def dumps(mentions: Iterable[Mention]) -> str:
    """JSON UTF-8, không escape ASCII — nếu không thì tiếng Việt thành \\uXXXX."""
    return json.dumps(
        [m.to_dict() for m in mentions], ensure_ascii=False, indent=2
    )
