-- ═══════════════════════════════════════════════════════════════════════════
--  Knowledge Base schema — NGUỒN SỰ THẬT DUY NHẤT về cấu trúc store.
--  Không rải CREATE TABLE ở bất kỳ chỗ nào khác trong code.
--
--  Thiết kế theo mô hình UMLS: concepts (neo) + terms (atom) + relations (cạnh),
--  cộng attributes (EAV) và sources (provenance).
--  Chi tiết & lý do: docs/kb-pipeline-plan.md §4, §5
-- ═══════════════════════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────
-- schema_meta — phiên bản schema, để phát hiện artifact lệch code
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────
-- sources — provenance ở mức FILE GỐC (không phải bộ mã).
--   ví dụ: icd10_pdf_who, icd10_csv_byt, rxnorm_rrf, snomed_int
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE sources (
    source       TEXT PRIMARY KEY,
    release      TEXT,
    origin_file  TEXT,
    sha256       TEXT,
    n_rows       INTEGER,
    ingested_at  TEXT
);

-- ─────────────────────────────────────────────────────────────────────────
-- concepts — 1 dòng / mã. Neo của toàn hệ thống.
--
--   concepts.vocab  = BỘ MÃ   ('icd10' | 'rxnorm' | 'snomed')
--   terms.source    = FILE GỐC (FK → sources)
--
--   Phân biệt này cần thiết vì một concept ICD gộp term từ HAI file
--   (icd-10-vn.pdf + ICD10.csv), nên provenance phải nằm ở mức term.
--
--   concept_id là INTEGER surrogate — KHOÁ JOIN VỚI FAISS.
--   Gán TẤT ĐỊNH bằng sort (vocab, code); xem load/ids.py.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE concepts (
    concept_id   INTEGER PRIMARY KEY,
    vocab        TEXT    NOT NULL,
    code         TEXT    NOT NULL,
    entity_kind  TEXT    NOT NULL,
    pref_vi      TEXT,
    pref_en      TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    UNIQUE (vocab, code)
);

CREATE INDEX idx_concepts_code ON concepts (code);
CREATE INDEX idx_concepts_kind ON concepts (vocab, entity_kind);

-- ─────────────────────────────────────────────────────────────────────────
-- terms — bảng "atom". MỌI retrieval từ vựng đánh vào đây.
--
--   norm_term  : NFC + lowercase + chuẩn đơn vị — GIỮ dấu tiếng Việt
--   ascii_term : như trên nhưng BỎ dấu — tăng recall, giảm precision
--   Có cả hai để retrieve rộng bằng ascii rồi rerank bằng norm.
--
--   tier       : authoritative | derived | generated  (xem §4.1)
--   evidence   : JSON, BẮT BUỘC với tier='derived'
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE terms (
    term_id       INTEGER PRIMARY KEY,
    concept_id    INTEGER NOT NULL REFERENCES concepts (concept_id),
    -- `vocab` lặp lại từ `concepts`. Denormalize CÓ CHỦ ĐÍCH: nhờ nó bộ lọc
    -- bộ mã đẩy được vào trong biểu thức MATCH của FTS5. Không có cột này,
    -- query planner chọn `concepts` làm vòng ngoài rồi SCAN terms_fts ở trong
    -- cùng — đo được 7,4 s cho MỘT truy vấn (xem docs §10, Phase 2).
    vocab         TEXT    NOT NULL,
    source        TEXT    NOT NULL REFERENCES sources (source),
    term          TEXT    NOT NULL,
    norm_term     TEXT    NOT NULL,
    ascii_term    TEXT    NOT NULL,
    lang          TEXT    NOT NULL CHECK (lang IN ('vi', 'en')),
    term_type     TEXT    NOT NULL,
    is_preferred  INTEGER NOT NULL DEFAULT 0,
    tier          TEXT    NOT NULL DEFAULT 'authoritative'
                          CHECK (tier IN ('authoritative', 'derived', 'generated')),
    evidence      TEXT,
    CHECK (tier <> 'derived' OR evidence IS NOT NULL)
);

CREATE INDEX idx_terms_concept ON terms (concept_id);
CREATE INDEX idx_terms_norm    ON terms (norm_term);
CREATE INDEX idx_terms_tty     ON terms (term_type);
CREATE INDEX idx_terms_tier    ON terms (tier);
CREATE INDEX idx_terms_vocab   ON terms (vocab);

-- BM25 miễn phí. External-content table: nội dung nằm ở `terms`, FTS chỉ giữ index.
CREATE VIRTUAL TABLE terms_fts USING fts5 (
    vocab,
    norm_term,
    ascii_term,
    content      = 'terms',
    content_rowid = 'term_id',
    tokenize     = 'unicode61'
);

-- ─────────────────────────────────────────────────────────────────────────
-- relations — triple thống nhất. Nuốt được mọi loại cạnh:
--   RxNorm has_ingredient · SNOMED isa · SNOMED→ICD maps_to
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE relations (
    src_concept  INTEGER NOT NULL REFERENCES concepts (concept_id),
    rel          TEXT    NOT NULL,
    dst_concept  INTEGER NOT NULL REFERENCES concepts (concept_id),
    rel_group    INTEGER,
    priority     INTEGER,
    tier         TEXT    NOT NULL DEFAULT 'authoritative'
                         CHECK (tier IN ('authoritative', 'derived', 'generated')),
    meta         TEXT
);

CREATE INDEX idx_rel_src ON relations (src_concept, rel);
CREATE INDEX idx_rel_dst ON relations (dst_concept, rel);

-- ─────────────────────────────────────────────────────────────────────────
-- attributes — EAV. Hấp thụ mọi thay đổi CỘNG THÊM mà không cần DDL.
--   ICD: dagger/asterisk, chapter, block, sex_only, who_guidance
--   RxNorm: ATC_LEVEL, FDA_UNII_CODE
--   SNOMED: semantic_tag  (Phase 3 / H2)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE attributes (
    concept_id  INTEGER NOT NULL REFERENCES concepts (concept_id),
    attr        TEXT    NOT NULL,
    value       TEXT
);

CREATE INDEX idx_attr ON attributes (concept_id, attr);

-- ─────────────────────────────────────────────────────────────────────────
-- closure — bao đóng truyền ứng của quan hệ IS-A.  (điền ở Phase 3 / H1)
--
--   Định nghĩa từ Phase 0 chứ không đợi Phase 3, để giữ nguyên tắc
--   "schema ở một chỗ" và tránh phải migrate giữa chừng.
--   Bảng rỗng cho tới khi enrich/closure.py chạy.
--
--   ~7,6 triệu dòng khi đầy (SNOMED: 383.853 concept, 638.927 cạnh IS-A).
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE closure (
    ancestor    INTEGER NOT NULL REFERENCES concepts (concept_id),
    descendant  INTEGER NOT NULL REFERENCES concepts (concept_id),
    min_dist    INTEGER NOT NULL,
    CHECK (ancestor <> descendant)
);

CREATE INDEX idx_clo_desc ON closure (descendant, ancestor);
CREATE INDEX idx_clo_anc  ON closure (ancestor, descendant);
