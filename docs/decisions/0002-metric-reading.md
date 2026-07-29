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
