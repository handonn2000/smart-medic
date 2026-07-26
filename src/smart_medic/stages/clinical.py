"""High-precision mention-first symptom discovery for v3.

The ICD gazetteer can only discover a span after a terminology name matches.
This provider detects common Vietnamese surface forms independently of linking,
so colloquial symptoms can still receive the required type and raw offsets.
"""

from __future__ import annotations

import re

from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef
from .extract import Candidate


_SYMPTOM_PATTERNS = (
    r"đi\s+(?:tiêu|ngoài)\s+ra\s+máu",
    r"đi\s+ngoài\s+phân\s+đen",
    r"nôn\s+ra\s+máu",
    r"chảy\s+máu\s+mũi",
    r"vàng\s+da(?:\s+vàng\s+mắt)?",
    r"nổi\s+mẩn(?:\s+đỏ)?(?:\s+ngứa)?",
    r"đau\s+bụng(?:\s+(?:quanh\s+rốn|thượng\s+vị|âm\s+ỉ|dữ\s+dội|râm\s+ran))?",
    r"đau\s+(?:đầu\s+gối|ngực|lưng|đầu|bao\s+tử)(?:\s+(?:phải|trái|âm\s+ỉ))?",
    r"buồn\s+nôn",
    r"khó\s+thở(?:\s+(?:liên\s+tục|khi\s+gắng\s+sức))?",
    r"mệt(?:\s+mỏi)?(?:\s+kéo\s+dài)?",
    r"chóng\s+mặt",
    r"hồi\s+hộp",
    r"rợn\s+người",
    r"run\s+tay",
    r"tiêu\s+chảy",
    r"ho(?:\s+(?:khan|đờm(?:\s+(?:xanh|vàng))?|ra\s+máu))?",
    r"sốt(?:\s+(?:cao|nhẹ|kéo\s+dài))?",
    r"phù(?!\s+hợp)(?:\s+(?:phổi|chân|hai\s+chi))?",
    r"ngứa(?:\s+(?:da|toàn\s+thân))?",
    r"tiểu\s+ít",
)
_SYMPTOM_RE = re.compile(
    r"(?<![\wăâđêôơư])(?:"
    + "|".join(_SYMPTOM_PATTERNS)
    + r")(?![\wăâđêôơư])"
)


class ClinicalSymptomExtractor:
    name = "clinical_symptom_v3"

    def extract(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        for match in _SYMPTOM_RE.finditer(tref.norm):
            ns, ne = match.span()
            surface = match.group()
            before = tref.norm[max(0, ns - 28):ns]
            after = tref.norm[ne:min(len(tref.norm), ne + 32)]
            if surface.startswith("sốt") and re.search(r"(?:hạ|kháng)\s*$", before):
                continue
            if surface == "ho" and re.match(
                r"\s+(?:bệnh|rối\s+loạn|rung\s+nhĩ|đái\s+tháo\s+đường)", after
            ):
                continue
            rs, re_ = tref.to_raw(ns, ne)
            span = Span(rs, re_, tref.raw[rs:re_])
            out.append(Candidate(
                span=span,
                type=ConceptType.TRIEU_CHUNG,
                provenance=Provenance(
                    extractor=self.name,
                    locate_method="clinical_phrase_grammar",
                    link_path="symptom_surface_rule",
                    scores={"confidence": 0.90},
                    evidence={"normalized_surface": surface},
                ),
            ))
        return out
