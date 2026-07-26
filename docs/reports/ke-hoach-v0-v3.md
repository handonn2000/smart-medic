# Kế hoạch v0 → v3

**Ngày:** 25/07/2026 · **Chiến lược:** vertical slice — lát cắt dọc mỏng chạy được end-to-end trước, đào sâu từng module sau.

Căn cứ số liệu: [`2026-07-25-phan-tich-du-lieu.md`](./2026-07-25-phan-tich-du-lieu.md).

---

## Nguyên tắc chi phối

**1. Không có model để train.** 0 file có nhãn → zero-shot. Cái xây ở v0–v2 là **pipeline**, không phải model. Model chỉ xuất hiện ở v3 (distill sang encoder offline) và mục đích là **đáp ứng yêu cầu reproducible của top-15**, không phải tăng điểm — học trò luôn kém thầy.

**2. Luôn có artifact nộp được.** Từ cuối v0 trở đi, bất kỳ lúc nào cũng phải có `output.zip` hợp lệ. Deadline ập tới thì nộp cái đang có, không phải nộp con số 0.

**3. Hạ tầng không được "để tối ưu sau".** Bốn lỗi đã ghi nhận (nhãn viết tắt hỏng 471 record, JSON cắt cụt, offset lệch NFC, span chồng lấn) **không có lỗi nào là lỗi model**. Bỏ qua ở v0 thì mỗi vòng sau debug lại đúng bốn lỗi đó.

**4. Phân bổ công sức theo trọng số, không theo độ thú vị.**

| Thành phần | Trọng số | Đầu tư | Vì sao |
|---|---|---|---|
| `candidates` | 0.4 | **cao nhất** | Khó nhất, và là nơi ăn điểm. Cần KB + retrieve + rerank |
| `text` | 0.3 | trung bình | Phụ thuộc NER; LLM few-shot đã khá tốt (99,8% span định vị được) |
| `assertions` | 0.3 | **thấp nhất** | ~80% concept có assertion rỗng → mặc định rỗng cho J=1. Thêm luật phạm vi mục là gần chạm trần. **Không đầu tư model ở đây** |

---

## v0 — Hạ tầng + baseline tất định

**Mục tiêu:** có `output.zip` hợp lệ, có thước đo, có baseline hồi quy. **Không dùng LLM.**

### Phạm vi

```
src/smart_medic/
├── io.py           đọc UTF-8, NFC-map, tính offset trên chuỗi thô
├── schema.py       dataclass Concept + validate() theo đúng 5 nhãn có dấu
├── kb/
│   └── icd.py      load ICD10.csv, làm sạch, gazetteer longest-match
├── pipeline.py     orchestrator: txt → List[Concept]
├── emit.py         ghi JSON (ensure_ascii=False) + đóng gói output.zip
└── score.py        WER + Jaccard + validate schema + verify position
```

**Baseline v0:** quét tên bệnh ICD nguyên văn (longest-match, có ranh giới từ) → span `CHẨN_ĐOÁN` + mã. Mọi thứ khác để rỗng. Chạy vài giây, offline 100%, không phụ thuộc mạng.

### Xử lý bắt buộc trong v0

- **NFC**: chuẩn hóa **chỉ trong bộ nhớ** để so khớp; `position` luôn tính trên chuỗi thô. File 14: raw 2.672 vs NFC 2.538 ký tự — lệch 134.
- **Con trỏ tìm kiếm** đẩy qua hết độ dài match, không phải `+1` (chống span chồng lấn khi có nhiều token `*****` giống nhau).
- **Làm sạch ICD**: lọc `Hiệu lực=Có` (bỏ 955 dòng) · xử lý 2.120 mã hậu tố `*`/`†` · bỏ dòng rác (`test`→`D15.098`) · stoplist 42 tên ≤6 ký tự · cờ `is_symptom_chapter` cho mã chương R.
- **Nhãn viết đầy đủ có dấu**: `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`.

### Definition of Done

- [ ] `python -m smart_medic.infer --input data/test --output data/output` chạy sạch trên 100/100 file
- [ ] `score.py --pred output/ --gold output/` → `FINAL_SCORE = 1.0000` + `Schema OK`
- [ ] `assert raw[start:end] == entity["text"]` đúng cho **mọi** entity, đặc biệt 20 file NFD `13,14,16,17,19,20,28,34,35,42,52,54,56,67,72,81,86,94,97,100`
- [ ] `assert candidates == []` cho mọi span type ∉ {`CHẨN_ĐOÁN`, `THUỐC`}
- [ ] `output.zip` đúng cấu trúc `output/1.json … output/100.json`
- [ ] Không có tên nhãn viết tắt trong toàn bộ output

**Ra khỏi v0 khi:** cả 6 mục trên xanh. Điểm số ở v0 gần như chắc chắn thấp — **đó không phải tiêu chí**. Tiêu chí là hạ tầng đúng.

---

## v1 — MVP: LLM trích xuất + hai nhánh mapping

**Mục tiêu:** bài nộp thật đầu tiên, có điểm ở cả ba thành phần.

### Kiến trúc

```
txt → [Extractor] → span + type + assertion thô
                         ↓
                   [assign_positions]  ← code tính offset, KHÔNG phải LLM
                         ↓
        ┌────────────────┴────────────────┐
   type=CHẨN_ĐOÁN                    type=THUỐC
        ↓                                 ↓
   gazetteer ICD                    RxNorm SCD/SBD
   (longest-match)                  (chuẩn hóa hàm lượng + dạng bào chế)
        ↓                                 ↓
        └────────────┬────────────────────┘
                [lọc precision]  → 1–2 mã
                     ↓
                  JSON + zip
```

### Quyết định thiết kế đã chốt

**Interface `Extractor`.** Lời gọi LLM nằm sau một interface trừu tượng ngay từ v1. Đường lui sang model offline ở v3 khi đó là đổi implementation, không đổi pipeline. Đây là bảo hiểm cho yêu cầu reproducible.

**LLM không được trả `position`.** LLM trả chuỗi span; code tự định vị trên chuỗi thô. Span không định vị được thì **loại bỏ** (tỉ lệ đã đo: 1/472). Lý do: LLM diễn giải thay vì trích nguyên văn.

**Type gate cho gazetteer.** Chỉ span `type=CHẨN_ĐOÁN` mới được tra ICD. Đây là lá chắn cho vấn đề 27% mention rơi vào chương R.

**Nhánh THUỐC target `TTY=SCD`** (phụ `SBD`), căn cứ 5/6 mã trong ví dụ của đề là SCD. Ràng buộc này làm luôn việc của bộ lọc chất phân tích XN: SCD bắt buộc có hàm lượng + dạng bào chế nên `glucose` trơ trọi trong bảng XN không khớp được gì.

**Assertion: mặc định rỗng + luật phạm vi mục.** Chỉ bật `isHistorical` cho concept nằm trong mục "Tiền sử bệnh" / "Thuốc trước khi nhập viện" (58 và 22 file có tiêu đề này). `isNegated` chỉ khi cue có ranh giới từ và không nằm trong 8 cụm cố định (`không được`, `không đặc hiệu`, `không rõ`…). `isFamily` **không bật ở v1** — bằng chứng cho thấy nó gần như bằng 0 trong corpus.

**Budget token ≥ 32k** cho mỗi lời gọi + hàm sửa JSON cắt tới object hoàn chỉnh cuối. Đã có tiền lệ 2/10 file hỏng vì `stop_reason=max_tokens`.

### Song song: `build_kb.py`

Phải làm cùng v1 vì nhánh THUỐC bị chặn cho tới khi có bảng tra, và vì ẩn số version cần gỡ sớm.

> **Việc #0 phải làm trước:** `git status` đang báo `D data/knowledge_base/RXNORM.csv` — file còn trong git HEAD (637.977 dòng, commit `a039dfe`) nhưng đã bị xóa khỏi đĩa, thay bằng `RxNorm_full_07062026/` untracked. **Chốt một nguồn** rồi commit: khôi phục CSV (`git checkout -- …`) hoặc chính thức chuyển sang RRF. Để lẫn lộn thì pipeline gãy trên máy khác — đúng kịch bản bị loại vì BTC không cài lại được.
>
> **Khuyến nghị: dùng RRF.** Nó là bản phân phối chính thống, và kèm các bảng phụ mà CSV không có — `RXNCUI.RRF` (remap, cần cho rủi ro version), `RXNSTY.RRF`, `RXNREL.RRF`. `RXNORM.csv` là export đa nguồn (RXNORM 323k · MTHSPL 218k · VANDF 70k · MSH 26k), rộng hơn về synonym nhưng lẫn nhiều nguồn ngoài RxNorm.

```
data/kb/
├── icd10_concepts.parquet    code · canonical_name · chapter · is_symptom_chapter · valid · has_dagger
├── icd10_aliases.parquet     alias_norm · alias_nodiac · code · alias_type · risk_short
├── rxnorm_concepts.parquet   rxcui · tty · str · is_current
├── rxnorm_aliases.parquet    alias_norm · rxcui · tty · weight
└── rxnorm_remap.parquet      old_rxcui → new_rxcui        (từ RXNCUI.RRF)
```

**Nguyên tắc sống còn:** hàm normalize là **một mẩu code duy nhất** dùng chung lúc build KB và lúc query. Tách đôi là sinh skew — alias trong index chuẩn hóa kiểu A, mention lúc chạy chuẩn hóa kiểu B, không bao giờ khớp và rất khó phát hiện.

Nhưng **hai nhánh cần hai normalizer khác nhau** (cùng interface, khác implementation):

| | ICD (Việt→Việt) | RxNorm (Anh→Anh) |
|---|---|---|
| Chuẩn hóa | NFC → lowercase → gộp biến thể gạch ngang (`–`/`-`) → giữ dấu làm trường chính + trường bỏ dấu để fuzzy | lowercase → chuẩn đơn vị (`MG`/`mg`, `MG/ML`) → chuẩn dạng bào chế (`tab`→`tablet`) → tách hoạt chất/hàm lượng |
| Lọc lúc build | `Hiệu lực=Có`, bỏ dòng rác, xử lý hậu tố `*`/`†` | `SAB=RXNORM` + `SUPPRESS=N` → 202.495 dòng; ưu tiên SCD/SBD, IN chỉ dùng làm neo co-reference |
| Sinh alias | cắt đuôi `", không đặc hiệu"` / `", khác"` / `"không phân loại nơi khác"` → alias thứ hai bắt cách nói rút gọn | gom SY/TMSY/PSN về cùng RXCUI |
| Cờ rủi ro | `risk_short` (42 tên ≤6 ký tự) · `is_symptom_chapter` (chương R) | `is_analyte` — **không** lấy từ semantic type (glucose và prothrombin mang nhãn *Pharmacologic Substance* y hệt aspirin); lấy từ ràng buộc TTY + danh sách tay |

`build_kb.py` phải in **version stamp + checksum** file nguồn. Vừa là yêu cầu reproducible của BTC, vừa là thứ phát hiện version mismatch kiểu `360047` ở lần sau.

### Definition of Done

- [ ] Tất cả DoD của v0 vẫn xanh (chạy như test hồi quy)
- [ ] 100/100 file có output, không file nào rỗng vì lỗi kỹ thuật
- [ ] `build_kb.py` chạy từ máy sạch, in version stamp, sinh đủ 5 bảng
- [ ] Điểm trên dev set 20 file **cao hơn v0** ở cả 3 thành phần
- [ ] Không mã nào do LLM "nhớ ra" — mọi mã truy được về một dòng trong KB

---

## v2 — Nâng precision

**Mục tiêu:** biến recall thành precision. Đây là vòng ăn điểm thật.

| Việc | Căn cứ | Kỳ vọng |
|---|---|---|
| **Rerank top-5 cho mention không trùng gazetteer** | Recall@1 ~51% nhưng Recall@5 = 94,9% | Lời nhất trong phần model |
| **Ngưỡng precision** — chỉ giữ mã khi điểm rerank vượt ngưỡng; gazetteer nguyên văn thì gán thẳng, còn lại phải qua ngưỡng | Pipeline cũ gán mã cho 97,6% chẩn đoán trong khi Recall@1 chỉ ~51% → khoảng nửa số mã đang sai | Chặn over-prediction |
| **Co-reference token bị che** | 17/30 file có neo plaintext; 13 file không neo → `candidates: []` | 68 concept THUỐC đang bỏ trống |
| **Retrieval ngữ nghĩa cho 6 file gazetteer không phủ** (37, 48, 56, 88, 94, 95) + mention dân dã | "Thiếu men G6PD" vs "Thiếu máu do thiếu men glucose-6-phosphate dehydrogenase [G6PD]" gần như không trùng token | Phần fuzzy không với tới |
| **Tuning α, THRESH trên dev set** | Rẻ, cải thiện chắc chắn — nhưng vô nghĩa khi chưa có dev set | — |

**Điều kiện tiên quyết:** dev set 20 file đã gán tay xong. Danh sách đã chốt: `1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94` (~750 concept).

**Kỷ luật:** mọi thay đổi ở v2 phải đo trên dev set trước khi vào bài nộp. Hai file cùng cluster near-duplicate không được nằm hai phía train/dev — dev set hiện tại đã đảm bảo 0 leak.

### Definition of Done

- [ ] Điểm dev tăng so với v1, tách bạch được đóng góp của từng thay đổi
- [ ] Tỉ lệ chẩn đoán được gán mã **giảm** so với v1 nhưng điểm candidates **tăng** (dấu hiệu precision đã lên)
- [ ] Hai file trong cùng cluster cho kết quả nhất quán (dùng làm test bất biến)

---

## v3 — Reproducibility

**Chỉ làm khi đã lọt top-15.** Trước đó là đầu tư sai chỗ.

### Trạng thái nhánh `feature/solution_v3` (v3.3, không model training)

- [x] KB runtime tự xác minh SHA-256 + kích thước trước khi parse.
- [x] Artifact CSV.gz và submission ZIP tái lập byte-for-byte.
- [x] Run manifest ghi phiên bản runtime cùng fingerprint input/output/KB/ZIP.
- [x] Smoke test từ bundle sạch, không có Git metadata hay nguồn ICD/RxNorm thô.
- [x] Metric simulator chạy với curated gold trong smoke gate.
- [x] Mention-first cho triệu chứng dân dã, giữ offset raw trên 20 file NFD.
- [x] Trích cặp `TÊN_XÉT_NGHIỆM`/`KẾT_QUẢ_XÉT_NGHIỆM` có unit,
      kết quả định tính và chẩn đoán hình ảnh.
- [x] Rewrite ICD cho cách gọi trong corpus + giải quyết parent/unspecified
      mà không thêm model/dependency.
- [x] Phân biệt analyte/thuốc bằng ngữ cảnh; khôi phục ca
      `Glucose 5% x 1000ml truyền tĩnh mạch` → RxNorm SCD `1795612`.
- [x] Mask `***` không còn bị bỏ sót; co-reference dùng độ dài khi duy nhất.
- [x] ConText scope chặn pseudo-negation/conditional và section leak sang phần Q&A.
- [x] Curated v3 gold + regression cho 6 cặp near-duplicate mạnh nhất.
- [x] v3.2 hardening các span chẩn đoán đặc hiệu, loại span ngắn/generic và
      mở rộng từ điển thuốc exact-match mà không thêm dependency runtime.
- [x] v3.3 thêm batch cross-document resolver có cơ chế abstain an toàn và ba
      artifact RxNorm (`current`, `legacy`, `both`) để kiểm tra tương thích gold.
- [x] 81 test, smoke test bundle sạch, schema/offset validator và curated metric
      đều pass; artifact ZIP giữ tính deterministic.
- [ ] Distill XLM-R được hoãn; đây là bước model-training riêng, không cần cho
      pipeline offline hiện tại.

Kết quả full-corpus v3.3 (`current`): **100 file, 1.585 mention**, trong đó
434 mention có candidates và tổng cộng 475 candidate code; schema/offset
self-score đạt **1,0000**. Phân bố type gồm 420 chẩn đoán, 520 triệu chứng,
251 tên xét nghiệm, 256 thuốc và 138 kết quả xét nghiệm. So với v3.2, 41/100
file thay đổi, loại ròng 31 chẩn đoán ngắn/generic và tăng 3 thuốc exact-match.
Proxy simulator tại ngưỡng 0,80 đạt **0,8638** (v3.2: 0,8648); đây chỉ là
expectation model khi chưa có gold, không phải dự báo trực tiếp điểm Viettel AI.

Artifact khuyến nghị là `data/output.zip`, SHA-256
`bd91d7a2d5ef7d26f7144b61cd65b7ce1b5987bdda6d216cc0966f5d2b7020da`.
Hai biến thể tương thích nằm ở `data/v3_3_variants/`; chỉ 7 bản ghi thuốc khác
nhau giữa các mode, nên giữ `current` làm mặc định. Chi tiết thay đổi và phép đo:
[`báo cáo v3.2`](./2026-07-26-v3.2-rule-hardening.md) và
[`báo cáo v3.3`](./2026-07-26-v3.3-precision-compatibility.md).

- Distill: LLM sinh nhãn bạc trên 100 file (+ dữ liệu ngoài nếu có) → fine-tune XLM-R token-classification (BIO + CRF). **Dùng XLM-R, không PhoBERT** trừ khi chạy VnCoreNLP tách từ — sai bước này là nguyên nhân phổ biến làm PhoBERT kém kỳ vọng, và span lệch thì WER tăng.
- Đóng gói weights, **không tải model lúc runtime**. SapBERT đã có tiền lệ tải rất dễ vỡ (cần socksio, sentence-transformers không load được vì thiếu config, tokenizer XLM-R cần sentencepiece + protobuf).
- Ghim phiên bản + seed. README cài đặt viết và thử từ **máy sạch**.
- Fallback offline cho mọi thứ phụ thuộc API.

**Rủi ro cần nhớ:** không cài lại được → **bị loại**. Đây là rủi ro mất trắng, không phải mất điểm. Nó xứng đáng được ưu tiên hơn vài phần trăm điểm số.

---

## Hai blocker ngoài tầm kiểm soát

| # | Câu hỏi phải hỏi BTC | Ảnh hưởng |
|---|---|---|
| 1 | **Công thức `candidates_score` chính xác?** | Chênh tới 0,27 điểm giữa hai cách hiểu — đủ để đảo thứ hạng. Cách hiểu sát-chữ tự mâu thuẫn (bộ dự đoán hoàn hảo chỉ được 0,336) |
| 7 | **Gold label dùng bản RxNorm nào?** | `360047` trong chính ví dụ của đề đã hết hiệu lực 07/2019 → remap `2178097`. Toàn file `RXNCUI.RRF` có 22.330 mã đã remap. Nếu gold sinh từ bản cũ, retrieve từ bản 2026 sai hệ thống ở đúng phần trọng số 0.4 |

**Không tối ưu sát metric trước khi câu 1 được chốt.** Nhưng nguyên tắc bất biến vẫn đúng bất kể công thức: đúng type → mã chính xác, ít mã, precision cao.

Đường lui cho câu 7 nếu BTC không trả lời: dựng sẵn bảng remap hai chiều, và đo trên dev set xem trả `{mã mới, mã cũ}` có hơn trả `{mã mới}` không. Quyết định này phụ thuộc công thức ở câu 1 nên hai blocker gắn với nhau.

---

## Bảng tóm tắt

| Vòng | Ra được gì | Phụ thuộc LLM | Chuyển vòng khi |
|---|---|---|---|
| **v0** | `output.zip` hợp lệ + `score.py` + baseline hồi quy | không | 6 DoD xanh |
| **v1** | Bài nộp thật, có điểm cả 3 thành phần | có (sau interface) | Điểm dev > v0 ở cả 3 thành phần |
| **v2** | Precision lên, over-prediction xuống | có | Điểm dev tăng, tách bạch được từng thay đổi |
| **v3** | Chạy lại được từ máy sạch | không (offline) | README cài được từ máy sạch |
