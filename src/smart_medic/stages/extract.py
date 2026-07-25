"""Extract — interface + implementation cho v0.

Provider pattern (system design §2, quyết định #2): Extractor có nhiều
implementation qua các vòng. Nếu lời gọi LLM nằm rải trong pipeline thì v3 phải
viết lại pipeline; nằm sau interface thì v3 chỉ đổi một dòng config.

    v0  GazetteerExtractor   offline, tất định   ← đang ở đây
    v1  LLMExtractor         cần API
    v3  EncoderExtractor     XLM-R distill, offline lại
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..kb.store import KnowledgeBase
from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef


@dataclass
class Candidate:
    """Một khái niệm ứng viên do Extractor đề xuất, ĐÃ định vị."""

    span: Span
    type: ConceptType
    codes: tuple[str, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)


class Extractor(Protocol):
    name: str

    def extract(self, tref: TextRef) -> list[Candidate]:
        ...


class GazetteerExtractor:
    """Baseline v0 — quét tên bệnh ICD nguyên văn.

    Đây cũng là BASELINE HỒI QUY VĨNH VIỄN: mọi vòng sau phải đo được là hơn nó.
    Chạy vài giây, offline 100%, không phụ thuộc mạng, hoàn toàn tất định.

    Type gate ngay tại đây (system design §4.4): mã chương R là "triệu chứng &
    dấu hiệu bất thường", KHÔNG phải chẩn đoán. Đo được 27% mention khớp
    nguyên văn rơi vào chương R (khó thở→R06.0, đau đầu→R51). Những mention
    này được gán TRIỆU_CHỨNG và candidates RỖNG — vì schema bắt buộc thế.
    """

    name = "gazetteer"

    def __init__(self, kb: KnowledgeBase, *, max_candidates: int = 2) -> None:
        self.kb = kb
        self.max_candidates = max_candidates

    def extract(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        for m in self.kb.icd_gaz.scan(tref.norm):
            rs, re_ = tref.to_raw(m.ns, m.ne)
            text = tref.raw[rs:re_]
            span = Span(rs, re_, text)
            if not span.verify(tref.raw):
                continue                       # bất biến vỡ → loại, không đoán

            prov = Provenance(
                extractor=self.name,
                locate_method="gazetteer_scan",
                link_path="gazetteer_exact",
                kb_rows=[f"icd:{c}" for c in m.codes],
                scores={"confidence": 1.0},
            )

            if m.is_symptom_chapter:
                # Chương R → triệu chứng. KHÔNG gán mã: schema cấm.
                out.append(Candidate(span, ConceptType.TRIEU_CHUNG, (), prov))
            else:
                out.append(
                    Candidate(
                        span,
                        ConceptType.CHAN_DOAN,
                        m.codes[: self.max_candidates],
                        prov,
                    )
                )
        return out
