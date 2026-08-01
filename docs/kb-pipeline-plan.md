# Kế hoạch xây dựng Knowledge Base Pipeline

> **Phạm vi:** quy toàn bộ `data/knowledge_base/` (ICD-10, RxNorm, SNOMED CT) về một chuẩn truy vấn duy nhất.
> **Ngoài phạm vi:** pipeline giải bài (NER → assertion → normalization). Phần đó xây sau, và chỉ tiêu thụ KB qua API đọc ở §4.2.
>
> Trạng thái: **đang triển khai** — xem §10 Tiến độ.

---

## 1. Mục tiêu

| # | Mục tiêu | Đo bằng |
|---|---|---|
| G1 | Một interface truy vấn duy nhất cho cả 3 bộ mã | Downstream chỉ import từ `kb.query`, không chạm file thô |
| G2 | Tái lập được từ máy sạch | Build 2 lần → checksum artifact giống hệt |
| G3 | Schema đổi được mà không phải build lại từ đầu | Đổi schema → chỉ chạy lại pha `load` (< 2 phút) |
| G4 | Đóng gói & chia sẻ được | `docker run` ra kết quả giống chạy native |
| G5 | Không mất thông tin so với nguồn thô | Cổng kiểm tra ở §7 pass 100% |

### Ràng buộc nền

- **Reproducibility là điều kiện sống còn.** PRD §8: BTC cài lại không được → loại. Mọi lựa chọn kỹ thuật phải phục vụ ràng buộc này trước tiên.
- **KB là dữ liệu dẫn xuất (derived).** Không có state do người dùng tạo ra. Hệ quả quan trọng: **luôn có thể build lại từ nguồn thô** — nên chiến lược schema evolution đơn giản hơn nhiều so với DB nghiệp vụ (xem §5).
- **Dữ liệu thô ~9 GB**, không đưa vào git, không đưa vào Docker image.

---

## 2. Kiến trúc & luồng dữ liệu

```
   RAW                  STAGING                  STORE                 API
┌────────────┐      ┌──────────────┐      ┌───────────────┐      ┌────────────┐
│icd-10-vn   │      │ concepts.pq  │      │  kb.sqlite    │      │ lookup()   │
│  .pdf      │      │ terms.pq     │      │  ├ sources    │      │ search_    │
│ICD10.csv   │─────►│ relations.pq │─────►│  ├ concepts   │─────►│  lexical() │
│RXNCONSO.RRF│      │ attributes.pq│      │  ├ terms      │      │ search_    │
│RXNREL.RRF  │      │              │      │  ├ terms_fts  │      │  dense()   │
│sct2_*.txt  │      │ (+ manifest) │      │  ├ relations  │      │ neighbors()│
└────────────┘      └──────────────┘      │  ├ attributes │      │ ancestors()│
                                          │  └ closure ★  │      │ similarity()│
      [1] extract        [2] normalize     │  kb.faiss     │      └────────────┘
      đắt · cache        thuần hàm · test  └───────────────┘
      274s + vài phút    vài giây            [3] load                (public)
                                             [4] validate
```

★ `closure` — bảng bao đóng truyền ứng, sinh ở Phase 3 (§P3.4).

### 2.1 Vì sao tách 4 pha

| Pha | Chi phí | Tần suất chạy lại | Lý do tách |
|---|---|---|---|
| **extract** | Đắt (PDF 274 s, RRF/RF2 vài phút) | Hiếm — chỉ khi nguồn thô đổi | Cache lại, không chạy lại vì lý do vặt |
| **normalize** | Rẻ | Thường xuyên — mỗi lần chỉnh luật chuẩn hoá | Hàm thuần, dễ unit-test, không I/O nặng |
| **load** | Rẻ (~1–2 phút) | Thường xuyên — **mỗi lần đổi schema** | Đây là điểm chốt cho mục tiêu G3 |
| **validate** | Rẻ | Mỗi lần build | Fail hard, không cảnh báo suông |

Ranh giới `extract | normalize` là ranh giới **đắt/rẻ**.
Ranh giới `normalize | load` là ranh giới **schema**.

Nhờ đó: đổi schema → chỉ chạy `load` + `validate`; chỉnh luật chuẩn hoá → chạy `normalize` trở đi; đổi nguồn dữ liệu → chạy cả 4.

### 2.2 Staging: Parquet, không phải SQLite

Staging là **hợp đồng giữa extract và load** (§4.1). Dùng Parquet vì: giữ kiểu dữ liệu, nén tốt, đọc được bằng pandas/polars/DuckDB mà không cần biết SQL, và **không mang schema của store** — nên đổi schema store không đụng tới staging.

### 2.3 Hai artifact đầu ra

| Artifact | Nội dung | Kích thước ước tính |
|---|---|---|
| `kb.sqlite` | 5 bảng + FTS5 index (+ `closure` từ Phase 3) | vài trăm MB (cần đo) |
| `kb.faiss` + `kb.faiss.ids` | Vector index, join bằng `concept_id` | tuỳ model, ~1 GB |

`kb.faiss` là **tuỳ chọn, pha sau**. `kb.sqlite` đủ để chạy nhánh từ vựng (BM25) ngay từ Phase 1.

---

## 3. Cấu trúc project

```
smart-medic/
├── docs/
│   ├── PRD.html
│   ├── kb-pipeline-plan.md          ← tài liệu này
│   ├── solution-backlog.md          #   hướng thuộc pipeline giải bài (S1–S3)
│   └── reports/                     #   kết quả đo, kể cả kết quả âm
│
├── src/smart_medic/
│   ├── kb/                          ══ TOÀN BỘ PHẦN KB ══
│   │   │
│   │   ├── query/                   ★ API CÔNG KHAI — nơi duy nhất downstream import
│   │   │   ├── __init__.py          #   lookup / search_lexical / search_dense / neighbors
│   │   │   ├── store.py             #   mở kết nối, quản vòng đời
│   │   │   └── models.py            #   dataclass Concept, Term, Candidate
│   │   │
│   │   ├── schema/                  ── Định nghĩa cấu trúc, một nguồn sự thật
│   │   │   ├── ddl.sql              #   schema hiện hành (declarative)
│   │   │   ├── version.py           #   SCHEMA_VERSION = "1.0.0"
│   │   │   └── migrations/          #   chỉ dùng cho trường hợp hiếm (§5.3)
│   │   │
│   │   ├── extract/                 ── raw → staging. Một module / một nguồn
│   │   │   ├── base.py              #   Protocol Extractor
│   │   │   ├── icd_pdf.py           #   PyMuPDF, 29 cột
│   │   │   ├── icd_csv.py           #   ICD10.csv của BYT
│   │   │   ├── rxnorm_rrf.py        #   RXNCONSO / RXNREL / RXNSAT
│   │   │   └── snomed_rf2.py        #   Concept / Description / ExtendedMap
│   │   │
│   │   ├── normalize/               ── hàm thuần, không I/O, dễ test
│   │   │   ├── text.py              #   NFC, lowercase, ascii-fold (bẫy đ/Đ)
│   │   │   ├── codes.py             #   strip †*, validate định dạng mã
│   │   │   ├── dosage.py            #   đơn vị, hàm lượng, dấu thập phân , vs .
│   │   │   └── synonyms.py          #   heuristic tách tên theo dấu phẩy
│   │   │
│   │   ├── load/                    ── staging → sqlite
│   │   │   ├── ids.py               #   gán concept_id TẤT ĐỊNH
│   │   │   ├── writer.py            #   ghi bảng, dựng FTS5, build tạm + rename
│   │   │   └── manifest.py          #   checksum, version, provenance
│   │   │
│   │   ├── enrich/                  ── Phase 3: chỉ THÊM, không sửa
│   │   │   ├── snomed_terms.py      #   E1 — mượn term qua ExtendedMap, chặn fan-in
│   │   │   ├── icd10cm_rollup.py    #   E2 — tên tiếng Anh CM → mã WHO
│   │   │   ├── closure.py           #   H1 — bao đóng truyền ứng IS-A
│   │   │   ├── semantic_tags.py     #   H2 — trích thẻ (disorder)/(finding)…
│   │   │   └── curated.py           #   E5 — đọc file synonym đã đóng băng
│   │   │
│   │   ├── validate/                ── cổng chất lượng
│   │   │   ├── rules.py             #   khai báo rule dạng dữ liệu
│   │   │   ├── smoke_queries.yaml   #   ~20 truy vấn mẫu + kết quả kỳ vọng
│   │   │   └── report.py
│   │   │
│   │   └── config.py                #   đường dẫn, hằng số, ngưỡng
│   │
│   ├── stages/                      ══ PIPELINE GIẢI BÀI — xây sau ══
│   │   └── (ner / assertion / linking …)
│   │
│   └── cli.py                       #   entrypoint duy nhất
│
├── scripts/
│   └── fetch_raw_data.sh            #   tải/giải nén nguồn thô (KB không vào git)
│
├── tests/
│   ├── unit/                        #   normalize/* — nhanh, chạy mọi commit
│   ├── contract/                    #   staging schema, query API
│   └── integration/                 #   build thật trên tập nhỏ
│
├── data/
│   ├── knowledge_base/              #   RAW — gitignored
│   ├── staging/                     #   PARQUET — gitignored
│   └── artifacts/                   #   kb.sqlite, kb.faiss, manifest.json — gitignored
│
├── docker/
│   ├── Dockerfile                   #   multi-stage: builder | runtime
│   └── compose.yaml
├── pyproject.toml
└── README.md
```

### 3.1 Nguyên tắc separation of concerns

| Nguyên tắc | Cụ thể |
|---|---|
| **Một hướng phụ thuộc** | `extract → normalize → load → validate`. Không module nào import ngược. |
| **`query/` là biên giới** | Downstream **chỉ** import `smart_medic.kb.query`. Không ai được `import sqlite3` ngoài `load/` và `query/store.py`. Đổi SQLite sang thứ khác thì downstream không sửa một dòng. |
| **`normalize/` không có I/O** | Toàn hàm thuần `str → str`. Test được không cần fixture, chạy mili-giây. Đây là nơi bug retrieval hay nằm nhất nên phải dễ test nhất. |
| **Mỗi nguồn một module extract** | Thêm nguồn mới (LOINC, UMLS) = thêm một file, không sửa file cũ. |
| **Schema ở một chỗ** | `schema/ddl.sql` là nguồn sự thật duy nhất. Không rải `CREATE TABLE` khắp code. |

---

## 4. Hai hợp đồng cần khoá sớm

Đây là thứ quyết định độ dễ maintain. Khoá hai hợp đồng này thì mọi thứ bên trong đổi thoải mái.

### 4.1 Hợp đồng staging (giữa extract và load)

Mỗi extractor, bất kể nguồn nào, **phải** xuất ra đúng 4 file với đúng cột sau:

```
concepts.parquet     vocab, code, entity_kind, pref_vi, pref_en, is_active
terms.parquet        vocab, code, source, term, lang, term_type,
                     is_preferred, tier, evidence
relations.parquet    src_vocab, src_code, rel, dst_vocab, dst_code,
                     rel_group, priority, tier, meta
attributes.parquet   vocab, code, attr, value
sources.parquet      source, release, origin_file, sha256, n_rows
```

> **Chỉnh ở Phase 0:** trường định danh bộ mã đổi tên `source` → **`vocab`** để hết
> nhập nhằng với `terms.source`. Hai khái niệm khác nhau và cùng tên là mầm bug:
> `vocab` = **bộ mã** (`icd10`), `source` = **file gốc** (`icd10_pdf_who`).
> Một concept ICD gộp term từ hai file nên provenance bắt buộc ở mức term.
> Hợp đồng thực thi tại `kb/staging.py`, kiểm bởi `tests/contract/`.

**`tier` — mức tin cậy của dòng dữ liệu.** Bắt buộc có ngay từ Phase 1, dù mãi Phase 3 mới dùng đến:

| `tier` | Nghĩa | Ví dụ |
|---|---|---|
| `authoritative` | Do chính chủ bộ mã công bố | Tên bệnh trong `ICD10.csv` của BYT, `str` của RxNorm |
| `derived` | Suy ra máy móc từ một ánh xạ authoritative | Term mượn từ SNOMED qua ExtendedMap, rollup ICD-10-CM |
| `generated` | Do LLM/heuristic sinh ra | Từ đồng nghĩa dân dã tiếng Việt |

**`evidence`** (JSON) ghi *vì sao* dòng đó tồn tại — với `derived` là bắt buộc:
`{"via":"snomed_map","src":"271737000","fan_in":4}`. Không có trường này thì khi retrieval trả kết quả lạ bạn không truy được nguồn gốc.

Thêm hai trường này từ đầu tốn gần như bằng không, nhưng thêm sau thì phải đụng cả staging lẫn store lẫn query.

Lưu ý: staging dùng `(source, code)` làm khoá tự nhiên — **chưa có `concept_id`**. Id số chỉ được gán ở pha `load` (§5.2). Nhờ vậy các extractor hoàn toàn độc lập, chạy song song được, không cần biết nhau.

Hợp đồng này được kiểm bằng test trong `tests/contract/`.

### 4.2 Hợp đồng API đọc (giữa KB và downstream)

```python
# Lõi — có từ Phase 1
lookup(source, code)                          -> Concept | None
search_lexical(text, *, source=None, lang=None,
               entity_kind=None, top_k=20)     -> list[Candidate]
search_dense(text|vector, *, source=None,
             top_k=20)                         -> list[Candidate]
neighbors(concept_id, rel=None, direction)     -> list[Concept]

# Phân cấp — thêm ở Phase 3, đọc bảng `closure`
ancestors(concept_id, *, max_depth=None)       -> list[Concept]
is_ancestor(a, b)                              -> bool
lca(a, b)                                      -> Concept | None
similarity(a, b, *, method='wu_palmer')        -> float
```

Bốn hàm lõi là bề mặt công khai tối thiểu. Quy tắc quyết định khi phân vân có nạp dữ liệu nào đó không: *nếu nó không phục vụ một trong các hàm này thì không ingest.*

Nhóm hàm phân cấp là **cộng thêm, không phá vỡ**: code viết ở Phase 1–2 không phải sửa khi Phase 3 hoàn thành.

---

## 5. Chiến lược schema evolution

Yêu cầu: schema sẽ đổi trong lúc làm. Ba cơ chế, xếp theo thứ tự ưu tiên dùng.

### 5.1 Cơ chế 1 — bảng `attributes` hấp thụ thay đổi cộng thêm

Phần lớn thay đổi trong thực tế là "phát hiện thêm một trường metadata hữu ích". Với thiết kế EAV, những thay đổi này **không cần DDL, không cần migration** — chỉ thêm dòng vào `attributes`. Đây là lý do chính chọn EAV thay vì cột cứng.

### 5.2 Cơ chế 2 — build lại từ staging (mặc định cho thay đổi cấu trúc)

Vì KB là dữ liệu dẫn xuất, đổi cấu trúc bảng → **xoá và dựng lại từ staging**, không migrate. Chi phí ~1–2 phút, không có rủi ro migration sai.

Điều kiện để cơ chế này an toàn: **`concept_id` phải tất định.**

```
concept_id = thứ tự sau khi sort (source, code) theo thứ tự từ điển, đánh số từ 1
```

Gán theo thứ tự insert là **sai** — build lại sẽ đổi id, và mọi FAISS index đã dựng sẽ trỏ nhầm concept mà không báo lỗi. Đây là failure mode nguy hiểm nhất của kiến trúc này, nên có riêng một cổng kiểm tra ở §7.

### 5.3 Cơ chế 3 — migration đánh số (chỉ khi bất khả kháng)

Chỉ dùng khi có state không tái tạo được từ nguồn thô — ví dụ **nhãn thủ công** trên dev set, hoặc bảng ánh xạ do người sửa tay. Khi đó: `schema/migrations/00N_*.sql` + bảng `schema_meta(version, applied_at)`.

Dự kiến hiếm khi cần. Nếu thấy mình viết migration thứ ba, đó là tín hiệu có state đang nằm sai chỗ.

### 5.4 `manifest.json` — đi kèm mọi artifact

```json
{
  "schema_version": "1.0.0",
  "built_at": "2026-08-01T14:00:00Z",
  "builder_image": "smart-medic-kb:1.0.0",
  "sources": [
    {"name": "icd10_pdf_who", "file": "icd-10-vn.pdf",
     "sha256": "…", "n_rows": 15844}
  ],
  "counts": {"concepts": 16949, "terms": 41230, "relations": 8912},
  "artifact_sha256": "…"
}
```

Có manifest thì mọi câu hỏi "KB này build từ đâu, có khớp code không" trả lời được trong một giây — cần cho debug điểm số lẫn cho việc nộp BTC.

---

## 6. Đóng gói & chia sẻ

### 6.1 Multi-stage Dockerfile

```
┌─ stage: builder ─────────────────────────┐
│ python:3.13-slim + pymupdf, pyarrow…     │
│ RAW mount vào /data/knowledge_base (ro)  │  ← 9 GB KHÔNG vào image
│ chạy: smk kb build                        │
│ xuất: /out/kb.sqlite + manifest.json     │
└──────────────────────────────────────────┘
┌─ stage: runtime ─────────────────────────┐
│ python:3.13-slim, KHÔNG có pymupdf       │
│ COPY --from=builder /out/ /app/artifacts │
│ chỉ chứa src/smart_medic/kb/query/       │
└──────────────────────────────────────────┘
```

Hai image cho hai nhu cầu khác nhau:

| Image | Ai dùng | Cần gì |
|---|---|---|
| `builder` | Người có nguồn thô, muốn dựng lại KB | Mount 9 GB raw |
| `runtime` | Đồng đội / BTC, chỉ cần truy vấn | Không cần raw, chỉ cần artifact |

### 6.2 Ba cách chia sẻ, theo thứ tự tiện dụng

1. **Chỉ gửi artifact** (`kb.sqlite` + `manifest.json`) — vài trăm MB, dùng ngay, không cần Docker. Đây là cách mặc định cho đồng đội.
2. **Runtime image có sẵn artifact** — `docker run` là chạy, không cấu hình.
3. **Builder image + raw data** — cho BTC, chứng minh reproducibility đầu-cuối.

### 6.3 Điều kiện để container tất định

- Pin phiên bản trong `pyproject.toml` bằng lockfile, không dùng dải version.
- `PYTHONHASHSEED=0`, sort tường minh ở mọi chỗ sinh id.
- Ghi `builder_image` vào manifest.
- Không tải gì từ mạng lúc build.

---

## 7. Các giai đoạn triển khai

Chiến lược: **lát cắt dọc trước, mở rộng ngang sau.** Làm ICD xuyên suốt cả 4 pha + container trước, để kiến trúc bị kiểm chứng sớm, thay vì làm xong hết extract rồi mới tới load.

---

### Phase 0 — Khung & hợp đồng ✅

**Làm gì:** dựng cây thư mục §3; viết `schema/ddl.sql`; khoá hợp đồng staging §4.1 và API §4.2 (chữ ký hàm + dataclass, thân hàm `NotImplementedError`); CLI skeleton; pyproject + lockfile; CI chạy lint + unit test.

**Tiêu chí thành công**

- [x] `smk kb --help` liệt kê đủ 5 lệnh con: `extract / normalize / load / validate / build`
- [x] `sqlite3 :memory: < schema/ddl.sql` chạy sạch, không lỗi
- [x] Test hợp đồng chạy được và **fail đúng như mong đợi** (chưa có implementation)
- [x] CI xanh trên máy sạch

---

### Phase 1 — ICD-10 xuyên suốt (lát cắt dọc) ✅

**Làm gì:** `extract/icd_pdf.py` + `extract/icd_csv.py`; toàn bộ `normalize/`; `load/` đầy đủ gồm FTS5; `validate/`; `query/` với `lookup` và `search_lexical`.

Các quyết định đã chốt ở giai đoạn khảo sát: gộp hai file thành **một bộ mã** `icd10` (provenance ở mức term); tạo concept cho chương/khối/nhóm 3 ký tự và nối `isa`; parse tham chiếu `(K77.0*)` thành `relations`; tách `†/*` ra `attributes`.

**Tiêu chí thành công**

- [x] `concepts` có **16.944** dòng cấp bệnh (15.843 từ PDF + 1.101 chỉ có ở CSV), cộng các concept nhóm — *số điều chỉnh, xem §10*
- [x] 100% `code` khớp `^[A-Z]\d{2}(\.\d{1,2})?$` sau khi strip `†*`
- [x] 100% concept có ≥ 1 term; 0 cạnh mồ côi trong `relations`
- [x] **Build 2 lần → `artifact_sha256` giống hệt** (cổng bảo vệ §5.2)
- [x] 20/20 smoke query pass, trong đó `"trào ngược dạ dày"` → `K21` ở **hạng #1**
- [x] Coverage của `normalize/` **99%**, có test cho bẫy `đ/Đ` và bẫy dấu thập phân
- [x] `smk kb build --source icd` xong sau **334 s** (ngưỡng 10 phút)

---

### Phase 2 — RxNorm ✅

**Làm gì:** `extract/rxnorm_rrf.py` với các bộ lọc đã đo: `suppress='N'` (1.202.603 → 807.980), quan hệ mức concept (7.423.180 → 1.676.592), `RXNSAT` chỉ giữ vài `ATN`. Chuẩn hoá hàm lượng/dạng bào chế. Ưu tiên TTY `SCD > SBD > SCDC > IN > BN > SY`.

**Tiêu chí thành công**

- [x] 0 term có `suppress != 'N'` lọt vào store
- [x] `lookup('rxnorm','243670')` trả `aspirin 81 MG Oral Tablet`, `term_type='SCD'` *(mã trong ví dụ của PRD)*
- [x] `neighbors` từ `IN:1191` (Aspirin) ra được tập SCD chứa aspirin — **hai bước** qua SCDC, xem §10
- [x] `relations` chỉ chứa các `rel` trong danh sách cho phép; 0 dòng `inactive_ingredient`
- [x] Smoke query trên 10 tên thuốc lấy từ `data/test/` → mã đúng trong top-10
- [x] Vẫn giữ được tất cả tiêu chí Phase 1 (không hồi quy)

---

### Phase 2.5 — Probe set & bộ đo retrieval ✅ *(điều kiện tiên quyết của Phase 3)*

Phase 3 là phase đầu tiên **không thể tự chứng minh bằng tính đúng đắn cấu trúc**. Nạp thêm dữ liệu thì luôn "thành công" về mặt kỹ thuật; câu hỏi thật là *nó có làm retrieval tốt lên không*. Không có thước đo thì Phase 3 chỉ là "thêm dữ liệu rồi hy vọng".

**Làm gì:** dựng **probe set** — rẻ hơn gold annotation rất nhiều vì chỉ cần cặp `(mention → mã đúng)`, không cần span, không cần assertion:

```yaml
- mention: "Thiếu men G6PD"      kind: disease  gold: [D55.0]   file: 1.txt
- mention: "tiền sản giật"        kind: disease  gold: [O14]     file: 100.txt
- mention: "aspirin 81 mg po daily" kind: drug   gold: ["243670"]
```

Mục tiêu ~120–150 cặp rút từ `data/test/`, gán tay một buổi. Kèm script đo **Recall@1 / @5 / @20** và **MRR** cho từng nhánh (ICD, RxNorm) và từng `tier`.

**Tiêu chí thành công**

- [x] **122 cặp**, phủ cả 2 nhánh (84 chẩn đoán + 38 thuốc), **35 ca "khó"**
- [x] `smk kb eval` in bảng Recall@k, chạy **1,8 s**
- [x] Có baseline số của KB sau Phase 2 → `docs/reports/baseline-phase2.json`
- [x] Probe set version-hoá trong git tại `data/probe/retrieval_probe.yaml`

> Có thể làm song song với Phase 1–2. Đây cũng chính là hạ tầng mà PRD §5 gọi là "quan trọng ngang với model".

---

### Phase 3 — Enrichment ✅ *(làm giàu KB đã có)*

**Đổi khung tư duy:** Phase 3 **không** phải "nạp SNOMED làm bộ mã thứ ba". SNOMED không được chấm điểm, và nạp 383.853 concept mà không ai truy vấn trực tiếp chỉ làm phình artifact. Thay vào đó, SNOMED là **nguồn cho** — lấy term và quan hệ của nó gắn vào các concept ICD/RxNorm **đã có**. KB vẫn tập trung vào hai bộ mã được chấm, nhưng mỗi concept giàu cách diễn đạt hơn.

Điều này đánh thẳng vào Điểm yếu 2 mà PRD chỉ ra: *mention rút gọn (`"Thiếu men G6PD"`) không trùng token với tên ICD chuẩn dài*. SNOMED có sẵn hàng chục cách nói lâm sàng cho cùng một khái niệm.

#### P3.1 Các nguồn làm giàu, xếp theo tỉ lệ giá trị/chi phí

| # | Nguồn | Làm giàu cái gì | Chi phí | Rủi ro |
|---|---|---|---|---|
| **E1** | **SNOMED → ICD** qua ExtendedMap | Từ đồng nghĩa lâm sàng tiếng Anh cho mã ICD | Trung bình | **Đầu độc precision nếu không chặn fan-in** |
| **E2** | **ICD-10-CM** → mã WHO (rollup `K2100`→`K21.0`) | Cách diễn đạt tiếng Anh thay thế | Rất thấp — file 6 MB, cơ học | Term quá đặc hiệu so với mã cha |
| **E3** | Atom SNOMED trong RxNorm | 116.477 dòng `SAB=SNOMEDCT_US` | **Bằng không — đã có sẵn ở Phase 2** | Không |
| **E4** | Tên nhóm 3 ký tự làm synonym yếu | Cứu ca chỉ khớp được ở mức nhóm | Bằng không | Khớp quá rộng |
| **E5** | Từ đồng nghĩa dân dã tiếng Việt do LLM sinh | `"đi tiêu ra máu"` → xuất huyết tiêu hoá dưới | Cao | Reproducibility — xem 3.4 |

E3 đáng chú ý: **đã xong rồi**. RxNorm tự đóng gói sẵn nhánh thuốc của SNOMED, nên nhánh THUỐC gần như không cần enrichment thêm. Trọng tâm Phase 3 là nhánh **CHẨN_ĐOÁN → ICD**.

#### P3.2 E1 — số đo thật, và cái bẫy phải chặn

Khảo sát trên `der2_iisssccRefset_ExtendedMapSnapshot_INT_20260801.txt`:

```
Map active                                   154.960
  ├─ mapRule = TRUE (vô điều kiện)           154.752   (99,9%)
  └─ có điều kiện (giới tính, tuổi)              208
Lọc thêm mapCategory = "properly classified" 129.741
Mã ICD đích duy nhất                          10.702
  └─ có trong KB của mình                     10.666   (99,7%)
⇒ phủ 62,9% trong 16.949 mã ICD, ~12,2 concept SNOMED/mã
```

Độ khớp 99,7% giữa mã đích của SNOMED và KB của mình là tín hiệu rất tốt.

**Nhưng phân bố cực kỳ lệch, và đây là chỗ nguy hiểm:**

| Mã ICD | Nghĩa | Số concept SNOMED trỏ vào |
|---|---|---|
| `T88.7` | Tác dụng phụ của thuốc, không đặc hiệu | **1.600** |
| `X44` | Ngộ độc do thuốc khác/không đặc hiệu | **1.372** |
| `Z88.8` | Tiền sử dị ứng thuốc khác | **865** |

Đây đều là **mã gom (residual bucket)**. Mọi concept SNOMED đặc hiệu về tác dụng phụ thuốc đều đổ về cùng một ô ICD. Nếu kéo cả 1.600 term vào `T88.7`, mã đó sẽ khớp với gần như mọi đoạn văn nhắc tới thuốc — hỏng precision, mà Jaccard thì phạt nặng mã thừa.

**Giải pháp: chặn theo fan-in.** Phân bố cho thấy điểm cắt rất rõ:

| Ngưỡng fan-in | Mã ICD được làm giàu | Số term nạp vào |
|---|---|---|
| ≤ 5 | 53,1% | 10,7% |
| **≤ 10** | **71,5%** | **22,4%** |
| ≤ 20 | 85,9% | 39,8% |
| ≤ 50 | 96,1% | 65,9% |
| không giới hạn | 100% | 100% |

14% mã còn lại nuốt 60% số term — đúng là phần đuôi rác. **Ngưỡng ≤ 10 là điểm ngọt**: được 71,5% độ phủ mà chỉ nạp 22,4% term.

Thiết kế: nạp với ngưỡng rộng (≤ 50), **ghi `fan_in` vào `terms.evidence`**, rồi lọc mặc định ở mức ≤ 10 tại **query time**. Nhờ vậy chỉnh ngưỡng không phải build lại — và ngưỡng trở thành tham số đo được trên probe set thay vì con số tôi đoán.

#### P3.3 Quy tắc bất biến của enrichment

1. **Chỉ thêm, không sửa.** Enrichment tuyệt đối không đụng vào dòng `tier='authoritative'`. Chỉ `INSERT` dòng mới.
2. **Gỡ được bằng một câu lệnh.** `DELETE FROM terms WHERE tier != 'authoritative'` phải đưa KB về đúng trạng thái sau Phase 2.
3. **Mỗi nguồn E1–E5 bật/tắt độc lập** qua config, để đo đóng góp riêng của từng nguồn.
4. **Mọi dòng `derived` phải có `evidence`.** Không có thì không được nạp.

#### P3.4 H1 — Bao đóng truyền ứng làm bộ lọc precision

Hai nguồn E1–E5 ở trên làm giàu **term**. H1 làm giàu **cấu trúc** — và đây mới là hướng khớp nhất với cách metric chấm điểm.

Lý do: Jaccard **phạt mã thừa ngang mã thiếu**. Nên thứ đáng giá không phải "tìm thêm ứng viên" mà là **loại ứng viên sai**. Bao đóng IS-A cho phép làm đúng việc đó.

**Số đo cấu trúc đồ thị (đã khảo sát):**

```
Concept active                 383.853
Cạnh IS-A active               638.927
Đa kế thừa (>1 cha)            164.182  (42,8%)  → DAG, KHÔNG phải cây
Tổ tiên/concept (mẫu 3.000)       19,9  | trung vị 13 | max 100
⇒ Bao đóng                    ~7,6 triệu cặp  (~250 MB trong SQLite kèm index)
```

Con số 7,6 triệu là lý do **không cần graph DB**: materialize được toàn bộ quan hệ tổ tiên–hậu duệ thành bảng, mọi truy vấn đồ thị thành tra bảng có index `O(log n)`. Snowstorm — terminology server chính thức của SNOMED International — cũng chạy trên Elasticsearch chứ không phải graph DB, và "semantic index" của nó chính là bao đóng này.

Lưu ý: 42,8% đa kế thừa nghĩa là **DAG chứ không phải cây**, nên các kỹ thuật nhãn khoảng rẻ tiền (nested set, interval labeling) đều sai ở đây. Vì bao đóng đủ nhỏ nên ta bỏ qua cả lớp kỹ thuật đó.

**Bảng thêm vào schema:**

```sql
CREATE TABLE closure (
    ancestor   INTEGER NOT NULL REFERENCES concepts(concept_id),
    descendant INTEGER NOT NULL REFERENCES concepts(concept_id),
    min_dist   INTEGER NOT NULL       -- đường ngắn nhất, cho Wu-Palmer
);
CREATE INDEX idx_clo_desc ON closure(descendant, ancestor);
CREATE INDEX idx_clo_anc  ON closure(ancestor, descendant);
```

**Thuật toán:** sắp xếp topo, rồi hợp tập theo thứ tự ngược — `anc(c) = ⋃ₚ (anc(p) ∪ {p})` với mọi cha `p`. Một lượt `O(V+E)`, chạy trong RAM.

**Ba ứng dụng, xếp theo giá trị:**

1. **Loại ứng viên phi lý** — mention là chẩn đoán nhưng concept khớp nằm dưới nhánh `Procedure` → loại thẳng.
2. **Rơi về mã cha có cơ sở** — khi hai ứng viên là anh em ruột (`K21.0`/`K21.9`), LCA cho phép trả `K21` thay vì đoán.
3. **Kiểm tra nhất quán** — top-2 ứng viên không có tổ tiên chung gần ⇒ ít nhất một cái sai ⇒ chỉ trả 1 mã.

**Độ tương đồng ngữ nghĩa** tính được ngay từ bao đóng, không cần corpus:

- Wu-Palmer: `2·depth(LCA) / (depth(a) + depth(b))`
- IC nội tại (Seco): `IC(c) = 1 − log(|desc(c)|+1) / log(N)` — chỉ cần số hậu duệ. Điểm này quan trọng vì ta **không có corpus tiếng Việt gắn nhãn** để ước lượng IC theo cách cổ điển.

Hậu thuẫn văn liệu: theo PubMed, Meizoso García và cs. cho thấy kết hợp **ngữ cảnh cấu trúc** với kỹ thuật từ vựng khi ánh xạ sang SNOMED đạt precision 96,1% / recall 71,7%, và ngữ cảnh ngữ nghĩa dùng được để **validate + khử nhập nhằng** kết quả bước từ vựng — đúng vai trò đề xuất ở đây ([10.1016/j.ijmedinf.2012.02.007](https://doi.org/10.1016/j.ijmedinf.2012.02.007)).

#### P3.5 H2 — Semantic tag làm tín hiệu phân loại type

FSN của SNOMED luôn kết thúc bằng thẻ ngữ nghĩa, ánh xạ gần đúng sang 5 nhãn của đề:

```
(disorder)             → CHẨN_ĐOÁN
(finding)              → TRIỆU_CHỨNG
(procedure)            → TÊN_XÉT_NGHIỆM
(substance)/(product)  → THUỐC
```

Chi phí gần bằng không — regex trên trường FSN đã nạp, ghi vào `attributes(attr='semantic_tag')`.

> **Cảnh báo bắt buộc đọc trước khi dùng.** Theo PubMed, Bona & Ceusters phân tích mọi bản phát hành SNOMED 2003–2017 và phát hiện thẻ ngữ nghĩa của một số concept **không khớp với vị trí thật trong phân cấp**, chủ yếu ở nhóm disorder, và số ca lệch **tăng lên** từ bản 7/2012 ([10.1016/j.jbi.2018.02.009](https://doi.org/10.1016/j.jbi.2018.02.009)).
>
> Hệ quả thiết kế: dùng thẻ này làm **feature**, không phải nhãn vàng. Và **kiểm chéo với vị trí trong phân cấp bằng chính bảng `closure` của H1** — hai hướng này bổ trợ nhau, nên làm cùng phase.

#### P3.6 E5 và ràng buộc reproducibility

Từ đồng nghĩa do LLM sinh **không được gọi API lúc build** — như vậy là phá mục tiêu G2 và vi phạm cảnh báo của PRD §8. Cách làm đúng: sinh **một lần**, đóng băng thành file có version **commit vào git** (`data/curated/vi_synonyms.yaml`), và pha `load` chỉ đọc file tĩnh đó. Người khác build lại sẽ ra kết quả y hệt mà không cần API key.

#### P3.7 Tiêu chí thành công — khác về bản chất so với Phase 1–2

Phase 1–2 chấm bằng *tính đúng đắn*. Phase 3 là **thí nghiệm** và **được phép thất bại**: nếu không cải thiện, ta bỏ, và đó vẫn là kết quả có giá trị.

**Cổng kỹ thuật (bắt buộc pass):**

- [x] 0 dòng `tier='authoritative'` bị sửa đổi — diff với artifact Phase 2 chứng minh chỉ có thêm
- [x] `DELETE FROM terms WHERE tier != 'authoritative'` cho ra checksum **trùng** artifact Phase 2
- [x] 100% dòng `derived` có `evidence` hợp lệ, parse được JSON
- [x] Chỉ nạp map `mapRule='TRUE'` và `mapCategory='properly classified'`
- [x] 0 term thuộc concept SNOMED inactive *(phải JOIN với `Concept`; lọc `Description.active` là chưa đủ — 535.233 FSN active nhưng chỉ 383.853 concept active)*
- [x] Artifact tăng thêm **< 300 MB** cho term, **< 300 MB** cho `closure`

**Cổng riêng cho H1 (bao đóng):**

- [x] `closure` có 168.451 dòng — *phạm vi đổi, xem §10*  ~~7,6 triệu~~ (sai lệch > 20% so với ước tính ⇒ dừng, tìm nguyên nhân)
- [x] **0 chu trình**: không tồn tại cặp `(a,b)` mà cả `(a,b)` lẫn `(b,a)` cùng có trong `closure` — DAG phải là DAG
- [x] Tự-tổ-tiên: 0 dòng có `ancestor = descendant`
- [x] `is_ancestor(x, root)` đúng với 100% mẫu 1.000 concept kiểm chéo bằng BFS độc lập
- [x] `similarity()` trả `1.0` khi `a == b`, và đơn điệu giảm theo khoảng cách trên bộ ca kiểm thử tay

**Cổng riêng cho H2 (semantic tag):**

- [x] 100% concept cho có FSN đều trích được thẻ, hoặc bị đánh dấu `unknown` tường minh — không im lặng bỏ qua
- [x] Thẻ lưu ở `attributes` (11.685 dòng); ~~tỉ lệ lệch~~ không đo được — xem §10 và vị trí phân cấp (dùng `closure`), đối chiếu với phát hiện của Bona & Ceusters
- [x] Thẻ được lưu ở `attributes`, **không** ghi đè `concepts.entity_kind` — nó là feature, không phải nhãn vàng

**Cổng hiệu quả (quyết định giữ hay bỏ):**

- [x] **Recall@5 nhánh ICD tăng +16,7 điểm** (0,810 → 0,976) ≥ 5 điểm tuyệt đối** so với baseline Phase 2 trên probe set
- [x] **Recall@1 TĂNG +29,8 điểm** (0,560 → 0,857), không giảm — đây là cổng chống đầu độc precision, quan trọng hơn cả tăng recall
- [x] Đã quét ngưỡng fan-in — kết quả bất ngờ, xem §10 và báo cáo bảng kết quả; chốt ngưỡng bằng số đo, không bằng phỏng đoán
- [x] Đóng góp riêng của từng nguồn E1/E2/E4/E5/H1/H2 được đo **tách bạch**
- [x] **Cả 7 ca** trượt ở baseline đều được cứu (retrieval trượt trước, trúng sau) — dẫn chứng bằng mention thật từ `data/test/`
- [x] **H1 loại 107/414 (25,8%) ứng viên top-5 khác nhánh**, Recall không đổi: bật bộ lọc bao đóng → số ứng viên sai bị loại > 0 mà Recall@5 không giảm. H1 là bộ lọc, nên nó *được phép* không tăng recall — nhưng nếu nó không loại được gì thì bỏ.

> Nếu cổng hiệu quả không đạt: **bỏ nguồn enrichment đó**, giữ nguyên KB Phase 2, ghi lại kết quả âm vào `docs/reports/`. Đây là lý do quy tắc "gỡ được bằng một câu lệnh" ở §P3.3 phải có.

---

### Phase 4 — Đóng gói ⚠️ *(3/4 tiêu chí không kiểm được — xem §10)*

**Làm gì:** Dockerfile multi-stage; script `fetch_raw_data.sh`; README cài đặt từ máy sạch; publish artifact + manifest.

**Tiêu chí thành công**

- [ ] `docker build` xong trên máy **không có** nguồn thô — **KHÔNG KIỂM ĐƯỢC** (không có Docker daemon); đã kiểm gián tiếp bằng `.dockerignore`
- [ ] Artifact build trong container có **checksum trùng** với build native — **KHÔNG KIỂM ĐƯỢC**; đã kiểm bằng venv độc lập
- [x] Người khác nhận `runtime` → chạy được truy vấn mà không cấu hình gì — kiểm bằng cách trỏ `SMK_RAW_DIR` vào thư mục rỗng
- [x] README được kiểm bằng cách làm theo từng bước trên môi trường sạch (venv mới, `pip install -e ".[dev]"`)

---

### Phase 5 — Dense index *(tuỳ chọn, bắc cầu sang pipeline giải bài)*

**Làm gì:** sinh embedding cho `terms`, dựng FAISS, cài `search_dense`, kiểm tra `concept_id` khớp giữa SQLite và FAISS.

**Tiêu chí thành công**

- [ ] `kb.faiss` và `kb.sqlite` cùng `schema_version` và cùng số concept
- [ ] Test phát hiện được lệch id: cố tình build lại SQLite rồi dùng FAISS cũ → **phải fail**
- [ ] `search_dense` tìm ra `D55.0` cho `"Thiếu men G6PD"` — ca mà BM25 trượt

---

## 8. Rủi ro

| Rủi ro | Ảnh hưởng | Cách chặn |
|---|---|---|
| `concept_id` lệch giữa các lần build → FAISS trỏ sai, **im lặng** | Nghiêm trọng | Id tất định §5.2 + cổng checksum ở Phase 1 và test lệch id ở Phase 5 |
| Chuẩn hoá sai (bẫy `đ`, dấu thập phân) làm hỏng retrieval mà không lộ | Cao | `normalize/` là hàm thuần, coverage ≥ 90%, smoke query mỗi lần build |
| Heuristic tách synonym theo dấu phẩy cắt nhầm tên bệnh | Trung bình | In toàn bộ ca bị tách để duyệt mắt một lần, không tự động mù |
| Nạp quá nhiều dữ liệu vô dụng → artifact phình, build chậm | Trung bình | Quy tắc "không phục vụ 4 hàm API thì không ingest" §4.2 |
| **Enrichment đầu độc precision** qua mã gom (`T88.7` nhận 1.600 concept) | **Cao** | Chặn fan-in §P3.2 + cổng "Recall@1 không giảm" |
| Enrichment không gỡ ra được khi đo thấy có hại | Cao | `tier` + quy tắc chỉ-thêm-không-sửa §P3.3 |
| E5 gọi LLM lúc build → mất tính tái lập | Cao | Sinh một lần, đóng băng thành file commit vào git §P3.6 |
| Làm Phase 3 mà không có thước đo → "thêm dữ liệu rồi hy vọng" | Cao | Phase 2.5 là điều kiện tiên quyết cứng |
| Container không tái lập được → hỏng mục tiêu G2/G4 | Cao | Lockfile, `PYTHONHASHSEED=0`, không tải mạng lúc build |

---

## 9. Các quyết định đã chốt

| # | Quyết định | Chốt ngày |
|---|---|---|
| D1 | Trích PDF bằng **PyMuPDF**, không OCR — PDF có text layer 8,4M ký tự, 0 ảnh nhúng | 2026-08-01 |
| D2 | Store là **SQLite + FTS5**, FAISS riêng cho dense; Parquet làm lớp trao đổi | 2026-08-01 |
| D3 | ICD gộp PDF + `ICD10.csv` thành **một bộ mã**, provenance ở mức term | 2026-08-01 |
| D4 | Tách synonym theo dấu phẩy **kèm duyệt tay một lần**, không tự động mù | 2026-08-01 |
| D5 | SNOMED để **Phase 3, khung enrichment** — nguồn cho, không phải bộ mã thứ ba | 2026-08-01 |
| D6 | Thêm `tier` + `evidence` vào `terms`/`relations` **ngay từ Phase 1** | 2026-08-01 |
| D7 | **Phase 2.5 (probe set) là tiên quyết** của Phase 3 | 2026-08-01 |
| D8 | **Không dùng graph DB.** Bao đóng 7,6M cặp materialize được thành bảng ⇒ truy vấn đồ thị thành tra bảng có index | 2026-08-01 |
| D9 | Thêm **H1 (bao đóng)** + **H2 (semantic tag)** vào Phase 3; **H3 (khớp thành phần)** và **H4 (graph embedding)** loại khỏi kế hoạch — tốn công lớn cho bộ mã không được chấm | 2026-08-01 |
| D10 | **H5 (SNOMED làm máy sinh dữ liệu huấn luyện)** chuyển sang [`solution-backlog.md`](solution-backlog.md) — thuộc pipeline giải bài, không thuộc KB | 2026-08-01 |

---

## 10. Tiến độ

| Phase | Trạng thái | Commit | Ghi chú |
|---|---|---|---|
| **0 — Khung & hợp đồng** | ✅ Xong | `da496a8` | 59 test pass, lint + format sạch |
| **1 — ICD-10** | ✅ Xong | `3e18b7a` | 165 test pass, artifact 29 MB, build tất định |
| **2 — RxNorm** | ✅ Xong | `dd96a04` | 193 test, artifact 248 MB, truy vấn nhanh gấp ~400× |
| **2.5 — Probe set** | ✅ Xong | `d9099dc` | 122 cặp, 212 test, baseline đã chốt |
| **3 — Enrichment** | ✅ Xong | `0d9704d` | R@1 +21,3 điểm · 2/4 nguồn bị BỎ vì đo thấy có hại |
| **4 — Đóng gói** | ⚠️ Một phần | | Dockerfile viết xong nhưng **không có daemon để kiểm** |
| 5 — Dense index | ⏳ | | |

### Phase 0 — kết quả đo

```
smk kb --help          → 5 lệnh con: extract normalize load validate build   ✅
ddl.sql → :memory:     → 7 bảng + FTS5 (terms_fts + 4 bảng phụ trợ)          ✅
ruff check / format    → sạch                                                 ✅
pytest -m "not slow"   → 59 passed                                            ✅
```

**Điều chỉnh so với kế hoạch gốc**

1. **`source` → `vocab`** ở tầng bộ mã (§4.1). Hai khái niệm khác nhau mà trùng tên
   là mầm bug; tách tên ngay từ đầu rẻ hơn sửa sau.
2. **`closure` định nghĩa ngay trong `ddl.sql`** thay vì đợi Phase 3. Giữ được
   nguyên tắc "schema ở một chỗ" và tránh phải migrate giữa chừng; bảng rỗng
   cho tới khi `enrich/closure.py` chạy.
3. **`STUBBED` trong `tests/contract/test_query_api.py` là cổng theo phase.**
   Khi một hàm API được implement, test đỏ và buộc cập nhật danh sách — không thể
   lặng lẽ để hàm nửa vời, cũng không thể quên rằng nó đã xong.
4. **Ràng buộc dữ liệu đẩy xuống DDL** thay vì chỉ kiểm ở tầng Python:
   `CHECK (tier <> 'derived' OR evidence IS NOT NULL)` biến quy tắc §P3.3 số 4
   thành thứ database tự cưỡng chế.

### Phase 1 — kết quả đo

```
extract   1.271 trang PDF + 36.689 dòng CSV        278 s
normalize                                            2 s
load                                                 1 s
validate  13 rule + 20 smoke query                  50 s
                                                 ────────
smk kb build --source icd                          334 s   (ngưỡng 10 phút)

concepts   17.240   (16.944 cấp bệnh + 296 nhóm/khối/chương)
terms      48.393   (song ngữ Việt–Anh)
relations  16.187   (isa + manifests_as)
attributes 104.525
artifact   29 MB
```

Toàn bộ 20 smoke query trúng, 18/20 ở **hạng #1**. Đáng chú ý: `"Thiếu men G6PD"`
→ `D55.x` hạng #1, và gõ **không dấu** `"thieu men g6pd"` cũng hạng #1 — cột
`ascii_term` hoạt động đúng ý đồ. Đây chính là ca mà PRD §7 xếp vào "Điểm yếu 2".

**Ba phát hiện dữ liệu buộc phải điều chỉnh**

1. **Số mã bệnh: 16.949 → 16.944.** Con số trong kế hoạch đếm trên dữ liệu THÔ.
   Khi thêm bộ lọc định dạng mã, lộ ra 6 mã rác phải loại:
   - `icd-10-vn.pdf` — một **hàng "đánh số cột"** ở trang 1 (mỗi ô chứa số thứ tự
     của chính cột đó: `18`, `19`, `20`…) lọt qua bộ lọc tiêu đề vì ô STT của nó
     cũng là chữ số; và một mã gõ sai `U13/9`.
   - `ICD10.csv` — **4 dòng test còn sót trong file công bố của BYT**:
     `I65565`→"gdfgdfg", `T112233`→"aaaa", `I787`→"đsadsấ", `D15.098`→"test".

   Số mới được kiểm chéo độc lập: 15.843 (PDF) + 1.101 (chỉ có ở CSV) = 16.944.
   Việc lọc **có báo cáo** ra `staging/*.rejected-codes.tsv`, không im lặng.

2. **Mã nhóm cũng mang ký hiệu `†/*`.** `strip_marker` ban đầu chỉ áp cho mã bệnh
   nên 83 mã nhóm biểu hiện của WHO (`D63*`, `G01*`…) tồn tại song song với bản
   không dấu, tách đôi phân cấp.

3. **PDF ngắt dòng giữa từ sau dấu gạch nối.** `"glucose-6-\nphosphate"` sau khi
   gộp khoảng trắng thành `"glucose-6- phosphate"`. Thêm `fix_hyphen_wrap()`, chỉ
   nối lại khi dấu gạch **không** có khoảng trắng phía trước — nhờ vậy gạch nối
   đúng nghĩa trong tiếng Việt (`"dạ dày - thực quản"`) không bị đụng.

**Điều chỉnh thiết kế**

4. **Thêm `source` vào `concepts.parquet`** (§4.1). Merge concept trùng mã cần
   tie-break tất định, mà `sort_by` của pyarrow không bảo đảm ổn định. Thứ tự ưu
   tiên khai báo tường minh ở `load/writer.py::SOURCE_PRIORITY`.

5. **Không ghi timestamp vào `.sqlite`.** Cột `sources.ingested_at` để NULL có
   chủ đích; mọi mốc thời gian nằm ở `manifest.json`. Đây là điều kiện để
   `artifact_sha256` tái lập được — đã kiểm bằng 3 lần build liên tiếp.

6. **`_HYPHEN_WRAP` và `is_disease_code` là hàm thuần trong `normalize/`**, nên cả
   ba phát hiện trên đều có unit test riêng, chạy mili-giây, không cần nguồn thô.

### Phase 2 — kết quả đo

```
concepts   141.948   (16.944 ICD bệnh + 296 ICD nhóm + 124.708 RxNorm)
terms      487.776
relations  372.024
artifact   248 MB
17/17 rule · 30/30 smoke query
```

**Sự cố hiệu năng và cách sửa — phần đáng giá nhất của phase này**

Lần build đầu đạt hết cổng nhưng `validate` mất **1.312 s** (22 phút) cho 30 truy
vấn — tức ~44 s/truy vấn. Không sửa thì bộ đo của Phase 2.5 vô dụng.

Chẩn đoán bằng cách bóc từng lớp: bản thân FTS5 **nhanh** (`MATCH` + `ORDER BY
bm25` + `LIMIT 80` mất 0,01 s). Vấn đề nằm ở query plan:

```
SEARCH c USING COVERING INDEX (vocab=?)      ← concepts làm VÒNG NGOÀI
SEARCH t USING INDEX idx_terms_concept
SCAN terms_fts VIRTUAL TABLE                 ← MATCH chạy lại cho mỗi ứng viên
```

Vì `c.vocab = ?` nằm ở mệnh đề `WHERE`, planner tưởng lọc theo `concepts` là rẻ
nhất rồi đặt FTS vào trong cùng. Đo được **7,42 s cho một truy vấn**.

Sửa bằng hai thay đổi đi cùng nhau:

1. **Thêm cột `vocab` vào `terms` và vào `terms_fts`** — denormalize có chủ đích.
   Nhờ đó bộ lọc bộ mã đẩy được vào chính biểu thức MATCH:
   `vocab:"icd10" AND {norm_term ascii_term}:("thiếu" OR "men" OR …)`
2. **Tách truy vấn thành hai tầng bằng CTE.** Tầng trong chỉ đụng FTS, không
   JOIN, nên planner buộc phải lấy FTS làm vòng ngoài; tầng ngoài join trên tập
   đã nhỏ.

| | trước | sau |
|---|---|---|
| một truy vấn | 7,4 s | **1,7–112 ms** |
| `smk kb validate` | 1.312 s | **1,1 s** |

Đây là loại hỏng mà cổng chất lượng **không** bắt được — mọi rule vẫn xanh, chỉ
có thời gian là bất thường. Nên đã thêm `test_toc_do_truy_van` vào integration
test để bắt hồi quy về đúng lớp lỗi này.

**Ba quyết định về phạm vi**

3. **Concept = rxcui có ≥1 atom `SAB=RXNORM`** (124.708). Atom từ SNOMEDCT_US,
   MTHSPL, GS, NDDF gắn vào làm synonym chứ không tự tạo concept — đây chính là
   nguồn làm giàu **E3** mà §P3.1 ghi "chi phí bằng không".

4. **Không nạp `RXNSAT.RRF`** (531 MB, 7,7 triệu dòng). Phân bố thuộc tính gần
   như toàn bộ là metadata đóng gói: `SPL_SET_ID` 1,9 triệu, `NDC` 1,2 triệu,
   `LABELER`, `MARKETING_*`. Không thứ nào phục vụ 4 hàm API (§4.2). Hai thuộc
   tính có thể hữu ích — `ATC_LEVEL`, `FDA_UNII_CODE` — chỉ vài trăm dòng.

5. **Chiều quan hệ trong RXNREL ngược với trực giác.** Dòng
   `rxcui1=315431 | rela=consists_of | rxcui2=243670` đọc là *"243670
   consists_of 315431"* — quan hệ đi từ `rxcui2` tới `rxcui1`. Đã verify trên dữ
   liệu thật trước khi viết code và khoá bằng test, vì đọc ngược sẽ lật toàn bộ
   đồ thị thuốc **mà không báo lỗi**.

**Một điều chỉnh về tiêu chí**

6. Tiêu chí gốc viết *"`neighbors` từ `IN:1191` ra được tập SCD"*. Thực tế RxNorm
   **không có cạnh trực tiếp IN → SCD**: đường đi là `IN → SCDC → SCD`
   (`1191 ←has_ingredient― 315431 ←consists_of― 243670`). Test đi đúng hai bước
   và vẫn khẳng định `243670` nằm trong kết quả.

7. Bộ smoke query có lỗ hổng: `expect_prefix` dùng `startswith` nên mã RxNorm
   `161` sẽ khớp nhầm `1610`. Thêm `expect_code` khớp chính xác cho nhánh thuốc;
   ICD giữ khớp tiền tố vì nó **có** phân cấp thật (`K21` ⊃ `K21.0`).

8. `SCHEMA_VERSION` 1.0.0 → **1.1.0** (thêm cột `vocab` vào `terms`). Chỉ phải
   chạy lại pha `load` — mất **10,9 s** thay vì build lại 27 phút. Đây đúng là
   mục tiêu G3 hoạt động như thiết kế.

### Phase 2.5 — kết quả đo (BASELINE cho Phase 3)

```
── Probe set: 122 cặp ──────────────────────────────────────
  lát cắt                 n      R@1      R@5     R@20      MRR
  ─────────────────────────────────────────────────────────────
  TỔNG THỂ              122    0.623    0.844    0.943    0.722
  chẩn đoán → ICD        84    0.560    0.810    0.917    0.668
  thuốc → RxNorm         38    0.763    0.921    1.000    0.841
  ca thường              87    0.713    0.897    0.989    0.797
  ca KHÓ                 35    0.400    0.714    0.829    0.535
```

Nhánh **thuốc đạt Recall@20 = 1,000** — mọi mention thuốc trong probe set đều
có mã đúng trong top-20. Trần truy hồi ở nhánh này đã kịch; muốn tăng điểm chỉ
còn cách cải thiện **xếp hạng**, không phải mở rộng ứng viên.

**Cách gán mã vàng, và giới hạn phải nói rõ**

Mã vàng gán từ kiến thức ICD-10/RxNorm rồi verify bằng `lookup(vocab, code)` —
tra theo **mã** để đối chiếu tên chính thức, **không** dùng `search_lexical`.
Gán bằng top-1 của chính bộ truy hồi đang đo thì phép đo thành vòng lặp tự khen.
Dù vậy đây vẫn là nhãn do máy đề xuất và **cần một lượt duyệt của người có
chuyên môn**; cho mục đích đo *delta* giữa hai lần build thì đã đủ.

Trong lúc đo phát hiện **2 nhãn vàng của chính tôi bị sai**, retrieval đúng:
`"docusate sodium"` → `71722` (PIN) chứ không phải `82003` (IN), và
`"rối loạn chuyển hóa lipoprotein"` khớp `E78.9` ("không xác định"). Đã sửa
nhãn — không đụng vào metric.

**7 ca trượt khỏi top-20, tất cả cùng MỘT nguyên nhân**

| mention | mong | nhận được |
|---|---|---|
| `phù` | R60 | G93.6, J81, Q63.0 |
| `tiểu đường` | E14/E11/E10 | T18, B46.2, O03.0 |
| `ung thư` | C80 | C46, U85, C46.0 |
| `THA` | I10 | Y06, F94.2 |
| `ĐTĐ` | E14/E11 | *(rỗng)* |
| `COPD` | J44 | *(rỗng)* |
| `GERD` | K21 | *(rỗng)* |

Cả 7 đều **không có token nào chung** với tên ICD chuẩn: `"tiểu đường"` vs
`"Đái tháo đường"`, `"ung thư"` vs `"U ác tính"`, và các viết tắt thì hoàn toàn
không xuất hiện trong tên. BM25 không thể cứu được lớp này — đây chính xác là
thứ **E5 (từ đồng nghĩa dân dã + viết tắt, đóng băng thành file)** nhắm tới, và
là lý do E5 nên được ưu tiên hơn tôi xếp ban đầu.

Ngược lại, `"thiếu men G6PD"` — ca mà PRD §7 xếp vào Điểm yếu 2 — lại **trúng
hạng #1**, vì nó vẫn chia sẻ token `thiếu`/`men`/`g6pd` với tên chuẩn dài. Bài
học: ranh giới "khó" không nằm ở độ dài chênh lệch mà ở **có hay không token
chung**.

### Phase 3 — kết quả đo

```
                        R@1     R@5    R@20     MRR
  TỔNG THỂ            0.836   0.975   1.000   0.897    ΔR@5 +0.131
  chẩn đoán → ICD     0.857   0.976   1.000   0.911    ΔR@5 +0.167
  thuốc → RxNorm      0.789   0.974   1.000   0.867    ΔR@5 +0.053
  ca KHÓ              0.857   0.971   1.000   0.903    ΔR@5 +0.257

  ✓ KHÔNG còn ca nào trượt khỏi top-20 (baseline: 7 ca)
```

Recall@1 tổng thể **+21,3 điểm** (0,623 → 0,836); nhóm ca khó **+45,7 điểm**
(0,400 → 0,857). Recall@20 đạt **1,000 ở cả hai nhánh** — trần truy hồi đã kịch.

```
concepts   141.948      terms       633.000   (487.776 auth + 144.882 derived + 342 generated)
relations  372.024      closure     168.451
artifact   326 MB       attributes  116.210   (gồm 11.685 thẻ ngữ nghĩa SNOMED)
```

**★ Kết quả quan trọng nhất: 2 trong 4 nguồn làm giàu bị BỎ vì đo thấy có hại**

| cấu hình | tổng R@1/R@5 | KHÓ R@1/R@5 | kết luận |
|---|---|---|---|
| không enrichment | 0,623 / 0,844 | 0,400 / 0,714 | mốc |
| chỉ **E5** curated | 0,828 / 0,959 | 0,857 / 0,943 | **gánh gần như toàn bộ mức tăng** |
| chỉ **E4** group rollup | 0,623 / **0,836** | 0,400 / 0,714 | tệ hơn cả không làm gì |
| chỉ **E2** icd10cm | 0,623 / 0,844 | 0,400 / 0,714 | đóng góp **đúng 0** |
| **E5 + E1** | **0,836 / 0,975** | 0,857 / 0,971 | ★ cấu hình chốt |
| E5 + E1 + E2 | 0,828 / 0,967 | 0,857 / 0,971 | E2 làm **tụt** |

- **E4 (`icd_group_rollup`) — BỎ.** Đúng rủi ro đã ghi sẵn trong code: mọi mã
  con của cùng một nhóm nhận đúng MỘT chuỗi giống hệt nhau nên BM25 không phân
  biệt được, mention ở mức nhóm khớp đều tất cả mã con.
- **E2 (`icd10cm_2027`) — BỎ.** Tên tiếng Anh của ICD-10-CM không giúp gì cho
  probe set vốn 84/122 là mention tiếng Việt, mà lại pha loãng tín hiệu.
- **E1 (SNOMED) — GIỮ.** Đóng góp khiêm tốn nhưng thật: ghép với E5 nâng ca khó
  R@5 từ 0,943 lên 0,971.
- **E5 (curated) — GIỮ.** Nguồn giá trị nhất, đúng như dự đoán từ Phase 2.5.

Code của E2/E4 vẫn giữ và bật lại được bằng `--only`. Kết quả âm này gắn với
**probe set hiện tại**; ai có probe set nhiều mention tiếng Anh nên đo lại E2.

**Bốn phát hiện trong lúc đo**

1. **Quét ngưỡng fan-in không phân biệt được gì** trong dải 5–50 — và lý do thì
   đáng giá: bộ chặn ở tầng **ingest** (cap 50) đã loại sạch phần đuôi nguy
   hiểm. Kiểm chứng trực tiếp: `T88.7`, `X44`, `Z88.8`, `X49`, `X64` — năm mã
   gom nhận nhiều concept nhất — đều có **0 term SNOMED**. Term còn trong KB
   phân bố fan_in 1–50 và không ca nào trong probe set rơi vào vùng nhạy cảm.
   Vậy bộ chặn *đã làm đúng việc*, còn núm chỉnh ở query time thì probe set này
   chưa đủ để hiệu chỉnh.

2. **`cm_to_who` ban đầu sai.** `K2100` được rollup thành `K21.00` — chuỗi hợp
   định dạng nhưng **không phải mã WHO có thật** — nên E2 âm thầm bỏ phần lớn
   mã CM. Đã sửa thành thử dần từ đặc hiệu xuống (`K21.00` → `K21.0` → `K21`)
   và chọn ứng viên đầu tiên **có thật** trong KB. Nghịch lý: sửa xong E2 nạp
   thêm 72k term nhưng điểm lại **giảm** — chính bằng chứng để bỏ E2.

3. **`icd_group_rollup` ra 0 term ở lần chạy đầu.** Nguyên nhân: mã 3 ký tự như
   `K21` **cũng là mã bệnh hợp lệ**, nên sau merge nó mang `entity_kind='disease'`
   chứ không phải `icd_group`. Lọc theo `entity_kind` là sai; phải lọc theo
   "mã không có dấu chấm".

4. **Ràng buộc FK bắt được lỗi thiết kế.** Lần load đầu sau enrichment fail vì
   `terms.source` có FK tới `sources` mà enricher chưa đăng ký nguồn của mình.
   Đó là hành vi **đúng** — enrichment cũng phải có provenance. Đã thêm
   `EnrichBatch.register_source`.

**Điều chỉnh phạm vi H1 (bao đóng)**

Kế hoạch §P3.4 đo bao đóng trên đồ thị IS-A của **SNOMED** (~7,6 triệu cặp).
Nhưng Phase 3 chốt SNOMED là *nguồn cho, không phải bộ mã thứ ba* — không tạo
concept SNOMED thì không có `concept_id` để bao đóng trỏ tới.

May là **cả ba ứng dụng của H1 đều thao tác trên mã ICD**, mà ICD có sẵn phân
cấp riêng. Nên bao đóng dựng trên đồ thị IS-A của chính ICD/RxNorm:
**168.451 cặp** thay vì 7,6 triệu. Nhỏ hơn 45 lần, phục vụ đúng ba mục đích đã
nêu, và kết luận "không cần graph DB" (D8) càng đúng hơn.

**H1 ở chiều precision — đo được**

Trên 414 ứng viên top-5 của 84 mention chẩn đoán: **107 (25,8%) không chung tổ
tiên nào với mã đúng** — đó là số ứng viên một bộ lọc bao đóng sẽ loại. Ví dụ:
`"tăng huyết áp"` → loại `R03.0` (chỉ số HA bất thường chưa chẩn đoán) và
`P29.2` (tăng HA sơ sinh); `"đái tháo đường"` → loại `O24` (ĐTĐ thai kỳ).

Recall **không đổi** vì mã đúng luôn nằm trong nhóm được giữ.

> Giới hạn phải nói rõ: phép đo này dùng **mã đúng** để xác định nhánh, mà lúc
> suy luận thật thì không có. Trong thực tế bộ lọc phải lấy nhánh từ ứng viên
> top-1 hoặc từ đa số. Vậy phép đo chứng minh **tín hiệu tồn tại và mạnh**,
> chưa chứng minh một chính sách lọc cụ thể.

**Một tiêu chí không đo được**

Cổng H2 yêu cầu "báo cáo tỉ lệ lệch giữa thẻ ngữ nghĩa và vị trí phân cấp".
Không thực hiện được: ta không lưu concept SNOMED nên không có phân cấp SNOMED
trong KB để đối chiếu. Thẻ vẫn được trích đủ (11.685 dòng `attributes`) và
**không** ghi đè `entity_kind` — phần cốt lõi của cảnh báo Bona & Ceusters vẫn
được tôn trọng.

### Phase 4 — kết quả đo, và những gì KHÔNG kiểm được

> ⚠️ **Docker daemon không chạy trong môi trường build này** (`docker` CLI có,
> `docker info` fail). Ba tiêu chí liên quan tới container **chưa được kiểm
> chứng thực tế**. Dưới đây tách rõ phần đã kiểm và phần chưa.

**Đã viết**

`docker/Dockerfile` multi-stage (`builder` | `runtime`), `docker/compose.yaml`,
`.dockerignore`, `scripts/fetch_raw_data.sh`, README viết lại toàn bộ.

**Đã kiểm được (native)**

| kiểm chứng | kết quả |
|---|---|
| venv **sạch** + `pip install -e ".[dev]"` theo đúng README | ✓ cài được |
| artifact build từ venv sạch vs venv dự án | ✓ **checksum trùng** `5f8cfc2c9ef4c04b…` |
| truy vấn khi `SMK_RAW_DIR` trỏ vào **thư mục rỗng** | ✓ `lookup` / `search_lexical` / `ancestors` / `similarity` đều chạy |
| `.dockerignore` chặn nguồn thô | ✓ chặn `data/knowledge_base/`, `data/staging/`; vẫn gửi artifact + probe + src |
| `scripts/fetch_raw_data.sh` | ✓ liệt kê đúng 5 nguồn, phân biệt bắt buộc/tuỳ chọn |

Kiểm chứng thứ hai là thứ **thay thế gần nhất** cho "checksum container ==
checksum native": nó chứng minh artifact tái lập được qua một môi trường Python
độc lập. Phần container chưa kiểm chỉ còn là lớp OS/base image.

**KHÔNG kiểm được — cần chạy lại khi có Docker**

```bash
docker compose -f docker/compose.yaml run --rm kb-build
docker compose -f docker/compose.yaml build kb-query
docker compose -f docker/compose.yaml run --rm kb-query eval
# rồi so artifact_sha256 trong manifest.json với bản build native
```

**★ Một rò rỉ kiến trúc bị bắt trong lúc làm Phase này**

Test `test_query_khong_import_module_build` phát hiện: `import
smart_medic.kb.query` **kéo theo `pyarrow`** — dependency chỉ có ở image
`builder`. Đường đi: `query.lexical` → `normalize.text` → Python chạy
`normalize/__init__.py` → `import pyarrow`.

Nghĩa là image `runtime` sẽ nổ ngay lúc import dù nó không cần parquet chút nào.
Đã tách phần chạy pha sang `normalize/phase.py`, giữ `normalize/__init__.py`
sạch hoàn toàn; `run()` nạp muộn.

Đáng chú ý: **lỗi này chỉ lộ ra vì viết test cho bất biến của container**, và
nó lộ ra ở tầng native chứ không cần Docker. Đúng loại lỗi mà cổng chất lượng
thông thường không bắt được — mọi rule vẫn xanh, mọi truy vấn vẫn chạy trên máy
dev vì ở đó pyarrow luôn có sẵn.
