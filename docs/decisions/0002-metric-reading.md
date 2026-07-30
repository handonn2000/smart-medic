# ADR 0002 — Cách đọc công thức metric, và cách xử lý phần không đọc được

- **Trạng thái:** ĐÃ QUYẾT
- **Ngày:** 2026-07-29
- **Ảnh hưởng:** mọi quyết định ưu tiên trong dự án

## Bối cảnh

Công thức chính thức `final = 0.3·text + 0.3·assertions + 0.4·candidates` để ngỏ ba điều:

1. **Quy tắc căn chỉnh entity** — ghép entity dự đoán với entity gold thế nào trước khi tính
   điểm từng entity. Đề bài không nêu.
2. **Xử lý entity không khớp** — entity thiếu và entity thừa được tính ra sao.
3. **`c_i` ở mẫu số `Σ_k (len(gt(k)) + 1)` đếm entity nào** — chỉ CHẨN_ĐOÁN/THUỐC, hay cả
   5 loại?

Điểm (3) đã hỏi và **BTC không công bố** — phải coi là hộp đen.

## Bằng chứng đo được

Cài cả ba cách đọc trong `src/smart_medic/scoring.py` và chấm trên 98 tài liệu thật:

**Một dự đoán hoàn hảo (pred ≡ gold) chỉ đạt 69,16/100:**

| Số hạng | Điểm | Ghi chú |
|---|---|---|
| text | 30,00 | không bị chặn |
| assertions | 30,00 | không bị chặn |
| candidates | **9,16** | danh nghĩa 40; `+1` ở mẫu số chặn ở ≈0,229 |

Top 1 bảng xếp hạng công khai = 50,41, tức **73% của trần này** — tỷ lệ hợp lý, corroborate
cách đọc.

**Cách đọc "matched" suy biến.** Xoá 30% dự đoán của chính mình:

| Cách đọc | final | Nhận xét |
|---|---|---|
| `matched` | **68,78** | *không đổi* — thưởng cho việc xoá dự đoán |
| `penalised` | **48,01** | phạt đúng |

## Quyết định

1. **Số chính thức nội bộ là `penalised / greedy_iou`.** Đây là cách đọc duy nhất phạt đơn
   điệu cả sinh thừa lẫn sinh thiếu.
2. **Luôn báo cả ba cách đọc trên mọi lần chạy.** Vì (3) là hộp đen vĩnh viễn, không bao giờ
   được rút gọn xuống một con số. Quy tắc diễn giải:
   - cải thiện `matched` mà không cải thiện `penalised` ⇒ **lách metric**, không phải tiến bộ
   - cải thiện `penalised` mà hại `docbag` ⇒ đang **sinh thừa**
3. **Giải hộp đen bằng đo, không bằng hỏi.** Ba probe (A: span+type rỗng hết · B: +mã thuốc ·
   C: +assertions) đọc thẳng đóng góp từng số hạng khỏi delta leaderboard.
   **P6.1 vì thế được nâng lên làm việc sớm, không phải việc cuối.**
4. **Căn chỉnh mặc định: greedy IoU**, xác định (sắp theo −IoU, rồi chỉ số gold, rồi chỉ số
   dự đoán). Chạy kèm `overlap_type` làm kiểm độ nhạy.
5. **Chặn `1 − WER` ở 0.** WER không chặn trên: gold `sốt` (1 từ) vs dự đoán
   `bệnh nhân có sốt cao` cho WER = 4,0 ⇒ `1−WER = −3,0`.

## Hệ quả — thứ tự ưu tiên của cả dự án

`text` + `assertions` = **60 trong 69,16 điểm khả thi (87%)**, còn `candidates` chỉ 9,16.

⇒ Phase 4 (candidates) xếp **sau** Phase 2 và Phase 3, và **không được rút người** từ chúng.
⇒ Không bao giờ ưu tiên theo trọng số danh nghĩa 0,4.

## Ghi chú

Nếu probe B cho thấy trần candidates cao hơn 9,16 đáng kể, mở lại ADR này — nó sẽ thay đổi
thứ tự ưu tiên toàn dự án.

---

## Cập nhật 30/07/2026 — phase P2

Phần thân ở trên **giữ nguyên**: ADR là bản ghi lịch sử của quyết định lúc ra quyết định.
Mục này ghi hai thứ đã đổi kể từ đó. Quyết định 1–5 **không** bị đảo.

### 1 · Trần thật là 70,00 / candidates 10,00 — con số 69,16 / 9,16 đã hết hạn

Bảng ở phần thân đo trên **98 tài liệu**. Gold hiện là **162 tài liệu · 7.435 entity ·
45,9 entity/file**. Đo lại (`scripts/analysis/leverage_map.py --seeds 6 --extras`):

| Số hạng | Bản 98 file | **Bản 162 file** |
|---|---:|---:|
| text | 30,00 | **30,00** |
| assertions | 30,00 | **30,00** |
| candidates | 9,16 | **10,00** |
| **trần** | 69,16 | **70,00** |

Top 1 bảng xếp hạng công khai 50,41 = **72%** của trần mới (trước ghi 73% của trần cũ).

Dùng **70,00 / 10,00** ở mọi chỗ. Thấy 69,16 hay 9,16 ở đâu, đó là bản đo cũ.

Kết luận vận hành **không đổi**: `text` + `assertions` = 60 trong 70,00 điểm khả thi
(**86%**), candidates 10,00. Không bao giờ ưu tiên theo trọng số danh nghĩa 0,4.

### 2 · SỐ CHÍNH THỨC LÀ MỘT CẶP, không phải một số

Quyết định 1 của phần thân chọn `penalised / greedy_iou`. Đo lại trên 162 gold cho thấy
điều đó **thiếu**, không sai:

`greedy_iou` không so trường `type` ở bất cứ đâu (`align()`, `scoring.py`). Nên số chính
thức **không bao giờ thưởng cho việc sửa type** — trong khi dưới `overlap_type`, sai type
10% mất **12,35 điểm** (sd ±0,82) và sai 20% mất 22,83.

Sửa lại thành:

> **Số chính thức nội bộ là cặp `(penalised/greedy_iou, penalised/overlap_type)`.**
> `greedy_iou` là điểm. `overlap_type` là **cột chặn**: một thay đổi chỉ được nhận nếu
> nó **không làm cột này giảm quá 0,010**.

`exact` giữ vai trò đèn báo bug offset: sụt về gần 0 trong khi hai cột kia bình thường
nghĩa là lệch ranh giới hệ thống, không phải khoảng trống mô hình.

Quy tắc này không còn là thứ phải nhớ: `tests/test_alignment_parity.py` biến nó thành lỗi
build. Chứng minh nó chặn được (đo thật, 162 gold, khôi phục 25% entity với type sai):

```
greedy_iou     52,83 → 70,00   Δ +17,17     ← trông như cải tiến lớn nhất dự án
overlap_type   52,83 → 43,19   Δ  −9,65     ← giá thật
verdict: ĐÁNH ĐỔI TYPE LẤY SPAN — từ chối
```

### 3 · Bar nghiệm thu — sàn 0,010 KHÔNG đủ một mình

Phần thân không nêu điều kiện dùng sàn. Paired bootstrap B=10.000 (`eval/bootstrap.py`,
resample theo tài liệu) đo trên gold hiện tại:

| So sánh | Δ | SE | CI95 | MDE |
|---|---:|---:|---|---:|
| bỏ cờ isFamily | −0,261 | 0,053 | [−0,371; −0,163] | 0,104 |
| sai 30% mã | −2,933 | 0,137 | [−3,202; −2,662] | 0,268 |
| bỏ 10% entity | −6,998 | 0,290 | [−7,572; −6,434] | 0,569 |
| bỏ 10%: seed A vs seed B | −0,167 | 0,426 | [−1,028; +0,662] | **0,835** |

Hàng cuối là điều kiện: hai hệ bỏ sót entity ở **những chỗ khác nhau** không phân biệt được
dưới ~0,84 điểm, kể cả khi tỷ lệ bỏ sót y hệt. Bar đầy đủ:

    Δ > max(0,010 ; 1,96·SE_bootstrap)   VÀ   CI95 không chứa 0

Sàn 0,010 **chỉ** hợp lệ cho cặp hệ thống tương quan cao — khác nhau ở một hậu xử lý, phần
lớn dự đoán trùng nhau. Dưới bar thì viết "dưới sàn nhiễu", không viết "cải thiện nhỏ".

---

## Cập nhật 30/07/2026 18:36 — **HỘP ĐEN ĐÃ MỞ. MỤC 1 VÀ MỤC 2 Ở TRÊN ĐỀU SAI.**

Hai lần nộp (Probe A rồi Probe B) và BTC **trả về chỉ số từng số hạng**, thứ mà cả ADR này
lẫn plan-v4 giả định là không bao giờ có.

### Công thức thật — khớp chính xác tới 4 chữ số, hai lần độc lập

```
final = 0.3·(100 − WER) + 0.3·J_assertion + 0.4·J_candidates
```

| lần nộp | WER | J_assertion | J_candidates | điểm quan sát | công thức cho |
|---|---:|---:|---:|---:|---:|
| Probe A | 73,3686 | 30,9496 | 11,0259 | 21,6847 | **21,6847** |
| Probe B | 73,3686 | 30,9496 | 14,8832 | 23,2276 | **23,2276** |

`WER` được BTC báo là **sai số thô**, còn `text_score = 100 − WER`. Ba số hạng đều ở thang
0–100. **`num_scored = num_records = 100`** ⇒ không tài liệu nào bị loại.

### Điều bị bác bỏ — bằng chứng cứng, không suy diễn

Chúng ta nộp `candidates = []` **toàn bộ**. Cách đọc `official` của ADR này
(`Σ_k |gt(k) ∩ pred(k)| / Σ_k (len(gt(k)) + 1)`) cho candidates **đúng 0,00** khi `pred` rỗng
— giao với tập rỗng luôn rỗng. **BTC trả về 11,0259.** Và 11,0259 đã **vượt trần 10,00** mà
"Cập nhật 30/07 mục 1" tính cho toàn bộ số hạng candidates.

⇒ Tử số của BTC **tính điểm cho "rỗng đúng chỗ"** (quy ước `jaccard(∅, ∅) = 1`, đúng như
`scoring.py` cài cho assertions nhưng **không** cài cho candidates).

**Hai con số sụp theo:**

| | ADR/plan ghi | thật |
|---|---|---|
| trần điểm | 70,00 | **100,00** |
| trần candidates | 10,00 (0,2501) | **40,00** |
| hệ số cầu nối `recall ≈ A/51,55` | dùng được | **VÔ HIỆU** — suy ra từ trần 51,81 dưới `official` |

Top 1 công khai 50,41 = **50%** của trần 100, không phải 72% của 70.

### Nhưng thứ tự ưu tiên KHÔNG đảo — và đây là chỗ dễ đọc sai nhất

Bảng "dư địa từng số hạng" (text 22,01 · assertions 20,72 · candidates 35,59) **đếm trùng**:
cả ba số hạng bị **cùng một cổng căn chỉnh** nhân vào. Hiệu chuẩn trên gold với đúng extractor
này (`m_gold = 0,7651`, chất lượng text trên cặp đã ghép `q = 0,8786`) cho:

    m_test = text_score / q = 26,6314 / 87,86 = 0,3031

⇒ **chỉ 30,3% slot entity được ghép trên test, so với 76,5% trên gold — kém 2,52 lần.**
Gold `restyled/` (tổng hợp, retention chuỗi bề mặt 63,5%) đã nói dối về chất lượng extractor.

Ba đòn bẩy quy về **cùng một thang điểm cuối**, từ nền 23,23:

| đòn bẩy | điểm | ghi chú |
|---|---:|---|
| P3 · recall ×1,5 | **+11,61** | cả ba số hạng cùng scale |
| P3 · recall ×2,0 | **+23,23** | |
| P3 · recall lên mức gold (77%) | **+35,40** | |
| P5 · mã ICD cho 791 span CHẨN_ĐOÁN | +3,11 … +6,23 | giá biên **đo được** +0,00787 điểm/span |
| P4 · module assertion thật | **+3,85** | J_assertion 30,95 → 43,80 |

**P4 nhỏ hơn plan tưởng rất nhiều:** `assertions = []` đã bắt được **71%** điểm assertions khả
thi ở recall hiện tại, vì quy ước `jaccard(∅,∅)=1` trả tiền sẵn cho mọi entity mà gold cũng
không có cờ. Con số 8,19 điểm của bản đồ đòn bẩy là trần ở recall 100%, không phải dư địa hôm nay.

⇒ **Kết luận vận hành giữ nguyên hướng, đổi hoàn toàn lý do và độ lớn: recall (P3) là đòn bẩy
áp đảo, gấp 4–9 lần P4 hoặc P5.** Câu "text + assertions = 86% điểm khả thi" ở mục 1 sai;
câu "đừng ưu tiên theo trọng số danh nghĩa 0,4" **vẫn đúng**, nhưng vì candidates bị cổng
recall chặn, không vì trần 10,00.

### Đặc tả CHÍNH THỨC của BTC — hộp đen đóng lại vĩnh viễn

Đề bài đã công bố đủ công thức. Ba điều ADR này để ngỏ từ đầu, nay có đáp án bằng văn bản,
không còn phải suy từ leaderboard:

**(1) Căn chỉnh CÓ so `type`.** Nguyên văn: *"đoán đúng phần text của khái niệm nhưng sai loại
… khái niệm sẽ bị tính 2 lần (do tạo ra 1 khái niệm mới so với ground truth) và mỗi lần đều
được tính 0 điểm với cả 3 loại metric."*

⇒ **`overlap_type` là căn chỉnh chính thức, không phải `greedy_iou`.** Sai type bị phạt **hai
lần**: gold bị miss = 0, pred thừa = 0. Quyết định 4 của phần thân ("căn chỉnh mặc định
greedy IoU") **sai**. Cột chặn của "Cập nhật 30/07 mục 2" thực ra **là cột điểm**.

⇒ **Probe A′ HUỶ.** Nó chỉ còn xác nhận điều đặc tả đã nói ra. Luật chi tiêu #2 (tab 05 §D):
không nộp để xác nhận điều nội bộ đã cho thấy chắc chắn.

**(2) `+1` là TRỌNG SỐ CỦA TÀI LIỆU, không phải mẫu số chặn.**

    candidates_score = Σ_i J_cand(i)·W_i / Σ_i W_i      với  W_i = Σ_{k∈i}(len(gt(k))+1)

`+1` chỉ nằm trong `W_i`. Nó **không** vào trong `J`, nên **không chặn gì cả** — bản cài tham
chiếu cho gold ≡ pred = **100,00/100,00/100,00**. Toàn bộ lập luận "trần 0,2501 ⇒ candidates
chỉ 9,16/10,00" của phần thân và của mục 1 **sai từ gốc**: đó là hiểu `+1` như mẫu số.

**(3) `1 − WER(i)` KHÔNG chặn ở 0.** Đặc tả viết `Σ(1−WER(i))/len(test)` không kèm `max(0,·)`.
Quyết định 5 của phần thân (chặn ở 0) **không khớp đặc tả** — lệch 0,49 điểm trên gold.

Quy ước rỗng thì khớp đúng `jaccard()` đang cài: `J=1` khi cả hai rỗng, `J=0` khi gold rỗng mà
pred không rỗng.

### Điểm nội bộ thật của làn R — scoring.py đang báo thiếu 16,53 điểm

Bản cài tham chiếu theo đặc tả, cùng `runs/_pred_gold`, cùng gold 162 file:

| | text | assertions | candidates | FINAL |
|---|---:|---:|---:|---:|
| **đặc tả chính thức** (`overlap_type`) | 59,07 | 47,24 | **41,68** | **48,57** |
| nếu type không tính (`greedy_iou`) | 66,72 | 54,07 | 48,38 | 55,59 |
| `scoring.py` hôm nay (`overlap_type`/`official`) | 59,56 | 47,24 | **0,00** | **32,04** |
| **TRẦN** (gold ≡ pred) | 100,00 | 100,00 | 100,00 | **100,00** |

Toàn bộ khoảng lệch nằm ở candidates: `cand_formula=official` báo **0,00** vì tử số là phép
giao, mà pred rỗng ⇒ giao rỗng. Đúng phải là **41,68** — công điểm cho ~66% concept mà gold
cũng không có mã.

### Việc còn phải làm

1. `scoring.py` cần một `cand_formula` thứ ba khớp hành vi BTC (tính điểm cho rỗng-đúng-chỗ).
   Cho tới lúc đó **mọi số candidates nội bộ đều sai** — `official` báo 0, `plain` báo quá cao.
   ⚠ File này ngoài phạm vi sở hữu của P2, phải mở phase riêng.
2. `scripts/analysis/leverage_map.py` phải chạy lại dưới công thức mới. Bảng đòn bẩy hiện tại
   đo trên trần 70,00 ⇒ **mọi ô đều lệch**.
3. Hệ số 51,55 phải xoá khỏi mọi tài liệu, thay bằng `m = text_score / 87,86`.

### 4 · Câu hỏi `c_i` — cách đọc cũ, giữ lại làm bản ghi lịch sử

Điểm (3) của "Bối cảnh" chưa được giải. Probe B đã dựng xong và đọc được nó **không tốn thêm
lần nộp nào**: `ΔC_thật = (B − A) / recall_est`, với `recall_est = A / 51,55`.

- ΔC_thật ≈ 10,0 ⇒ mẫu số đếm **mọi entity đã ghép** ⇒ ADR này đứng vững.
- ΔC_thật cao hơn rõ rệt ⇒ chỉ đếm 2 loại có mã ⇒ **mở lại ADR này**.

Ghi chú cuối phần thân ("nếu trần candidates cao hơn 9,16 đáng kể thì mở lại") vì thế đọc là:
**cao hơn 10,00 đáng kể**.
