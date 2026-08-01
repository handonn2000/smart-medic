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

import sqlite3

from smart_medic.kb.query.lexical import build_match_expr
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

_CONCEPT_COLS = "concept_id, vocab, code, entity_kind, pref_vi, pref_en, is_active"


def _to_concept(row: sqlite3.Row) -> Concept:
    return Concept(
        concept_id=row["concept_id"],
        vocab=row["vocab"],
        code=row["code"],
        entity_kind=row["entity_kind"],
        pref_vi=row["pref_vi"],
        pref_en=row["pref_en"],
        is_active=bool(row["is_active"]),
    )


# ── Lõi ──────────────────────────────────────────────────────────────────


def lookup(store: KBStore, vocab: str, code: str) -> Concept | None:
    """Tra một concept theo (bộ mã, mã). Trả None nếu không có."""
    row = store.conn.execute(
        f"SELECT {_CONCEPT_COLS} FROM concepts WHERE vocab = ? AND code = ?",
        (vocab, code),
    ).fetchone()
    return _to_concept(row) if row else None


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
    """Truy hồi từ vựng bằng BM25 (FTS5). Sắp xếp giảm dần theo `score`.

    Gộp theo concept: mỗi concept chỉ xuất hiện một lần, giữ term khớp nhất.
    """
    expr = build_match_expr(text)
    if not expr:
        return []

    where = ["terms_fts MATCH ?"]
    params: list[object] = [expr]
    if vocab:
        where.append("c.vocab = ?")
        params.append(vocab)
    if lang:
        where.append("t.lang = ?")
        params.append(lang)
    if entity_kind:
        where.append("c.entity_kind = ?")
        params.append(entity_kind)
    if tiers:
        where.append(f"t.tier IN ({','.join('?' * len(tiers))})")
        params.extend(tiers)

    # Lấy dư rồi mới gộp theo concept, tránh trường hợp một concept có nhiều
    # term khớp chiếm hết top-k.
    params.append(top_k * 8)
    sql = f"""
        SELECT {", ".join("c." + col for col in _CONCEPT_COLS.split(", "))},
               t.term AS matched_term, t.tier AS matched_tier,
               bm25(terms_fts) AS bm25_score
        FROM terms_fts
        JOIN terms t    ON t.term_id = terms_fts.rowid
        JOIN concepts c ON c.concept_id = t.concept_id
        WHERE {" AND ".join(where)}
        ORDER BY bm25_score
        LIMIT ?
    """

    out: list[Candidate] = []
    seen: set[int] = set()
    for row in store.conn.execute(sql, params):
        cid = row["concept_id"]
        if cid in seen:
            continue
        seen.add(cid)
        out.append(
            Candidate(
                concept=_to_concept(row),
                score=-float(row["bm25_score"]),  # bm25 âm → đổi dấu
                matched_term=row["matched_term"],
                matched_tier=row["matched_tier"],
            )
        )
        if len(out) >= top_k:
            break
    return out


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
    if direction not in ("out", "in", "both"):
        raise ValueError(f"direction không hợp lệ: {direction!r}")

    clauses = []
    if direction in ("out", "both"):
        clauses.append(("src_concept", "dst_concept"))
    if direction in ("in", "both"):
        clauses.append(("dst_concept", "src_concept"))

    found: dict[int, Concept] = {}
    for key_col, other_col in clauses:
        sql = (
            f"SELECT {', '.join('c.' + col for col in _CONCEPT_COLS.split(', '))} "
            f"FROM relations r JOIN concepts c ON c.concept_id = r.{other_col} "
            f"WHERE r.{key_col} = ?"
        )
        params: list[object] = [concept_id]
        if rel:
            sql += " AND r.rel = ?"
            params.append(rel)
        for row in store.conn.execute(sql, params):
            found.setdefault(row["concept_id"], _to_concept(row))
    return [found[k] for k in sorted(found)]


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
