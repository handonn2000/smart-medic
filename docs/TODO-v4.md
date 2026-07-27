# TODO — v4

**Cập nhật:** 27/07/2026 · nhánh `feature/solution_v4.1` · điểm gần nhất **21.5450**

---

## Bạn đang ở đâu

| thứ | trạng thái |
|---|---|
| `data/output.zip` | ✅ **sẵn sàng nộp** — 100 file, 1.585 mention, 158 thuốc có mã (trước là 14) |
| `data/silver_prompts/` | ✅ 100 prompt đã sinh |
| `data/silver_responses/` | ❌ **chưa có** — chưa chạy LLM |
| `data/dev_gold/` | ❌ **chưa có** ← đây là thứ chặn mọi thứ khác |
| `models/` | ❌ rỗng — chưa train |
| test | ✅ 140 xanh (system python3 và venv) |

---

## 0. Nộp `output.zip` hiện có — làm ngay, 10 phút

**Vì sao trước tiên:** artifact này đã chứa Phase 1 (13 → 157 thuốc có mã) và
Phase 2. Nó là **tín hiệu accuracy THẬT duy nhất** bạn có thể lấy mà không cần
train gì. Và nó trả lời luôn câu hỏi lớn nhất còn treo: giả thuyết "recall là
nút thắt" dự đoán điểm chỉ nhích **+1 đến +2** — vì Phase 1 sửa `candidates`
chứ không sửa recall. Nếu điểm nhảy vọt hơn thế, mô hình điểm ở
[`2026-07-26-v4-research-directions.md`](reports/2026-07-26-v4-research-directions.md)
§1 sai, và **toàn bộ thứ tự ưu tiên bên dưới phải xem lại**.

- [ ] Dựng lại artifact cho chắc chắn khớp code hiện tại:

```bash
PYTHONPATH=src python3 -m smart_medic.infer --extractor v3 --input data/test --output data/output --zip data/output.zip --explain
```

- [ ] Nộp `data/output.zip`, ghi lại điểm vào bảng ở mục 6.

**Xong khi:** có một con số mới trên leaderboard để so với 21.5450.

---

## ✅ ĐO ĐƯỢC RỒI — 27/07, sau khi có gold 20 file

**Luận điểm recall được XÁC NHẬN.** Đây là phép đo chặn mọi thứ, và nó đã xong.

| gold | G | khớp M | **recall** | precision | mật độ/1k | G_corpus suy ra |
|---|---:|---:|---:|---:|---:|---:|
| consensus | 689 | 315 | **45,7%** | 74,5% | 12,4 | 2.526 |
| sonnet5 | 932 | 410 | 44,0% | 96,9% | 16,8 | 3.417 |
| opus5 | 978 | 411 | 42,0% | 97,2% | 17,6 | 3.586 |
| prefill | 1003 | 412 | 41,1% | 97,4% | 18,0 | 3.678 |

**1. `--unmatched zero` đã được xác nhận bằng thực nghiệm.** Quét toàn bộ 12 cách
hiểu công thức: `zero` cho 31,69 (lệch 8,2 so với leaderboard 23,53), `skip` cho
86,31 (lệch 62,8). Không còn nghi ngờ gì — mention không khớp bị tính 0, nên
recall là trục điểm. Đây là câu hỏi #1 với BTC, nay tự trả lời được.

**2. Hai phương pháp độc lập cùng chốt kích thước gold.** Chặn trên
`G_corpus ≤ 2.940` suy từ delta leaderboard +1,9864 (§ mục 6) và mật độ đo trên
gold consensus (2.526) khớp nhau. Ba gold union (3.417–3.678) **vượt chặn** ⇒
chúng over-annotate ~25%. **Dùng `dev_gold_consensus` làm gold làm việc.**

**3. Thiếu 374 mention, thừa 108 — tỉ lệ 3,5:1.** Thiếu theo type: triệu chứng
169 · chẩn đoán 86 · tên XN 65 · thuốc 30 · kết quả 24.

**4. Đây là ĐUÔI DÀI thật, không phải vài phrase family còn sót.** 374 mention
thiếu trải trên **252 dạng bề mặt khác nhau**; top-20 chỉ phủ 23%. Kiểm tra tay:
`tăng huyết áp`, `nội soi`, `viêm nha chu`, `nôn`, `lú lẫn` đều KHÔNG có trong
gazetteer (bảng ICD chỉ có dạng đủ định ngữ như `tăng huyết áp thứ phát`).
⇒ Viết luật tay sẽ cần ~250 mục chỉ cho 20 file (27% corpus). **Phase 3 chính đáng.**

> ⚠️ **Gold do LLM sinh đang NỚI TAY cho ta ~8 điểm.** Chấm trên dev consensus
> ra 31,69 trong khi leaderboard thật là 23,53 — cùng artifact. Gold sinh bởi
> chính họ nhà model đang chạy pipeline nên chia sẻ thiên kiến. **Dùng dev gold
> để so TƯƠNG ĐỐI giữa các phiên bản, đừng đọc mức tuyệt đối.**

> ⚠️ **Gold CHƯA được adjudicate.** `data/dev_adjudication.json` có **314 xung
> đột chưa giải quyết** (không có trường quyết định). Consensus = phần hai model
> đồng ý, nên nó thiên về precision cao / recall thấp.

---

## 1. Gold dev set 20 file — ĐÃ XONG (pre-annotation)

**Vì sao:** hiện tại tín hiệu accuracy duy nhất là *một con số mỗi lần nộp*.
Không có gold thì không tuning được ngưỡng, không đo được model, và **không biết
provider recall làm điểm tăng hay giảm**. Mọi task từ mục 2 trở đi đều mù nếu
thiếu bước này.

20 file đã chốt sẵn (phủ đủ 14 tổ hợp thể loại × NFD × mask, không leak
near-duplicate): `1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94`.

- [ ] **1a.** Sinh prompt:

```bash
PYTHONPATH=src python3 scripts/preannotate_dev.py --emit-prompts data/dev_prompts --files 1,3,4,5,6,7,8,10,12,14,16,17,21,25,26,27,31,42,54,94
```

- [ ] **1b.** Chạy qua LLM. Với mỗi `data/dev_prompts/{n}.request.json`, gửi
  trường `system` + `user`, lưu câu trả lời thành `data/dev_responses/{n}.json`.
  Tên file chấp nhận: `{n}.json`, `{n}.response.json`, `{n}.txt`, `{n}.md`.
  Thân file là **mảng JSON** các object `{text, type, assertions, candidates}`.

  > ⚠️ **Không cần bỏ `position` bằng tay** — script tự bỏ qua. Nhưng câu
  > "liệt kê MỌI lần xuất hiện" trong prompt là **bắt buộc phải giữ**: nếu model
  > báo `vàng da` một lần trong khi nó xuất hiện bốn lần, các lần lặp sẽ bị gán
  > vào occurrence chưa dùng sớm nhất. Đó là hệ quả tất yếu của việc định vị từ
  > text, không phải bug — script sẽ liệt kê ra để bạn soi tay.

- [ ] **1c.** Ingest:

```bash
PYTHONPATH=src python3 scripts/preannotate_dev.py --ingest data/dev_responses --out data/dev_gold --files 1,3,4,5,6,7,8,10,12,14,16,17,21,25,26,27,31,42,54,94
```

- [ ] **1d.** **Đọc lại bằng mắt** mọi mục script liệt kê ở phần "cần người xem
  lại". Đây là *pre*-annotation; gold chỉ đúng sau khi người adjudicate. Ưu tiên
  các span "không định vị được" (model bịa) và các chuỗi lặp nhiều lần.

**Xong khi:** `data/dev_gold/` có 20 file, `ok` ≈ `in`, 0 lỗi schema.

---

## 2. Đo baseline thật + chốt cách hiểu metric

**Vì sao:** trước khi thay đổi gì nữa, phải biết v3.3 thật sự được bao nhiêu, và
công thức nào khớp leaderboard.

- [ ] **2a.** Chấm artifact hiện tại trên gold:

```bash
PYTHONPATH=src python3 -m smart_medic.score --pred data/output --gold data/dev_gold --src data/test --verbose
```

- [ ] **2b.** Quét mọi cách hiểu công thức:

```bash
PYTHONPATH=src python3 scripts/metric_sweep.py --pred data/output --gold data/dev_gold --leaderboard 21.5450
```

- [ ] **2c.** Ghi lại: tổ hợp nào cho con số **gần 21.5450 nhất**? Đó gần như
  chắc chắn là công thức BTC đang dùng.

**Điều cần xác nhận:** giả thuyết trung tâm là mention không khớp bị tính **0**
(`--unmatched zero`). Nếu hóa ra là `skip`, thì recall không quan trọng, chiến
lược precision-first của v3.3 mới đúng, và **kế hoạch v4 phải đảo ngược**.

---

## 3. Nhãn bạc 100 file

Chỉ làm **sau** mục 1 — cùng script, cùng đường gán vị trí, nên gold là bản
kiểm tra chất lượng cho quy trình sinh silver.

- [ ] **3a.** Prompt đã sinh sẵn ở `data/silver_prompts/`. Chạy qua LLM, lưu vào
  `data/silver_responses/{n}.json` (100 file).
- [ ] **3b.** Ingest:

```bash
PYTHONPATH=src python3 scripts/preannotate_dev.py --ingest data/silver_responses --out data/silver --files 1-100
```

- [ ] **3c.** Kiểm tỉ lệ drop. Drop cao ở nhiều file = prompt hoặc model có vấn
  đề, **đừng train trên đó**.

> 💡 Nếu quota cho phép: chạy 3 lần rồi chỉ giữ span mà **cả 3 lần đều đồng ý**
> (self-consistency). Đắt hơn nhưng nhãn sạch hơn nhiều.

**Xong khi:** `data/silver/` có ~100 file, tỉ lệ drop thấp và ổn định.

---

## 4. Train model

- [ ] **4a.** Cài dependency dev-time:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

- [ ] **4b.** Train + export (gold ghi đè silver khi trùng file):

```bash
.venv/bin/python scripts/train_ner.py --silver data/silver --gold data/dev_gold --export models
```

- [ ] **4c.** Chạy v4 và **đo trên gold**:

```bash
PYTHONPATH=src .venv/bin/python -m smart_medic.infer --extractor v4 --input data/test --output data/output_v4 --explain
PYTHONPATH=src python3 -m smart_medic.score --pred data/output_v4 --gold data/dev_gold --src data/test --verbose
```

**Xong khi:** điểm v4 trên gold **cao hơn** v3 trên gold. Nếu không cao hơn,
**đừng nộp** — quay lại mục 3 xem chất lượng nhãn bạc.

---

## 5. Hiệu chuẩn các placeholder

Tất cả đang là số đặt tay, mỗi chỗ đều có comment ghi rõ phải đo cái gì.

| tham số | ở đâu | đo cái gì |
|---|---|---|
| `--neural-min-score` (0.50) | `stages/neural.py` | quét theo **ĐIỂM THẬT**, không phải F1 |
| `--a1-top1-accuracy` (0.5) | `pipeline.py` | Recall@1 của retrieval trên gold |
| `--ambiguity-margin` (0.0) | `pipeline.py` | `q/(1−q)`, với `q` = P(gold có 2 mã) |
| `SYMPTOM_CHAPTER_TYPE_CONFIDENCE` (0.15) | `stages/extract.py` | P(gold nói CHẨN_ĐOÁN \| khớp chương R) |

- [ ] Quét `--neural-min-score` từ 0.3 → 0.8, chọn theo điểm gold.

> ⚠️ **Đừng tối ưu theo F1.** Metric phạt mention thừa và mention thiếu **đối
> xứng** qua mẫu số `G+P−M`, nên cực trị của F1 và cực trị của điểm **không trùng
> nhau**.

---

## 6. Sổ theo dõi điểm

| bản | thay đổi chính | điểm |
|---|---|---|
| v2 | lexical rerank | 14.0595 |
| v3.1 | mention-first symptom/lab | 19.4812 |
| v3.2 | contract tests, regimen | 21.5450 |
| **v4.1** | **thuốc IN/BN + tầng quyết định** | **23.5314** (+1.9864) |
| v4.2 | + provider neural | ⬜ |

**Đọc được gì từ +1.9864** (dự đoán trước khi nộp: +1 đến +2 — trúng):

Chỉ `candidates_score` thay đổi, nên `Δfinal = 0.4 · (số mã mới ĐÚNG) / D` với
`D = G + P − M`, `P = 1585`. Ta thay đúng 144 mention thuốc (cộng ~2 từ Phase 2),
và `D ≥ P` vì `G ≥ M`. Hai vế kẹp lại:

* **79 ≤ số mã mới đúng ≤ 146** ⇒ fallback IN/BN **chính xác ≥ 55%**. Đây là
  phép đo THẬT đầu tiên về chất lượng nhánh thuốc, không phải ước lượng.
* **G ≤ 2.940** — chặn trên cứng cho kích thước gold. Khớp với ước lượng 2.800
  từ mật độ, nên ngoại suy đó không sai lệch nhiều.

**Điều này CHƯA xác nhận:** Phase 1 không đụng gì tới recall, nên luận điểm
"recall là nút thắt" vẫn **chưa được kiểm chứng**. Tùy vào `D` thật, recall nằm
đâu đó trong khoảng **37%–84%** — quá rộng để ra quyết định. Chỉ gold dev set
(mục 1) mới thu hẹp được.

**Điều này ĐÃ xác nhận:** bỏ trống candidates thật sự mất điểm, đúng như suy
luận `J(∅, G) = 0`. Doctrine "rỗng thì an toàn" của v3.3 là sai, và đã sửa xong.

---

## Quyết định chỉ bạn mới trả lời được

- [ ] **Còn bao nhiêu lượt nộp?** Quyết định có đủ ngân sách cho thí nghiệm ở
  mục "tùy chọn" không.
- [ ] **Hạn vòng 1 là khi nào?** Nếu gấp, dừng ở mục 2 và nộp — mục 3–5 cần
  nhiều thời gian nhất.
- [ ] **Đã hỏi BTC hai câu chặn chưa?** (a) công thức `candidates_score` chính
  xác; (b) gold dùng bản RxNorm nào. Mục 2b trả lời gần đúng câu (a) bằng thực
  nghiệm, nhưng xác nhận chính thức vẫn tốt hơn.

---

## Việc phụ, nhưng là rủi ro loại trực tiếp

- [ ] **Khôi phục nguồn RxNorm.** `data/knowledge_base/` chỉ còn `ICD10.csv`.
  `data/kb/` (đã build) vẫn chạy được, nhưng ai clone sạch rồi chạy
  `kb/build.py` sẽ **không dựng lại được nhánh RxNorm**. Đây là rủi ro **NFR1
  (bị loại)**, không phải rủi ro điểm.

- [ ] **Thí nghiệm chính sách trùng lặp** (tốn 1 lượt nộp). 30,4% mention là
  `(text, type)` lặp trong cùng file (`khó thở` ×26). Nếu gold chỉ gán một lần
  mỗi document thì đó là 482 false positive. Có thể trả lời **miễn phí** ở mục 1
  bằng cách nhìn gold — làm thế trước khi tiêu một lượt nộp.

---

## Đừng làm

- ❌ **Đừng thêm blocklist / precision gate nữa.** v3.2→v3.3 bỏ 31 chẩn đoán và
  27 mã; theo mô hình điểm thì loại thay đổi đó tốt nhất là hòa.
- ❌ **Đừng nộp model recall khi chưa đo trên gold.** Metric phạt mention thừa
  đối xứng — thêm mention *có thể* làm mất điểm.
- ❌ **Đừng dùng `expected proxy @ 0.80` làm cổng release nữa.** Nó không nhìn
  thấy recall: đó là lý do nó chỉ nhúc nhích −0.0010 qua toàn bộ đợt sửa
  precision v3.2→v3.3.
- ❌ **Đừng để runtime tải model từ mạng.** Weights phải commit trong `models/`.
