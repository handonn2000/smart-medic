"""Kiểu dữ liệu trả về của API đọc.

Đây là phần *công khai* của KB: downstream chỉ thấy các dataclass này, không
thấy `sqlite3.Row`. Nhờ vậy đổi backend lưu trữ không phá code phía dưới.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Term:
    term_id: int
    concept_id: int
    source: str
    term: str
    lang: str
    term_type: str
    is_preferred: bool
    tier: str = "authoritative"
    evidence: str | None = None

    @property
    def evidence_obj(self) -> dict | None:
        """`evidence` đã parse. Trả None nếu rỗng hoặc không phải JSON hợp lệ."""
        if not self.evidence:
            return None
        try:
            return json.loads(self.evidence)
        except json.JSONDecodeError:
            return None


@dataclass(frozen=True, slots=True)
class Concept:
    concept_id: int
    vocab: str
    code: str
    entity_kind: str
    pref_vi: str | None = None
    pref_en: str | None = None
    is_active: bool = True
    attributes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Tên hiển thị — ưu tiên tiếng Việt vì input của đề là tiếng Việt."""
        return self.pref_vi or self.pref_en or self.code


@dataclass(frozen=True, slots=True)
class Candidate:
    """Một ứng viên do retrieval trả về.

    `score` chỉ so sánh được trong cùng một lần gọi, không so được giữa các
    phương pháp khác nhau (BM25 và cosine không cùng thang).
    """

    concept: Concept
    score: float
    matched_term: str
    matched_tier: str = "authoritative"

    @property
    def code(self) -> str:
        return self.concept.code
