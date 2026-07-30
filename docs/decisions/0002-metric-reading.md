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

### 4 · Câu hỏi `c_i` vẫn là hộp đen — đã có cách đọc, chưa có kết quả

Điểm (3) của "Bối cảnh" chưa được giải. Probe B đã dựng xong và đọc được nó **không tốn thêm
lần nộp nào**: `ΔC_thật = (B − A) / recall_est`, với `recall_est = A / 51,55`.

- ΔC_thật ≈ 10,0 ⇒ mẫu số đếm **mọi entity đã ghép** ⇒ ADR này đứng vững.
- ΔC_thật cao hơn rõ rệt ⇒ chỉ đếm 2 loại có mã ⇒ **mở lại ADR này**.

Ghi chú cuối phần thân ("nếu trần candidates cao hơn 9,16 đáng kể thì mở lại") vì thế đọc là:
**cao hơn 10,00 đáng kể**.
