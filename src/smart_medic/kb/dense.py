"""Pha 5 — dense index. `kb.sqlite` → `kb.faiss` + `kb.faiss.meta.json`.

Bổ trợ cho BM25 chứ không thay thế: BM25 mạnh khi mention chia sẻ token với tên
chuẩn, dense mạnh khi **không có token chung** — đúng lớp ca mà baseline Phase 2
trượt hết 7/7.

★ Bất biến sống còn: `concept_id` trong FAISS phải khớp `kb.sqlite`.
  FAISS trả về id kiểu int; nếu artifact được build lại và id đổi, mọi truy vấn
  dense sẽ trỏ **nhầm concept mà không báo lỗi** — dạng hỏng âm thầm nguy hiểm
  nhất của cả kiến trúc (§8).

  Cách chặn: `kb.faiss.meta.json` ghi `artifact_sha256` của .sqlite lúc dựng
  index. `load_index()` đối chiếu và **từ chối** nếu lệch.

── Phạm vi embedding ────────────────────────────────────────────────────
Chỉ nhúng **tên ưu tiên của mỗi concept** (`pref_vi` hoặc `pref_en`), không
nhúng cả 633.000 term. Lý do: dense lo phần *ngữ nghĩa của khái niệm*, còn sự
đa dạng cách diễn đạt đã do BM25 + enrichment lo. Nhúng một vector/concept giữ
index nhỏ (141.948 × 384 float32 ≈ 218 MB) và tra cứu tức thì.

── Ràng buộc tái lập ────────────────────────────────────────────────────
Model được **ghim theo revision**. Ở image `builder` nên bake sẵn model vào
image thay vì tải lúc chạy — PRD §8 cấm phụ thuộc mạng khi BTC dựng lại.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.schema.version import SCHEMA_VERSION

# Ghim chặt. Đổi model hoặc revision là phải dựng lại index.
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
EMBED_DIM = 384
BATCH_SIZE = 256


class IndexOutOfSync(RuntimeError):
    """FAISS index được dựng từ một artifact .sqlite khác."""


@dataclass(slots=True)
class IndexMeta:
    schema_version: str
    artifact_sha256: str
    model: str
    revision: str
    dim: int
    n_vectors: int

    def to_json(self) -> str:
        # `asdict` chứ không `__dict__`: dataclass dùng slots=True nên không có
        # __dict__ — bản đầu nổ đúng ở đây, sau khi đã nhúng xong 142k vector.
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> IndexMeta:
        return cls(**json.loads(text))


def meta_path(index_path: Path | None = None) -> Path:
    """`kb.faiss` → `kb.faiss.meta.json`.

    NỐI thêm đuôi chứ không dùng `with_suffix` — `with_suffix` THAY đuôi nên
    `kb.faiss` thành `kb.meta.json`, lệch với tên mà README, Dockerfile và
    `.dockerignore` tham chiếu. Build vẫn báo thành công còn `load_index()`
    thì không tìm thấy meta: hỏng ở chỗ khác với chỗ gây lỗi.
    """
    path = index_path or config.KB_FAISS
    return path.with_name(path.name + ".meta.json")


def _artifact_sha(db: Path) -> str:
    """sha256 của .sqlite, lấy từ manifest — không tính lại cho nhanh."""
    from smart_medic.kb.load import manifest

    return manifest.read()["artifact_sha256"] if config.KB_MANIFEST.is_file() else ""


def _rows(db: Path) -> tuple[list[int], list[str]]:
    """(concept_id, văn bản để nhúng) — ưu tiên tên tiếng Việt."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        ids, texts = [], []
        for cid, vi, en in conn.execute(
            "SELECT concept_id, pref_vi, pref_en FROM concepts "
            "WHERE is_active = 1 ORDER BY concept_id"
        ):
            text = (vi or en or "").strip()
            if text:
                ids.append(cid)
                texts.append(text)
        return ids, texts
    finally:
        conn.close()


def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)


def build(db: Path | None = None, out: Path | None = None) -> IndexMeta:
    import faiss
    import numpy as np

    db = db or config.KB_SQLITE
    out = out or config.KB_FAISS
    ids, texts = _rows(db)
    if not ids:
        raise RuntimeError("không có concept nào để nhúng")

    model = _load_model()
    vecs = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,  # chuẩn hoá → tích vô hướng = cosine
        show_progress_bar=True,
    ).astype(np.float32)

    # IndexFlatIP: vét cạn, chính xác tuyệt đối. Ở quy mô 142k vector thì tra
    # cứu vẫn dưới mili-giây, nên không cần IVF/HNSW — thêm cấu trúc xấp xỉ chỉ
    # thêm tham số phải tinh chỉnh mà không được gì.
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(EMBED_DIM))
    index.add_with_ids(vecs, np.asarray(ids, dtype=np.int64))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    faiss.write_index(index, str(tmp))
    tmp.replace(out)

    meta = IndexMeta(
        schema_version=SCHEMA_VERSION,
        artifact_sha256=_artifact_sha(db),
        model=MODEL_NAME,
        revision=MODEL_REVISION,
        dim=EMBED_DIM,
        n_vectors=len(ids),
    )
    meta_path(out).write_text(meta.to_json(), encoding="utf-8")
    return meta


def load_index(index_path: Path | None = None, *, db: Path | None = None):
    """Nạp index và TỪ CHỐI nếu nó lệch với artifact .sqlite hiện tại."""
    import faiss

    index_path = index_path or config.KB_FAISS
    mp = meta_path(index_path)
    if not index_path.is_file() or not mp.is_file():
        raise FileNotFoundError(f"Chưa có dense index: {index_path}\nChạy `smk kb dense` để dựng.")
    meta = IndexMeta.from_json(mp.read_text(encoding="utf-8"))

    if meta.schema_version != SCHEMA_VERSION:
        raise IndexOutOfSync(
            f"index dựng cho schema {meta.schema_version}, code cần {SCHEMA_VERSION}"
        )
    current = _artifact_sha(db or config.KB_SQLITE)
    if current and meta.artifact_sha256 and meta.artifact_sha256 != current:
        raise IndexOutOfSync(
            "FAISS index dựng từ một artifact .sqlite KHÁC.\n"
            f"  index  : {meta.artifact_sha256[:16]}…\n"
            f"  hiện có: {current[:16]}…\n"
            "concept_id có thể đã đổi — mọi kết quả dense sẽ trỏ nhầm concept. "
            "Chạy lại `smk kb dense`."
        )
    return faiss.read_index(str(index_path)), meta


_MODEL_CACHE: dict[str, object] = {}


def embed_query(text: str):
    """Nhúng một truy vấn. Model được cache trong tiến trình."""
    import numpy as np

    if "m" not in _MODEL_CACHE:
        _MODEL_CACHE["m"] = _load_model()
    vec = _MODEL_CACHE["m"].encode([text], convert_to_numpy=True, normalize_embeddings=True)
    return vec.astype(np.float32)
