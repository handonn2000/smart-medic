"""Giao diện chung cho enricher.

★ Ba quy tắc bất biến (§P3.3), enforce ngay ở tầng này:
  1. **Chỉ THÊM, không sửa.** Enricher chỉ trả dòng mới; không có đường nào để
     nó đụng vào dòng `tier='authoritative'`.
  2. **Gỡ được bằng một câu lệnh.** Mọi dòng sinh ra đều mang tier khác
     `authoritative`, nên `DELETE FROM terms WHERE tier != 'authoritative'`
     đưa KB về đúng trạng thái trước enrichment.
  3. **Mọi dòng `derived` phải có `evidence`.** `EnrichBatch.add_term` bắt buộc
     truyền evidence khi tier là `derived`; thiếu thì `ValueError` ngay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from smart_medic.kb.normalize.text import normalize_pair


@dataclass(slots=True)
class EnrichBatch:
    """Dòng CỘNG THÊM. Cùng schema với staging đã chuẩn hoá."""

    terms: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    attributes: list[dict] = field(default_factory=list)
    # Provenance của chính nguồn làm giàu. Bắt buộc: `terms.source` có FK tới
    # `sources`, nên nguồn không đăng ký thì load fail — và đó là hành vi đúng.
    sources: list[dict] = field(default_factory=list)

    def add_term(
        self,
        *,
        vocab: str,
        code: str,
        source: str,
        term: str,
        lang: str,
        term_type: str,
        tier: str,
        evidence: dict | None = None,
    ) -> None:
        if tier == "authoritative":
            raise ValueError("enricher không được sinh dòng tier='authoritative'")
        if tier == "derived" and not evidence:
            raise ValueError(f"term derived thiếu evidence: {term!r}")
        norm, ascii_ = normalize_pair(term)
        if not norm:
            return
        self.terms.append(
            {
                "vocab": vocab,
                "code": code,
                "source": source,
                "term": term,
                "norm_term": norm,
                "ascii_term": ascii_,
                "lang": lang,
                "term_type": term_type,
                "is_preferred": False,
                "tier": tier,
                "evidence": json.dumps(evidence, ensure_ascii=False) if evidence else None,
            }
        )

    def add_relation(
        self,
        *,
        src_vocab: str,
        src_code: str,
        rel: str,
        dst_vocab: str,
        dst_code: str,
        tier: str,
        rel_group: int | None = None,
        priority: int | None = None,
        meta: dict | None = None,
    ) -> None:
        if tier == "authoritative":
            raise ValueError("enricher không được sinh dòng tier='authoritative'")
        self.relations.append(
            {
                "src_vocab": src_vocab,
                "src_code": src_code,
                "rel": rel,
                "dst_vocab": dst_vocab,
                "dst_code": dst_code,
                "rel_group": rel_group,
                "priority": priority,
                "tier": tier,
                "meta": json.dumps(meta, ensure_ascii=False) if meta else None,
            }
        )

    def add_attribute(self, *, vocab: str, code: str, attr: str, value: str) -> None:
        self.attributes.append({"vocab": vocab, "code": code, "attr": attr, "value": value})

    def register_source(
        self,
        *,
        name: str,
        release: str | None = None,
        origin_file: str | None = None,
        sha256: str | None = None,
        n_rows: int = 0,
    ) -> None:
        self.sources.append(
            {
                "source": name,
                "release": release,
                "origin_file": origin_file,
                "sha256": sha256,
                "n_rows": n_rows,
            }
        )

    def extend(self, other: EnrichBatch) -> None:
        self.terms.extend(other.terms)
        self.relations.extend(other.relations)
        self.attributes.extend(other.attributes)
        self.sources.extend(other.sources)

    def counts(self) -> dict[str, int]:
        return {
            "terms": len(self.terms),
            "relations": len(self.relations),
            "attributes": len(self.attributes),
        }


@runtime_checkable
class Enricher(Protocol):
    """Nguồn làm giàu. Bật/tắt độc lập để đo đóng góp riêng (§P3.3 quy tắc 3)."""

    name: str

    def available(self) -> bool: ...

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        """`known` = {vocab: {code, …}} — các concept đã có từ pha authoritative.

        Enricher chỉ được gắn thêm vào concept đã tồn tại, không tự tạo concept
        mới. Đó là cách bảo đảm bộ mã vẫn tập trung vào ICD/RxNorm được chấm.
        """
        ...
