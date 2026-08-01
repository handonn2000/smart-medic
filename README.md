# Smart Medic

**Ontological Reasoning in Medical Knowledge Retrieval** — hệ thống AI đọc văn bản y khoa tiếng Việt tự do (ghi chú bác sĩ, giấy ra viện, kết quả xét nghiệm, hồ sơ EHR) và:

1. **Phát hiện & chuẩn hoá khái niệm y tế** — ánh xạ cụm từ ngôn ngữ tự nhiên về mã chuẩn (ICD-10 cho bệnh, RxNorm cho thuốc).
2. **Suy luận ontology** — xác định quan hệ ngữ cảnh giữa các khái niệm (phủ định, người nhà, tiền sử).

Xây cho **Viettel AI Race 2026 — Vòng 1**. Đề bài đầy đủ: [`docs/PRD.html`](docs/PRD.html).

## Trạng thái

| Phần | Trạng thái |
|---|---|
| **Knowledge Base pipeline** | ✅ Xong (Phase 0–5) — xem [`docs/kb-pipeline-plan.md`](docs/kb-pipeline-plan.md) |
| Pipeline giải bài (NER → assertion → linking) | ⏳ Chưa bắt đầu |

KB hiện có **141.948 concept** (16.944 mã bệnh ICD-10 + 124.708 khái niệm thuốc RxNorm), 633.000 term song ngữ, artifact 326 MB. Truy hồi đạt Recall@20 = 1,000 trên probe set 122 cặp.

---

## Cài đặt

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"        # dev đã bao gồm extra `build`
```

Dependency lõi chỉ có `PyYAML` — đủ để **truy vấn**. `pymupdf` và `pyarrow` chỉ
cần khi **dựng** KB nên nằm ở extra `build`; nhờ vậy image runtime không phải
mang theo 213 MB thư viện nó không gọi tới.

Yêu cầu Python ≥ 3.11. Không cần GPU, không cần Docker, không cần kết nối mạng lúc build.

## Dựng Knowledge Base

### 1. Kiểm nguồn thô

```bash
./scripts/fetch_raw_data.sh
```

Script **không tự tải** — ba nguồn đều có điều kiện sử dụng riêng (SNOMED cần license, RxNorm cần tài khoản UMLS/UTS, ICD-10 tiếng Việt lấy từ công bố BYT). Nó chỉ báo thiếu gì và lấy ở đâu. Đặt nguồn vào `data/knowledge_base/` theo đúng cấu trúc script in ra.

### 2. Build

```bash
PYTHONHASHSEED=0 smk kb build
```

Mất ~27 phút từ trạng thái chưa cache (pha `extract` chiếm phần lớn: PDF 1.271 trang mất ~280 s, RxNorm RRF ~20 phút). Các lần sau, nếu nguồn thô không đổi thì pha `extract` được bỏ qua và build chỉ mất ~30 giây.

Kết quả: `data/artifacts/kb.sqlite` + `manifest.json`.

### 3. Kiểm tra

```bash
smk kb validate   # 20 rule + 30 smoke query, fail hard nếu sai
smk kb eval       # Recall@1/5/20 + MRR trên probe set 122 cặp
```

### Chạy từng pha

```bash
smk kb extract     # raw → staging/raw/      (đắt, có cache theo checksum nguồn)
smk kb normalize   # → staging/norm/         (hàm thuần, rẻ)
smk kb enrich      # → staging/enrich/       (chỉ THÊM, không sửa)
smk kb load        # → kb.sqlite + FTS5 + closure
smk kb validate
```

Đổi schema thì chỉ cần chạy lại `load` (~14 s) chứ không phải build lại từ đầu.

## Dùng Knowledge Base

Downstream **chỉ** import `smart_medic.kb.query` — đó là bề mặt công khai duy nhất.

```python
from smart_medic.kb.query import KBStore, lookup, search_lexical, ancestors, similarity

with KBStore() as kb:
    # tra theo mã
    lookup(kb, "icd10", "K21.0")          # Bệnh trào ngược dạ dày - thực quản với viêm thực quản
    lookup(kb, "rxnorm", "243670")        # aspirin 81 MG Oral Tablet

    # truy hồi từ vựng (BM25 qua FTS5)
    search_lexical(kb, "thiếu men G6PD", vocab="icd10", top_k=5)
    search_lexical(kb, "aspirin 81 mg po daily", vocab="rxnorm", top_k=5)

    # phân cấp — đọc từ bảng bao đóng truyền ứng
    ancestors(kb, concept_id)
    similarity(kb, a, b)                  # Wu-Palmer, không cần corpus
```

## Truy hồi ngữ nghĩa (tuỳ chọn)

Nhánh dense bổ trợ cho BM25 ở đúng lớp ca mà BM25 yếu: mention **không chia sẻ
token nào** với tên chuẩn.

```bash
pip install -e ".[dense]"        # thêm faiss-cpu + sentence-transformers (~1 GB)
PYTHONHASHSEED=0 smk kb dense    # dựng data/artifacts/kb.faiss
```

```python
from smart_medic.kb.query import KBStore, search_dense
with KBStore() as kb:
    search_dense(kb, "ung thư", vocab="icd10", top_k=5)
```

Index ghi kèm `kb.faiss.meta.json` chứa `artifact_sha256` của `.sqlite` lúc dựng.
Nếu artifact được build lại và `concept_id` đổi, `search_dense` **từ chối chạy**
thay vì trả về concept sai một cách im lặng — đó là failure mode nguy hiểm nhất
của kiến trúc này.

## Docker

Hai image cho hai nhu cầu:

```bash
# Dựng KB từ nguồn thô (nguồn mount READ-ONLY lúc chạy, KHÔNG vào image)
docker compose -f docker/compose.yaml run --rm kb-build

# Chỉ truy vấn — artifact nằm sẵn trong image, không cần nguồn thô
docker compose -f docker/compose.yaml build kb-query
docker compose -f docker/compose.yaml run --rm kb-query eval
```

`.dockerignore` chặn `data/knowledge_base/` khỏi build context, nên 9 GB nguồn thô không bao giờ được gửi tới daemon.

## Tái lập

`manifest.json` ghi **hai** checksum, vì chúng bảo đảm hai thứ khác nhau:

| | ổn định khi nào | dùng để |
|---|---|---|
| `artifact_sha256` | **cùng** môi trường | phát hiện build không tất định |
| `content_sha256` | **qua** các môi trường | xác nhận hai bên dựng ra **cùng một KB** |

Byte không thể ổn định qua các phiên bản SQLite: đo được rằng build native
(SQLite 3.51.0) và build trong container (3.46.1) trên cùng staging cho hai file
khác byte nhưng **nội dung sáu bảng giống hệt** — chúng chỉ serialize B-tree và
index FTS5 khác nhau.

Bốn điều kiện để `artifact_sha256` ổn định trong cùng môi trường:

1. `concept_id` gán bằng sort `(vocab, code)`, không phải thứ tự insert
2. Thứ tự `INSERT` tất định ở mọi bảng
3. `page_size` cố định + `VACUUM` cuối cùng
4. **Không timestamp, không đường dẫn tuyệt đối nào trong `.sqlite`** — mốc thời
   gian nằm ở `manifest.json`, đường dẫn nguồn lưu tương đối so với `DATA_DIR`

```bash
smk kb load && smk kb load   # so artifact_sha256 giữa hai lần
```

## Cấu trúc

```
src/smart_medic/kb/
  query/       ★ API công khai — nơi DUY NHẤT downstream được import
  schema/      ddl.sql là nguồn sự thật duy nhất về cấu trúc store
  extract/     raw → staging, một module một nguồn
  normalize/   hàm thuần, không I/O — coverage 99%
  enrich/      Phase 3, chỉ THÊM không sửa
  load/        staging → sqlite, gán concept_id tất định
  validate/    cổng chất lượng, fail hard

data/
  knowledge_base/  nguồn thô (gitignored, ~9 GB)
  curated/         từ đồng nghĩa tiếng Việt đã đóng băng (trong git)
  probe/           probe set đo Recall@k (trong git)
  artifacts/       kb.sqlite + manifest.json (gitignored)
```

Chi tiết thiết kế, kết quả đo và các quyết định: [`docs/kb-pipeline-plan.md`](docs/kb-pipeline-plan.md).
Hướng cho pipeline giải bài: [`docs/solution-backlog.md`](docs/solution-backlog.md).

## Test

```bash
pytest -m "not slow"   # nhanh, không cần nguồn thô — chạy trong CI
pytest                 # đầy đủ, cần artifact đã build
ruff check src tests && ruff format --check src tests
```

## Nộp bài Vòng 1

- Dự đoán nộp dưới dạng `output.zip` chứa `output/1.json … output/100.json`.
- Top ~15 đội phải nộp source code (data processing, training, inference), dữ liệu, model weights và README cài đặt. **BTC cài lại không được là bị loại** — đó là lý do mọi lựa chọn kỹ thuật ở đây ưu tiên tính tái lập.

## License

Code theo [MIT License](LICENSE). Dữ liệu tham chiếu của bên thứ ba (ICD-10, RxNorm, SNOMED CT) giữ nguyên điều kiện sử dụng gốc và chỉ được đưa vào đây cho mục đích nghiên cứu/dự thi.
