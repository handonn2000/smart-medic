"""API ĐỌC CÔNG KHAI của Knowledge Base.

★ Đây là bề mặt DUY NHẤT mà downstream (pipeline giải bài) được phép dùng.
  Không import trực tiếp `kb.load`, `kb.extract`, hay `sqlite3`.

Quy tắc quyết định phạm vi ingest: *nếu một mẩu dữ liệu không phục vụ một
trong các hàm dưới đây thì không nạp vào KB.*

Trạng thái theo phase:
  Phase 1  lookup, search_lexical, neighbors
  Phase 3  ancestors, is_ancestor, lca, similarity   (cần bảng `closure`)
  Phase 5  search_dense                              (cần `kb.faiss`)
"""

from __future__ import annotations

from smart_medic.kb.query.models import Candidate, Concept, Term
from smart_medic.kb.query.store import KBStore, SchemaVersionMismatch

__all__ = [
    "Candidate",
    "Concept",
    "KBStore",
    "SchemaVersionMismatch",
    "Term",
    "ancestors",
    "is_ancestor",
    "lca",
    "lookup",
    "neighbors",
    "search_dense",
    "search_lexical",
    "similarity",
]


# ── Lõi ──────────────────────────────────────────────────────────────────


def lookup(store: KBStore, vocab: str, code: str) -> Concept | None:
    """Tra một concept theo (bộ mã, mã). Trả None nếu không có."""
    raise NotImplementedError("Phase 1")


def search_lexical(
    store: KBStore,
    text: str,
    *,
    vocab: str | None = None,
    lang: str | None = None,
    entity_kind: str | None = None,
    tiers: tuple[str, ...] | None = None,
    top_k: int = 20,
) -> list[Candidate]:
    """Truy hồi từ vựng bằng BM25 (FTS5). Sắp xếp giảm dần theo `score`."""
    raise NotImplementedError("Phase 1")


def search_dense(
    store: KBStore,
    text: str,
    *,
    vocab: str | None = None,
    top_k: int = 20,
) -> list[Candidate]:
    """Truy hồi ngữ nghĩa bằng FAISS."""
    raise NotImplementedError("Phase 5")


def neighbors(
    store: KBStore,
    concept_id: int,
    *,
    rel: str | None = None,
    direction: str = "out",
) -> list[Concept]:
    """Các concept kề qua `relations`. `direction` ∈ {'out', 'in', 'both'}."""
    raise NotImplementedError("Phase 1")


# ── Phân cấp (Phase 3) ───────────────────────────────────────────────────


def ancestors(store: KBStore, concept_id: int, *, max_dist: int | None = None) -> list[Concept]:
    """Mọi tổ tiên theo IS-A, đọc từ bảng `closure`."""
    raise NotImplementedError("Phase 3")


def is_ancestor(store: KBStore, ancestor_id: int, descendant_id: int) -> bool:
    """`ancestor_id` có phải tổ tiên của `descendant_id` không."""
    raise NotImplementedError("Phase 3")


def lca(store: KBStore, a: int, b: int) -> Concept | None:
    """Tổ tiên chung thấp nhất. SNOMED là DAG nên có thể có nhiều — trả cái sâu nhất."""
    raise NotImplementedError("Phase 3")


def similarity(store: KBStore, a: int, b: int, *, method: str = "wu_palmer") -> float:
    """Độ tương đồng ngữ nghĩa ∈ [0, 1]. `method` ∈ {'wu_palmer', 'lin', 'resnik'}."""
    raise NotImplementedError("Phase 3")
