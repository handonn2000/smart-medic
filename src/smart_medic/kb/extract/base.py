"""Giao diện chung cho mọi extractor.

Thêm một nguồn mới (LOINC, UMLS…) = thêm MỘT file implement `Extractor`,
không sửa file cũ. `load` không biết gì về nguồn — nó chỉ đọc staging.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class StagingBatch:
    """Kết quả của một extractor, đúng theo hợp đồng ở `kb/staging.py`.

    Dùng list[dict] thay vì pyarrow.Table để extractor không phải biết pyarrow;
    việc ép kiểu và ghi parquet do `extract/__init__.py` lo tập trung một chỗ.
    """

    concepts: list[dict] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    attributes: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def extend(self, other: StagingBatch) -> None:
        self.concepts.extend(other.concepts)
        self.terms.extend(other.terms)
        self.relations.extend(other.relations)
        self.attributes.extend(other.attributes)
        self.sources.extend(other.sources)

    def counts(self) -> dict[str, int]:
        return {
            "concepts": len(self.concepts),
            "terms": len(self.terms),
            "relations": len(self.relations),
            "attributes": len(self.attributes),
            "sources": len(self.sources),
        }


@runtime_checkable
class Extractor(Protocol):
    """Đọc một nguồn thô, trả về `StagingBatch`. Không ghi file, không đụng DB."""

    name: str

    def available(self) -> bool:
        """Nguồn thô có tồn tại không — cho phép build từng phần khi thiếu file."""
        ...

    def extract(self) -> StagingBatch: ...


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    """Checksum của file nguồn, ghi vào bảng `sources` để truy vết provenance."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()
