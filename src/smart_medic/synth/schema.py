"""Kiểu dữ liệu của bộ sinh corpus, và **bộ dựng tài liệu ghi offset lúc chèn**.

★ ĐÂY LÀ LÝ DO TỒN TẠI CỦA CẢ HƯỚNG ANNOTATION-FIRST
─────────────────────────────────────────────────────
Cách làm ngược lại — sinh văn bản trước rồi đi tìm span bằng `txt.index(...)` —
đã gây hai sự cố đo được trong dự án:

    `sample_output.json` của BTC lệch offset 19/19 mục vì văn bản gốc dùng CRLF
    20/100 file `data/test` không ở dạng NFC, và `100.txt` trộn NFC với NFD
    NGAY BÊN TRONG một cụm: cùng chữ `"tiền sản giật"` mà chỗ dài 16 ký tự,
    chỗ khác 13

`DocBuilder` ghi offset **tại thời điểm nối chuỗi vào tài liệu**, nên sai số
bằng 0 *theo kiến tạo* chứ không phải nhờ kiểm tra sau. Không có `index()`,
không có `find()`, không có so khớp chuỗi ở bất kỳ đâu trong `synth/`.

★ NHIỄU PHẢI ĐI QUA `transform`, KHÔNG ĐƯỢC SỬA VĂN BẢN SAU KHI DỰNG
─────────────────────────────────────────────────────────────────────
Chuẩn hoá NFD **đổi độ dài chuỗi**. Nếu tiêm nhiễu sau khi đã ghi offset thì mọi
span sau điểm tiêm đều lệch — im lặng, đúng lớp bug mà kiến trúc này sinh ra để
diệt. Nên `build(transform=…)` áp phép biến đổi lên **từng mảnh** rồi mới cộng
dồn vị trí: offset luôn tính trên chuỗi CUỐI CÙNG.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

TYPE_SYMPTOM = "TRIỆU_CHỨNG"
TYPE_TEST = "TÊN_XÉT_NGHIỆM"
TYPE_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"
TYPE_DIAGNOSIS = "CHẨN_ĐOÁN"
TYPE_DRUG = "THUỐC"

ALL_TYPES = (TYPE_SYMPTOM, TYPE_TEST, TYPE_RESULT, TYPE_DIAGNOSIS, TYPE_DRUG)

# Đề bài: chỉ hai nhãn này được gán mã.
TYPES_WITH_CANDIDATES = frozenset({TYPE_DIAGNOSIS, TYPE_DRUG})
# Đề bài: assertion chỉ áp cho ba nhãn này.
TYPES_WITH_ASSERTIONS = frozenset({TYPE_DIAGNOSIS, TYPE_DRUG, TYPE_SYMPTOM})

ASSERTIONS = ("isNegated", "isFamily", "isHistorical")


@dataclass(slots=True)
class Concept:
    """Một khái niệm lấy từ KB, kèm các cách nói bề mặt của nó.

    `codes` rỗng với TRIỆU_CHỨNG / TÊN_XN / KẾT_QUẢ_XN — đề bài quy định vậy, và
    Jaccard cho rỗng-gặp-rỗng bằng 1,0 nên rỗng là đáp án ĐÚNG, không phải thiếu.
    """

    type: str
    surfaces: tuple[str, ...]
    codes: tuple[str, ...] = ()
    origin: str = ""  # nguồn cách nói: atc | lab_panel | frozen_llm | mask

    def __post_init__(self) -> None:
        if self.codes and self.type not in TYPES_WITH_CANDIDATES:
            raise ValueError(f"{self.type} không được có mã: {self.codes}")


@dataclass(slots=True)
class SynthSpan:
    text: str
    type: str
    start: int
    end: int
    candidates: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "type": self.type,
            "candidates": list(self.candidates),
            "assertions": list(self.assertions),
            "position": [self.start, self.end],
        }


@dataclass(slots=True)
class SynthDoc:
    name: str
    text: str
    spans: list[SynthSpan] = field(default_factory=list)
    # Cụm gây nhiễu cố ý KHÔNG gán nhãn (§2.5). Ghi lại để thống kê và để test
    # khẳng định chúng thật sự không có span nào phủ.
    distractors: list[tuple[int, int]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps([s.to_dict() for s in self.spans], ensure_ascii=False, indent=2)


_Kind = Literal["plain", "span"]


class DocBuilder:
    """Nối tài liệu theo từng mảnh; span biết vị trí của mình ngay lúc được chèn.

    >>> b = DocBuilder()
    >>> b.plain("Chẩn đoán: ")
    >>> b.span("viêm phổi", TYPE_DIAGNOSIS, codes=("J18.9",))
    >>> doc = b.build("x")
    >>> doc.text[doc.spans[0].start : doc.spans[0].end]
    'viêm phổi'
    """

    __slots__ = ("_parts", "_distractors")

    def __init__(self) -> None:
        self._parts: list[tuple[_Kind, str, dict]] = []
        self._distractors: list[int] = []

    def plain(self, s: str) -> None:
        if s:
            self._parts.append(("plain", s, {}))

    def distractor(self, s: str) -> None:
        """Cụm gây nhiễu — chèn vào văn bản nhưng **cố ý không gán nhãn**.

        Đây là thứ dạy model *khi nào KHÔNG bắn*. Giám sát xa từ từ điển không
        bao giờ có lớp dữ liệu này, và precision là đòn bẩy lớn thứ hai (+0,120).
        """
        if not s:
            return
        self._distractors.append(len(self._parts))
        self._parts.append(("plain", s, {"distractor": True}))

    def span(
        self,
        text: str,
        type_: str,
        *,
        codes: tuple[str, ...] = (),
        assertions: tuple[str, ...] = (),
    ) -> None:
        if type_ not in ALL_TYPES:
            raise ValueError(f"nhãn lạ: {type_!r}")
        if codes and type_ not in TYPES_WITH_CANDIDATES:
            raise ValueError(f"{type_} không được có candidates")
        if assertions and type_ not in TYPES_WITH_ASSERTIONS:
            raise ValueError(f"{type_} không được có assertions")
        if not text.strip():
            raise ValueError("span rỗng hoặc toàn khoảng trắng")
        self._parts.append(
            ("span", text, {"type": type_, "codes": codes, "assertions": assertions})
        )

    def build(self, name: str, transform: Callable[[str], str] | None = None) -> SynthDoc:
        """Nối lại. `transform` áp lên TỪNG mảnh TRƯỚC khi cộng dồn vị trí.

        Thứ tự đó là điều kiện để offset đúng khi nhiễu làm đổi độ dài chuỗi
        (NFD). Đừng đảo.
        """
        chunks: list[str] = []
        spans: list[SynthSpan] = []
        distractors: list[tuple[int, int]] = []
        pos = 0
        for i, (kind, raw, meta) in enumerate(self._parts):
            s = transform(raw) if transform else raw
            if kind == "span":
                spans.append(
                    SynthSpan(s, meta["type"], pos, pos + len(s), meta["codes"], meta["assertions"])
                )
            elif i in self._distractors:
                distractors.append((pos, pos + len(s)))
            chunks.append(s)
            pos += len(s)
        return SynthDoc(name=name, text="".join(chunks), spans=spans, distractors=distractors)
