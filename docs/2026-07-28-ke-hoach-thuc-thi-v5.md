# Prompt thực thi — Smart Medic v5

> **Dành cho agent thực thi.** Tài liệu này là prompt đầy đủ: bối cảnh, sự thật đã đo,
> bẫy đã biết, lộ trình, tiêu chí nghiệm thu. Đọc hết §0–§4 trước khi chạm vào code.
>
> **Nguồn:** phân tích ngày 28/07/2026, chi tiết ở
> [`docs/reports/2026-07-28-huong-tiep-can-moi.html`](reports/2026-07-28-huong-tiep-can-moi.html)
> (10 tab) và [`bench/README.md`](../bench/README.md).

---

## 0. Vai trò và phạm vi

Bạn đang làm việc trên **Smart Medic** — bài dự thi Viettel AI Race 2026, đề
*"Ontological Reasoning in Medical Knowledge Retrieval"*. Nhiệm vụ của bạn là
thực thi lộ trình ở §5 theo **đúng thứ tự**, dừng lại ở mỗi cổng nghiệm thu và
báo cáo số đo trước khi đi tiếp.

**Bạn KHÔNG được:**

- Bỏ qua §5.G0 để nhảy vào phần mô hình. G0 là điều kiện cần để mọi số đo sau đó
  có nghĩa.
- Tự sinh gold bằng LLM (xem bẫy #2).
- Mở 5 nhánh cho 5 hướng (xem §5, phần "vì sao không phải 5 nhánh").
- Tuning tham số để tối đa hóa điểm trên dev gold hiện có (xem bẫy #1).
- Kết luận "nút thắt là X" từ một gold duy nhất (xem bẫy #3).

**Ngôn ngữ:** mọi báo cáo, comment, commit message viết bằng **tiếng Việt**, khớp
quy ước sẵn có của repo.

---

## 1. Bối cảnh tối thiểu

### 1.1 Bài toán

Input: 100 file `.txt` tiếng Việt tự do (ghi chú bác sĩ, bệnh án, blog y khoa,
hỏi–đáp). Output: mỗi file một `.json` là list các mention:

```json
{"text": "...", "position": [start, end], "type": "...",
 "assertions": [...], "candidates": [...]}
```

- 5 `type`: `TRIỆU_CHỨNG`, `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`, `CHẨN_ĐOÁN`, `THUỐC`
- 3 `assertion`: `isNegated`, `isFamily`, `isHistorical`
- `candidates`: mã ICD-10 cho chẩn đoán, RxCUI cho thuốc; **rỗng** với 3 type còn lại

### 1.2 Metric

```
final = 0,3·text_score + 0,3·assertions_score + 0,4·candidates_score
text_score       = 1 − WER
assertions_score = Jaccard
candidates_score = Jaccard          (quy ước: cả hai rỗng → J = 1)
```

Với quy ước `unmatched = zero` (đã xác nhận bằng thực nghiệm — nhánh v4.1 quét 12
cách hiểu, chỉ cách này khớp leaderboard), điểm **tách được**:

```
final ≈ (0,3·q_text + 0,3·q_assert + 0,4·q_cand) × M/(G+P−M)
        └────── chất lượng mỗi cặp khớp ──────┘   └── độ phủ ──┘
```

`G` = số mention gold, `P` = số mention ta phát, `M` = số cặp khớp.

### 1.3 Ràng buộc cứng (thứ tự ưu tiên)

| # | Ràng buộc | Vì sao ở vị trí này |
|---|---|---|
| **NFR1** | **Reproducible** — BTC cài lại được từ máy sạch | Không cài lại được = **bị loại**, mất trắng chứ không mất điểm |
| NFR2 | Chạy offline hoàn toàn khi nộp | Hệ quả của NFR1; API đóng không tái lập được |
| NFR3 | Determinism — cùng input, cùng output | Không có nó thì không đo được cải tiến |
| NFR4 | Suy giảm, không sập | Một file lỗi không được làm hỏng 99 file còn lại |
| NFR5 | Provenance — mọi mã truy được về một dòng KB | Chống LLM bịa mã |

> **Nguyên tắc chi phối:** khi reproducibility xung đột với accuracy, chọn
> reproducibility.

### 1.4 Lịch sử — hai hệ đã có

| | v3 (`feature/solution_v3`) | v4.1 (`feature/solution_v4.1`) |
|---|---|---|
| Kiến trúc | luật + gazetteer + retrieval từ vựng | v3 **+** tầng NER neural (XLM-R → ONNX) |
| Nguồn nhãn | không | nhãn bạc LLM trên 94/100 file test |
| Leaderboard | 21,5450 → 23,53 | chưa nộp |

**v4 CHỨA v3** (`CompositeExtractor` giữ luật làm primary, neural lấp đuôi) — hai
hệ **lồng nhau**, không độc lập. Xem sự thật #6.

### 1.5 Bản đồ file trên nhánh `feature/solution_v5`

Nhánh này là **hợp** của ba nguồn, đã gộp sẵn — không phải đi tìm ở nhánh khác:

| Đến từ | Nội dung |
|---|---|
| `feature/sample-data-gen` (gốc) | `scripts/gen_sample_data.py` · `data/generated_medical_records/` (314 tài liệu, 749 file) · `data/test/` · `docs/PRD.html` |
| `feature/solution_v4.1` | `src/smart_medic/` (pipeline v0→v4) · `scripts/` (train, preannotate, adjudicate) · `tests/` · `data/kb/` · `data/dev_gold*` (4 biến thể + `dev_adjudication.json`) · `docs/reports/*.md` |
| phân tích 28/07 | `bench/` (8 lệnh, stdlib thuần) · `data/runs/{v3,v4}/` · `docs/reports/2026-07-28-huong-tiep-can-moi.html` · chính file này |

```
bench/                          hạ tầng đo lường — stdlib thuần, 8 lệnh
data/dev_gold_consensus/        gold mặc định (giao 2 model)  ⚠ xem bẫy #3
data/dev_gold_{sonnet5,opus5,prefill}/   3 biến thể còn lại — dùng cho `bench robust`
data/dev_adjudication.json      314 xung đột CHƯA phân xử — đầu vào cho G0a
data/runs/{v3,v4}/              output thật của hai hệ, 100 file mỗi hệ
data/generated_medical_records/{synthetic,translated,restyled}/{annotations,text,intermediate}/
data/kb/                        artifact KB đã build (ICD + RxNorm alias)
data/knowledge_base/            ICD10.csv · RXNORM.csv (bảng gốc BTC)
```

**Khởi động trên máy sạch** (chạy đúng thứ tự này trước khi làm gì khác):

```bash
python3 -m bench selftest                    # 8/8 phải đạt
PYTHONPATH=src python3 -m smart_medic.infer \
    --extractor v3 --input data/test --output data/output --explain
PYTHONPATH=src python3 -m pytest tests -q    # 164 passed, 1 skipped
python3 -m bench robust --pred data/runs/v4 --pred data/runs/v3
```

Bước `infer` là bắt buộc: `data/output/*.json` bị `.gitignore` chặn, và hai test
trong `tests/test_annotate.py` cần artifact v3 ở đó. Không chạy nó thì 2/166 test
đỏ — **đó là thiếu dữ liệu, không phải lỗi code**.

> **`models/` rỗng.** `models/*.onnx` bị `.gitignore` chặn, nên **weights của v4
> (1,1 GB) KHÔNG có trong repo**. `--extractor v4` sẽ không chạy được cho tới khi
> train lại (`scripts/train_ner.py`) hoặc lấy weights từ máy đã train.
> `--extractor v3` chạy được ngay, không cần weights.
> `data/runs/v4/` là output đã lưu sẵn của v4, dùng làm mốc so sánh mà không cần weights.

---

## 2. Sự thật đã đo — KHÔNG đo lại, KHÔNG mâu thuẫn

Mọi con số dưới đây sinh từ `bench/` trên dữ liệu thật. Nếu bạn đo ra khác, **báo
cáo mâu thuẫn** thay vì âm thầm dùng số của mình.

### 2.1 Điểm và phân rã

| hệ | consensus | sonnet5 | opus5 | prefill | q_pair | độ phủ |
|---|---:|---:|---:|---:|---:|---:|
| v3 | 0,3214 | 0,3431 | 0,3635 | 0,3547 | 0,856 | 0,395 |
| v4 | 0,4192 | 0,5084 | 0,5270 | 0,5237 | 0,808 | 0,545 |

v4 mua độ phủ (0,395 → 0,545) bằng cách **bán** chất lượng (0,856 → 0,808).

### 2.2 Trần điểm từng module (oracle ablation trên v4, 4 gold)

| module | min | max | MDE dev 20 file | đo được? |
|---|---:|---:|---:|---|
| `+recall` (thêm gold thiếu) | +0,153 | +0,242 | ±0,040…0,058 | ✅ |
| `+precision` (bỏ pred thừa) | +0,058 | +0,208 | | ⚠ đảo dấu theo gold |
| `+candidates` (GP-02/03) | +0,044 | +0,077 | | sát mép |
| `+text` (biên span, GP-01) | +0,039 | +0,056 | | sát mép |
| `+assertions` | +0,018 | +0,026 | | ❌ dưới nhiễu |
| `+type` | +0,000 | +0,000 | | không có gì để lấy |

> **Hệ quả quan trọng nhất của bảng này:** một bản cài đặt đạt 50% trần của
> GP-02 cho +0,02…+0,04 — **dưới MDE ở mọi gold**. Đo GP-02/GP-03 bằng điểm cuối
> trên 20 file là vô nghĩa. Phải đo bằng **chỉ số mức module** (§5.G2).

### 2.3 Sáu sự thật khác

1. **`type` không vào công thức chấm.** Oracle `+type` = +0,0000 chính xác. Đừng
   đầu tư vào phân loại type ngoài mức cần để quyết định có gắn mã hay không.
2. **Biên span lệch hệ thống.** Gold 3,45 từ/span; nhãn bạc 3,09; pred v4 **2,36**
   (−1,09). Nặng nhất ở `KẾT_QUẢ_XÉT_NGHIỆM` (−2,38) và `CHẨN_ĐOÁN` (−1,18). Trên
   gold đầy đủ hơn thì lệch còn **−1,53**.
3. **Gold gần như không bao giờ có 2 mã.** consensus `{0: 518, 1: 171}`; ba gold
   còn lại mỗi cái đúng 1 mention/~1.000 có 2 mã. **Bền qua cả 4 gold.**
4. **Tỉ lệ gold rỗng khác nhau theo type** (bền qua 4 gold):
   `CHẨN_ĐOÁN` 7,7–14,8% · `THUỐC` 69,2–75,8% · 3 type còn lại 100%.
   ⇒ ngưỡng phát mã hai nhánh lệch nhau **5–9 lần**. Một ngưỡng chung là sai.
5. **Ghép tối ưu = ghép tham lam.** Greedy và Hungarian cho điểm trùng đến 4 chữ
   số trên cả hai hệ ⇒ cách ghép **không** phải nguồn bất định.
6. **v3 ⊂ v4.** Trên 20 file dev: chỉ v3 tìm ra **7** mention, chỉ v4 **417**, cả
   hai **416**. v3 đóng góp 0,8% mention mới ⇒ ensemble hai hệ này **vô giá trị**
   (hợp v3∪v4 cho **−0,005** so với v4 một mình).

### 2.4 Ba cấu trúc trong dữ liệu chưa hệ nào khai thác

| | Bằng chứng | Dùng ở |
|---|---|---|
| **Độ dài `*****` = số ký tự tên thuốc** | `*******` (7) trong `100.txt`, `len("aspirin")=7`. 99 cụm trên 30/100 file | GP-03 |
| **10 cụm file gần trùng** phủ 21/100 file | MinHash 8-shingle, cặp mạnh nhất J=0,797 | GP-05 |
| **RxNorm_full là đồ thị 7,4 triệu cạnh** | `RXNREL.RRF`; 1.318 lớp ATC; 116k dòng SNOMED CT | GP-03 |

Ngược lại: `ICD10.csv` chỉ có **1,13 tên/mã**, dài TB **8,88 từ** — gần như không
có từ đồng nghĩa. Đây là lý do retriever hiện tại đo được top-1 đúng **1/17** ngay
cả khi truy vấn bằng đúng text gold.

### 2.5 Dữ liệu sinh sẵn có (372 tài liệu, 11.261 span, **0 lỗi offset**)

Đo lại trên chính nhánh này bằng `python3 -m bench corpus`:

| tập | file | span | Δ độ dài span | nhãn thiếu | THUỐC rỗng |
|---|---:|---:|---:|---:|---:|
| dev_gold (chuẩn) | 20 | 689 | — | 15,2% *(nền)* | 76% |
| `synthetic` | 194 | 5.353 | **−0,12** ✅ | 30,5% ❌ | 10% ❌ |
| `translated` | 95 | 3.368 | **−1,11** ❌ | 9,0% ✅ | 9% ❌ |
| `restyled` | 83 | 2.540 | **−1,20** ❌ | 9,9% ✅ | 11% ❌ |

- `synthetic` (`data/generated_medical_records/synthetic/`) **dùng làm tập chấm chính** cho chất lượng span: MDE **±0,011** so
  với ±0,030 của dev 20 file.
- `translated`/`restyled` **KHÔNG train biên span** — lệch −1,11/−1,20 gần trùng
  khít lỗi của v4 (−1,09), train trên chúng là dạy lại lỗi cần sửa.
- **Không tập nào** hiệu chuẩn được ngưỡng phát mã (THUỐC rỗng 9–10% vs gold 76%).
- 741 mention THUỐC có RxCUI trong `synthetic` (dev gold chỉ có **16**) — dùng cho GP-03.

---

## 3. Năm cái bẫy đã có người sập

### Bẫy #1 — Tuning theo dev gold

Cùng một artifact cho **31,69** trên dev nhưng **23,53** trên leaderboard.
Gold LLM **nới tay ~8 điểm**. Dùng để so **tương đối** giữa các phiên bản; đừng
đọc mức tuyệt đối và đừng tối ưu tham số theo nó.

### Bẫy #2 — Tự sinh gold bằng LLM

Gold hiện có do LLM sinh, còn tầng neural của v4 được distill từ nhãn bạc LLM
trên cùng các file ⇒ hai bên **chia sẻ thiên kiến ở đúng chỗ ta đang đo**. Bằng
chứng: gold 3,45 → nhãn bạc 3,09 → pred 2,36, một dãy giảm đều.

> **Sinh thêm một vòng gold LLM nữa không gỡ được vòng lặp này.** Bước G0a bắt
> buộc phải do **con người** phân xử. Bạn chuẩn bị worksheet, con người quyết.

### Bẫy #3 — Kết luận nút thắt từ một gold

Bản đầu của báo cáo kết luận *"nút thắt đã đổi từ recall sang precision"* dựa trên
gold `consensus`. **Sai.** `consensus` là **phần giao** của hai model nên bỏ ~30%
mention; những mention nó bỏ chính là dự đoán **đúng** của v4, bị đếm thành
"thừa" ⇒ precision tụt giả tạo từ ~86% xuống 64,5%.

| gold | n | `+precision` | `+recall` | nút thắt |
|---|---:|---:|---:|---|
| consensus | 689 | **+0,208** | +0,153 | PRECISION (1,4×) |
| sonnet5 | 932 | +0,071 | **+0,211** | recall (3,0×) |
| opus5 | 978 | +0,064 | **+0,230** | recall (3,6×) |
| prefill | 1003 | +0,058 | **+0,242** | recall (4,2×) |

Điểm giao nằm giữa G=689 và G=857; chặn trên suy từ leaderboard cho `G_dev ≲ 800`
⇒ **bằng chứng hiện có không đủ để chốt**. Luôn chạy `bench robust` trước khi tin
bất kỳ chẩn đoán nào.

### Bẫy #4 — Cắt `candidates` xuống 1 mà chưa xếp hạng

Sự thật #3 nói gold gần như không bao giờ có 2 mã, nên `--max-candidates 1` có vẻ
là nước đi hiển nhiên. **Đo thì nó làm GIẢM điểm −0,0016 (p < 0,05 trên cả 4 gold).**

Nguyên nhân: **100%** danh sách 2 mã của v4 được sắp theo **chuỗi mã**, không theo
điểm (`['E78.4','E78.5']`, `['K29.6','K29.7']`). Cắt `[:1]` là lấy mã đứng trước
theo thứ tự chữ cái — ngẫu nhiên. Với `|G| = 1`:

```
E[J](k=1) = p₁          E[J](k=2) = (p₁+p₂)/2
k=1 thắng  ⟺  p₁ > p₂   ⟸  đòi hỏi danh sách ĐÃ được xếp hạng
```

> **Bài học tổng quát:** kết luận lý thuyết đúng vẫn cần điều kiện tiền đề được
> thoả. Xếp hạng trước, cắt sau — và **đo lại** thay vì giả định.

### Bẫy #5 — Hợp thô nhiều hệ

Hợp v3 ∪ v4 cho **−0,005** dù thêm mention. Mọi mention thêm vào phải đi qua
ngưỡng ở §5.G0b. **Không bao giờ hợp trực tiếp.**

---

## 4. Năm hướng và cấu trúc kết hợp

Chi tiết kỹ thuật từng hướng ở tab 01–05 của báo cáo HTML. Ở đây chỉ nêu **quan hệ**:

| Tầng | Việc | Hướng | Quan hệ |
|---|---|---|---|
| L1 | Phát hiện span + type | **GP-01** (lưới W2NER + semi-Markov CRF) *hoặc* **GP-04** (sinh có ràng buộc + MBR) | **chỗ rẽ duy nhất** |
| L2 | Assertion | ConText hiện tại | gần trần (+0,018) — **đừng động vào** |
| L3 | Ánh xạ mã | **GP-02** (ICD) ∥ **GP-03** (RxNorm) | song song, cộng thẳng |
| L4 | Quyết định phát/mã | *không thuộc hướng nào* | **hạ tầng dùng chung** |
| L5 | Hợp nhất & nhất quán | **GP-05** | trên cùng |

**Ba khối hạ tầng dùng chung** (báo cáo trình bày chúng bên trong một hướng, nhưng
cả 5 đều cần — phải tách ra):

1. **Tầng quyết định L4** — hiệu chuẩn isotonic + ngưỡng `p*` + chọn `k` bằng `E[J]`
2. **Union-Find IoU + bỏ phiếu + medoid WER** — GP-04 §4.2 và GP-05 §5.2 dùng chung
3. **Trie / Aho–Corasick trên tên KB** — GP-02, GP-03, GP-04 đều dùng

---

## 5. Lộ trình

### Vì sao KHÔNG mở 5 nhánh cho 5 hướng

1. **Thước đo không phân biệt được chúng.** §2.2: bản cài đặt thật của GP-02/GP-03
   cho hiệu ứng **dưới MDE**. Đây là vấn đề *dụng cụ đo*, không phải vấn đề *tổ chức*.
2. **5 kết quả độc lập không cộng lại được** (bẫy #5, đo được −0,005).
3. **L4 là biến gây nhiễu chung.** Mỗi nhánh tự chọn ngưỡng ⇒ 5 thí nghiệm bị nhiễu,
   không tách được phần nào thắng.
4. **Repo đã có provider pattern.** `Extractor` là Protocol nhiều implementation,
   chọn bằng `--extractor gazetteer|v2|v3|v4`; v3 và v4 **cùng tồn tại trong một
   cây**. Năm nhánh phân kỳ trên `src/smart_medic/` chống lại chính kiến trúc đó.

⇒ **Hai nhánh, và chỉ ở tầng L1.** Mọi thứ khác thêm vào nhánh chung dưới dạng
provider mới + cờ dòng lệnh.

---

### G0 — Chặn mọi thứ (~2 ngày, không mở nhánh nào)

Không có G0 thì mọi số đo ở G1–G3 đều không diễn giải được.

#### G0a · Gold gán tay 10 file

**Do con người phân xử, không phải LLM.** Bạn làm phần chuẩn bị:

- [ ] Chọn 10 file theo ba tiêu chí, **theo đúng thứ tự ưu tiên**:
  1. **Không** nằm trong holdout `12, 16, 25, 26, 31, 42` (giữ holdout sạch cho G1)
  2. **Không** lấy hai file cùng cụm near-duplicate:
     `[6,11] [7,9] [28,52] [30,44,76] [35,56] [42,62] [45,50] [51,70] [67,86] [80,95]`
  3. Phủ tầng: thể loại (bệnh án / hỏi–đáp / blog) × NFD × có mask
- [ ] Dựng worksheet phân xử: với mỗi mention, hiển thị **bất đồng giữa 4 gold có
      sẵn** (`data/gold_variants/`) — con người chỉ cần quyết ở chỗ chúng khác nhau,
      không phải gán từ đầu. Ưu tiên hiển thị: biên span, có/không có mã, số mã.
- [ ] Ghi ra `data/dev_gold_manual/`.

**Nghiệm thu G0a:**
- `python3 -m bench robust --pred data/runs/v4 --golds data/dev_gold_manual` chạy được
- Báo cáo: nút thắt là gì, `|candidates|` có bao giờ > 1 không, độ dài span TB
- Ba câu trả lời đó **chốt lại** ba chỗ mà 4 gold LLM đang mâu thuẫn

#### G0b · Tầng quyết định L4

Chạy trên chính output v4 hiện có — **không cần model mới**.

- [ ] **Xếp hạng candidates trước đã** (bẫy #4). Retriever phải trả điểm, và
      `candidates` phải sắp theo điểm giảm dần, không theo chuỗi mã.
- [ ] Hiệu chuẩn isotonic điểm retrieval → `p̂` thật. Kiểm bằng đường reliability + ECE.
- [ ] Chọn `k` bằng `bench.decision.best_candidate_set_singleton(p₁, p_rỗng)` với
      `p_rỗng` **theo type** (sự thật #4), không dùng ngưỡng chung.
- [ ] Ngưỡng phát mention `p* = S/(q̄+S)`, giải điểm bất động bằng
      `bench.decision.emission_fixed_point`.

**Nghiệm thu G0b:**
- `bench robust --pred data/runs/v4-L4 --pred data/runs/v4` → **thắng hoặc hoà trên
  cả 4 gold + gold gán tay**. Thắng đúng một gold là dấu hiệu đã tối ưu vào thiên
  kiến của gold đó → làm lại.
- Báo cáo `p*` hội tụ về đâu, và ngưỡng phát mã của hai nhánh CHẨN_ĐOÁN/THUỐC.
- **Đây cũng là bước giải bằng thực nghiệm câu hỏi precision-hay-recall mà §3 bẫy #3
  không chốt được** — vì `p*` tự tìm điểm tối ưu trên đường đánh đổi.

---

### G1 — Chỗ rẽ L1: hai spike có giới hạn thời gian (~3 ngày mỗi nhánh)

Nhánh `exp/gp01-grid` và `exp/gp04-constrained`. **Đây là hai nhánh duy nhất.**

Mỗi spike nhắm **đúng một câu hỏi**: *kiến trúc này có sửa được thiên lệch −1,09
từ không?* Không xây đầy đủ, không tối ưu, không ghép linking.

| | GP-01 | GP-04 |
|---|---|---|
| Ý tưởng | lưới quan hệ từ–từ (W2NER) + semi-Markov CRF + DP khoảng không chồng lấn | seq2seq sinh cấu trúc, ràng buộc bằng automaton hậu tố + trie mã, hợp nhất bằng MBR |
| Ưu | tái dùng pipeline train hiện có, ONNX, offline | đảm bảo `raw[s:e] == text` **bằng cấu trúc**; xoá luôn lớp lỗi NFD |
| Rủi ro NFR1 | thấp | trung bình — model lớn hơn |

**Đo trên `gen/synthetic` (194 file, MDE ±0,011)**, không phải trên dev 20 file:

```bash
python3 -m bench corpus --corpus ref:data/dev_gold_manual:data/test \
  --corpus gp01:data/runs/gp01-synth:data/generated_medical_records/synthetic/text
# (bỏ --corpus thì dùng mặc định: dev_gold + 3 tập sinh)
```

**Nghiệm thu G1:**
- Δ độ dài span co từ **−1,09** về **|Δ| < 0,3**
- `MISS_BOUNDARY` và `TEXT_INEXACT` giảm rõ rệt
- `bench robust` trên holdout 6 file: không tụt so với v4
- **Quyết định:** chọn một kiến trúc, đóng nhánh kia. Nếu cả hai đều đạt, giữ cả
  hai để G3 hợp nhất (khi đó chúng là hai hệ **khác kiến trúc** — đúng điều kiện
  mà v3/v4 không thoả, xem sự thật #6).

---

### G2 — Tầng L3, tuần tự (không song song)

GP-03 trước, GP-02 sau. Cả hai ghi vào cùng trường `candidates` và cùng bị L4 chặn,
nên phải đo **phần tăng thêm** của cái thứ hai khi đã có cái thứ nhất.

#### Bắt buộc: đo bằng chỉ số mức module, không phải điểm cuối

§2.2 đã chứng minh điểm cuối không đủ phân giải. Việc đầu tiên của G2 là **thêm
lệnh `bench link`**:

- Acc@1, Recall@5, Recall@20 trên tập mention có mã
- Tách hai nhánh: ICD (171 mention trong dev gold) và RxNorm (**741** mention
  trong `gen/synthetic`, vì dev chỉ có 16 — quá ít để kết luận)
- Chỉ số này phản hồi trong vài giây, thay vì sau một lần train

#### G2a · GP-03 — đồ thị RxNorm + phục hồi thuốc bị che

Thuần dữ liệu, **không model, không GPU**. Rủi ro NFR1 thấp nhất trong 5 hướng.

- [ ] Parse `RxNorm_full_07062026/rrf/` (16,8 triệu dòng) → artifact CSR ~37 MB
- [ ] Phục hồi mask: ràng buộc **độ dài ký tự** + lớp ATC suy từ ngữ cảnh +
      đồng tham chiếu (union-find) → ghép cặp bằng Hungarian
- [ ] Liên kết tập thể bằng Personalized PageRank (Forward-Push, **tất định**)
- [ ] Chính sách TTY: học từ dev, đừng đoán. Ví dụ đề dùng `308135` = **SCD**,
      còn dữ liệu sinh dùng toàn **IN** — mâu thuẫn chưa giải quyết, xem §7.

> **Ranh giới:** suy luận từ **độ dài mask** là đặc trưng tổng quát, có trong
> private test. Nó khác hoàn toàn với hard-code `file 100 → aspirin`. Ghi rõ điều
> này trong README, và phải có nhánh dự phòng khi luật độ dài vô hiệu.

**Nghiệm thu G2a:** Acc@1 nhánh RxNorm tăng, đo trên 741 mention của `gen/synthetic`;
số mask phục hồi được, kèm tỉ lệ đúng trên các ca kiểm chứng tay.

#### G2b · GP-02 — retriever ontology tiếng Việt

Đắt nhất trong 5 hướng, trần chỉ +0,044…+0,077 ⇒ **làm sau cùng trong G2**.

- [ ] Sinh corpus đồng nghĩa Việt cho 13.189 mã ICD (~100k cặp), **có bộ lọc
      round-trip** — biến thể phải được model thứ hai ánh xạ ngược về đúng mã gốc
- [ ] Self-alignment kiểu SapBERT, **negative lấy trong cùng nhóm bệnh** (302 nhóm)
      — đây là quyết định thiết kế quan trọng nhất, xem tab 02 §2.3
- [ ] Thác nước 26 chương → 302 nhóm → ~44 mã, rồi cross-encoder ở tầng cuối
- [ ] RRF hợp nhất: Aho–Corasick + BM25 + bi-encoder

> **Không dùng ANN cho ICD.** 13.189 × 768 fp16 = 20 MB, brute-force vài ms.
> HNSW là thừa. Chỉ cân nhắc cho nhánh RxNorm 638k–1,2M chuỗi.

**Nghiệm thu G2b:** Acc@1 nhánh ICD tăng từ mức nền **1/17** đo được; báo cáo
Recall@5/@20 để biết vấn đề nằm ở retrieve hay ở rerank.

---

### G3 — Tầng L5, có điều kiện

GP-05 **chỉ kích hoạt khi điều kiện thoả**. Đã đo: luật ① đáng **0,000** trên cả
v3 lẫn v4 (426 mention trùng dạng bề mặt, 0 mention sửa được — pipeline đã nhất
quán sẵn); luật ② **không đo được** trên dev hiện tại.

| thành phần | điều kiện kích hoạt |
|---|---|
| Hợp nhất đa hệ | ≥ 2 hệ khác **kiến trúc** (⇒ sau G1 nếu giữ cả hai nhánh) |
| Luật ② file gần trùng | gold gán tay phủ **trọn** ≥ 2 cụm near-duplicate |
| Active learning chọn file gán tiếp | **không** — làm được ngay, là đầu vào cho G0a vòng sau |
| Luật ① một nghĩa/văn bản | có extractor **không** tra mã tất định theo dạng bề mặt (ví dụ GP-04) |

---

## 6. Quy tắc bất di bất dịch

1. **Mỗi thay đổi phải chạy `bench robust`, không chỉ `bench score`.** Thắng đúng
   một gold = dấu hiệu đã tối ưu vào thiên kiến của gold đó.
2. **Δ < MDE thì chưa phải cải tiến.** MDE dev 20 file = ±0,054. Ghi nhận, đi tiếp,
   đừng dựa vào nó để quyết định hướng.
3. **Không hợp thô output nhiều hệ.** Mọi phép ghép đi qua ngưỡng L4.
4. **Mã phải truy được về một dòng KB** (NFR5). Model không bao giờ được "nhớ" mã.
5. **`position` tính bằng code trên chuỗi thô.** 20/100 file ở dạng NFD; đây là
   lớp lỗi **im lặng** — không ném exception, chỉ âm thầm mất điểm. Kiểm bất biến
   `raw[start:end] == text` ở **ranh giới mỗi stage**, không chỉ ở cuối.
6. **Đọc/ghi UTF-8, JSON `ensure_ascii=False`.**
7. **Ghim seed và phiên bản.** Chạy hai lần phải ra byte giống nhau (NFR3).
8. **Không dùng LLM lúc chạy inference nộp bài** (NFR2). LLM chỉ ở khâu dev sinh
   dữ liệu, và kết quả phải được cam kết vào repo.

---

## 7. Câu hỏi phải hỏi người dùng — không tự quyết

1. **Chính sách TTY của RxNorm.** Ví dụ trong đề dùng `308135` (SCD, có hàm lượng)
   nhưng dữ liệu sinh dùng toàn `IN` (hoạt chất). Mention `"doxycyclin"` trần trụi
   thì trả mã gì? Ảnh hưởng trực tiếp tới 0,4 trọng số của nhánh THUỐC.
2. **Giấy phép RxNorm/UMLS.** Đóng gói `.RRF` vào bài nộp cần kiểm điều khoản UTS.
   Phương án an toàn: nộp **artifact dẫn xuất** (chỉ các trường dùng đến) kèm
   script build.
3. **Ngân sách thời gian và LLM.** GP-02 cần ~100k lời gọi batch một lần. Nếu ngân
   sách không cho phép thì bỏ G2b, vì trần của nó chỉ +0,044…+0,077.
4. **Có được phép nộp model weights lớn không**, và giới hạn kích thước là bao
   nhiêu — quyết định GP-01 hay GP-04 ở G1.

---

## 8. Bản đồ lệnh

```bash
# kiểm chứng chính benchmark trước khi tin bất kỳ con số nào
python3 -m bench selftest

# điểm + phân rã + khoảng tin cậy
python3 -m bench score    --pred data/runs/v3 --pred data/runs/v4

# A/B kèm p-value hoán vị
python3 -m bench compare  --pred data/runs/v4 --pred data/runs/v3

# điểm mất ở đâu: 12 rổ lỗi + oracle ablation + quét recall
python3 -m bench diagnose --pred data/runs/v4

# BẮT BUỘC trước mọi kết luận: chẩn đoán có bền qua 4 gold không
python3 -m bench robust   --pred data/runs/v4

# ngưỡng tối ưu suy từ metric
python3 -m bench policy

# hệ giả lập tham chiếu (common random numbers)
python3 -m bench simulate

# thẩm định một tập nhãn mới so với tham chiếu
python3 -m bench corpus
```

Chạy hệ hiện có để sinh output mới:

```bash
PYTHONPATH=src python3 -m smart_medic.infer \
  --extractor v3 --input data/test --output data/output --explain
```

---

## 9. Báo cáo cuối mỗi cổng

Mỗi khi qua một cổng nghiệm thu, ghi một file
`docs/reports/<ngày>-<cổng>.md` gồm:

1. **Đã làm gì** — thay đổi cụ thể, đường dẫn file
2. **Số đo** — `bench robust` trên **cả 4 gold + gold gán tay**, kèm CI và p-value
3. **Δ so với mốc trước**, và Δ đó có vượt MDE không
4. **Điều gì KHÔNG đúng như dự đoán** — mục này quan trọng nhất; hai kết luận
   trong lịch sử dự án đã sai (bẫy #3 và bẫy #4) và cả hai chỉ lộ ra khi đo lại
5. **Việc còn treo** và câu hỏi mới phát sinh cho người dùng

> Viết đúng những gì đo được. Nếu một bước bị bỏ, nói rõ bỏ cái gì và vì sao.
> Nếu một giả thuyết bị bác bỏ, ghi lại — nó đáng giá ngang một cải tiến.
