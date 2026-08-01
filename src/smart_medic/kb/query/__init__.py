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

# Lấy dư từ FTS trước khi lọc/gộp: một concept có thể có nhiều term cùng khớp,
# và các bộ lọc lang/entity_kind/tier chạy SAU tầng FTS nên cần khoảng đệm.
FETCH_MULTIPLIER = 40

# Số ứng viên gom về trước khi re-rank, rồi mới cắt xuống `top_k`.
#
# ★ SÂU THEO NHÁNH, không dùng chung một số — đo chéo mới lộ ra:
#
#                        pool 20              pool 60
#   ICD  (gold lâm sàng) R@5 0,833 R@20 0,857  R@5 0,857 R@20 1,000  ← sâu THẮNG
#   thuốc (gold BTC)     R@5 0,818 R@20 0,909  R@5 0,818 R@20 0,818  ← sâu THUA
#
# Nhánh ICD cần pool sâu vì mã "không xác định" mà người gán nhãn chọn
# (`J18.9`, `E11.9`) nằm ở **hạng 21–26** — re-rank trên đúng top-20 không bao
# giờ với tới. Nới ra thì `Recall@20` TĂNG thật, không chỉ đổi thứ tự.
#
# Nhánh thuốc thì ngược: đáp án vốn đã nằm trong top-20, nới pool chỉ rước thêm
# ứng viên nhiễu và đẩy ca `nystatin` (gold là hoạt chất) văng khỏi top-20.
RERANK_POOL: dict[str, int] = {"icd10": 60, "rxnorm": 20}
RERANK_POOL_DEFAULT = 20


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
    max_fan_in: int | None = None,
    top_k: int = 20,
    rerank: bool = False,
) -> list[Candidate]:
    """Truy hồi từ vựng bằng BM25 (FTS5). Sắp xếp giảm dần theo `score`.

    Gộp theo concept: mỗi concept chỉ xuất hiện một lần, giữ term khớp nhất.

    `max_fan_in` lọc term mượn từ SNOMED theo số concept cùng trỏ về một mã ICD
    (§P3.2). Nạp rộng ở build-time, siết ở ĐÂY — nhờ vậy chỉnh ngưỡng không phải
    build lại, và ngưỡng thành tham số đo được trên probe set.

    `rerank` bật bước xếp hạng lại (`kb.query.rerank`), khác nhau theo nhánh:
    THUỐC dùng độ phủ token × TTY prior; CHẨN_ĐOÁN dùng độ phủ token trên tên
    đã bỏ đuôi định tính × prior mã khoảng.

    Lưu ý: nó **cũng gom ứng viên sâu hơn** `top_k` (xem `RERANK_POOL`) rồi mới
    cắt, nên `Recall@top_k` có thể **TĂNG** chứ không chỉ đổi thứ tự — đo được
    0,857 → 1,000 ở nhánh ICD.

    Mặc định TẮT để hợp đồng API §4.2 không đổi hành vi dưới chân code đã viết.
    """
    expr = build_match_expr(text, vocab=vocab)
    if not expr:
        return []

    # ★ Khi re-rank, gom SÂU HƠN top_k rồi mới cắt. Đo được: mã `.9` mà gold hay
    #   chọn (`J18.9`, `E11.9`) nằm ở hạng 21–26 — re-rank trên đúng top-20
    #   không bao giờ với tới chúng. Nhờ nới pool, `Recall@top_k` có thể TĂNG.
    pool = max(top_k, RERANK_POOL.get(vocab or "", RERANK_POOL_DEFAULT)) if rerank else top_k

    # ★ Hai tầng, cố ý. Tầng trong CHỈ đụng FTS (không JOIN) nên planner buộc
    #   phải lấy FTS làm vòng ngoài; tầng ngoài join trên tập đã nhỏ.
    #   Viết một tầng thì planner chọn `concepts` làm vòng ngoài rồi SCAN
    #   terms_fts ở trong cùng — 7,4 s/truy vấn (đo được, xem docs §10).
    where = []
    params: list[object] = [expr, pool * FETCH_MULTIPLIER]
    if lang:
        where.append("t.lang = ?")
        params.append(lang)
    if entity_kind:
        where.append("c.entity_kind = ?")
        params.append(entity_kind)
    if tiers:
        where.append(f"t.tier IN ({','.join('?' * len(tiers))})")
        params.extend(tiers)
    if max_fan_in is not None:
        where.append(
            "(json_extract(t.evidence, '$.fan_in') IS NULL "
            " OR json_extract(t.evidence, '$.fan_in') <= ?)"
        )
        params.append(max_fan_in)

    sql = f"""
        WITH hits AS (
            SELECT rowid AS term_id, bm25(terms_fts) AS bm25_score
            FROM terms_fts
            WHERE terms_fts MATCH ?
            ORDER BY bm25_score
            LIMIT ?
        )
        SELECT {", ".join("c." + col for col in _CONCEPT_COLS.split(", "))},
               t.term AS matched_term, t.tier AS matched_tier, hits.bm25_score
        FROM hits
        JOIN terms t    ON t.term_id = hits.term_id
        JOIN concepts c ON c.concept_id = t.concept_id
        {("WHERE " + " AND ".join(where)) if where else ""}
        ORDER BY hits.bm25_score
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
        if len(out) >= pool:
            break

    if rerank and vocab in ("rxnorm", "icd10"):
        from smart_medic.kb.query import rerank as _rr

        fn = _rr.rerank_drug if vocab == "rxnorm" else _rr.rerank_disease
        out = fn(store, text, out)
    return out[:top_k]


def search_dense(
    store: KBStore,
    text: str,
    *,
    vocab: str | None = None,
    top_k: int = 20,
) -> list[Candidate]:
    """Truy hồi ngữ nghĩa bằng FAISS.

    Bổ trợ cho `search_lexical`: BM25 mạnh khi mention chia sẻ token với tên
    chuẩn, dense mạnh khi KHÔNG có token chung.

    Nạp muộn `kb.dense` để image `runtime` không bắt buộc phải có torch/faiss.
    Ném `IndexOutOfSync` nếu index lệch với artifact — thà nổ còn hơn trả về
    concept sai một cách im lặng.
    """
    from smart_medic.kb import dense

    index, _meta = dense.load_index(db=store.path)
    # Lấy dư rồi lọc theo vocab: FAISS không biết bộ mã.
    scores, ids = index.search(dense.embed_query(text), top_k * 10 if vocab else top_k)

    out: list[Candidate] = []
    for score, cid in zip(scores[0], ids[0], strict=True):
        if cid < 0:
            continue
        concept = lookup_by_id(store, int(cid))
        if concept is None or (vocab and concept.vocab != vocab):
            continue
        out.append(
            Candidate(
                concept=concept,
                score=float(score),
                matched_term=concept.label,
                matched_tier="authoritative",
            )
        )
        if len(out) >= top_k:
            break
    return out


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
    """Mọi tổ tiên theo IS-A, đọc từ bảng `closure`. Gần trước, xa sau."""
    sql = (
        f"SELECT {', '.join('c.' + col for col in _CONCEPT_COLS.split(', '))}, cl.min_dist "
        "FROM closure cl JOIN concepts c ON c.concept_id = cl.ancestor "
        "WHERE cl.descendant = ?"
    )
    params: list[object] = [concept_id]
    if max_dist is not None:
        sql += " AND cl.min_dist <= ?"
        params.append(max_dist)
    sql += " ORDER BY cl.min_dist, c.concept_id"
    return [_to_concept(r) for r in store.conn.execute(sql, params)]


def is_ancestor(store: KBStore, ancestor_id: int, descendant_id: int) -> bool:
    """`ancestor_id` có phải tổ tiên của `descendant_id` không. Tra bảng, O(log n)."""
    row = store.conn.execute(
        "SELECT 1 FROM closure WHERE ancestor = ? AND descendant = ? LIMIT 1",
        (ancestor_id, descendant_id),
    ).fetchone()
    return row is not None


def _depth(store: KBStore, concept_id: int) -> int:
    """Độ sâu = khoảng cách xa nhất tới một gốc. 0 nếu là gốc."""
    row = store.conn.execute(
        "SELECT max(min_dist) FROM closure WHERE descendant = ?", (concept_id,)
    ).fetchone()
    return row[0] or 0


def lca(store: KBStore, a: int, b: int) -> Concept | None:
    """Tổ tiên chung thấp nhất.

    Đồ thị IS-A là DAG (một mã có thể có nhiều cha) nên có thể có nhiều tổ tiên
    chung — trả cái SÂU NHẤT, tức cụ thể nhất.
    """
    if a == b:
        return lookup_by_id(store, a)
    row = store.conn.execute(
        "SELECT x.ancestor, max(x.min_dist + y.min_dist) AS cost "
        "FROM closure x JOIN closure y ON x.ancestor = y.ancestor "
        "WHERE x.descendant = ? AND y.descendant = ? "
        "GROUP BY x.ancestor ORDER BY min(x.min_dist + y.min_dist), x.ancestor LIMIT 1",
        (a, b),
    ).fetchone()
    return lookup_by_id(store, row["ancestor"]) if row else None


def lookup_by_id(store: KBStore, concept_id: int) -> Concept | None:
    row = store.conn.execute(
        f"SELECT {_CONCEPT_COLS} FROM concepts WHERE concept_id = ?", (concept_id,)
    ).fetchone()
    return _to_concept(row) if row else None


def similarity(store: KBStore, a: int, b: int, *, method: str = "wu_palmer") -> float:
    """Độ tương đồng ngữ nghĩa ∈ [0, 1].

    Wu-Palmer: `2·depth(LCA) / (depth(a) + depth(b))` — chỉ cần độ sâu và LCA,
    cả hai đọc thẳng từ `closure`, **không cần corpus**. Điểm này quan trọng vì
    ta không có corpus tiếng Việt gắn nhãn để ước lượng Information Content
    theo cách cổ điển.
    """
    if method != "wu_palmer":
        raise ValueError(f"phương pháp chưa hỗ trợ: {method!r}")
    if a == b:
        return 1.0
    common = lca(store, a, b)
    if common is None:
        return 0.0
    da, db = _depth(store, a), _depth(store, b)
    if da + db == 0:
        return 0.0
    return min(1.0, 2 * _depth(store, common.concept_id) / (da + db))
