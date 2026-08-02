# Phase 5 — chọn cấu hình nộp

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **1 ngày** · Tiền đề: **Phase 4**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §4.0, §4 Phase 5, §5 toàn bộ
(đặc biệt quy tắc 11).

Phase này KHÔNG dừng gì cả — nó ĐỊNH TUYẾN: chọn một cấu hình đã xây để nộp.

BƯỚC 1 — đăng ký trước, TRƯỚC KHI nhìn gold_real. Tối đa 4 cấu hình, sàng sơ bộ
bằng dev tổng hợp và gold_batch1 (hai thứ KHÔNG phải cổng). Ghi danh sách vào
docs/reports/phase5-gate.json TRƯỚC khi chấm. Ví dụ:
   C0: labtest_extended=false, tagger=false, arbiter_model_weight=0.0  (baseline)
   C1: true,  false, 0.0
   C2: true,  true,  0.6
   C3: true,  true,  1.0

BƯỚC 2 — chấm cả 4 trên gold_real, MỘT LẦN, ghi hết. Dùng `smk eval solve` +
`smk eval compare` của Phase 0.

BƯỚC 3 — chọn theo luật cố định, không thương lượng:
   cấu hình nộp = argmax(final) trong các cấu hình có cận dưới CI 95% của
                  Δ(so với C0) > 0
   nếu tập đó rỗng → nộp C0

CỔNG CHẶN của cấu hình được chọn (kể cả khi đó là C0):
[ ] mọi cụm bẫy trong gold_real/README.md vẫn không có span nào phủ
[ ] smk solve chạy hết 100 file, 5 bất biến pass, 0 span lệch offset
[ ] gold (regression guard) không tụt quá 0.03
[ ] chạy lại được từ máy sạch, không gọi mạng

BÁO CÁO — luôn viết, dù kết quả thế nào: phase5-gate.json ghi CẢ 4 cấu hình,
mỗi cấu hình có final + CI + bảng theo nhánh, RIÊNG TỪNG BỘ GOLD.

Mục tiêu final >= 0.50 KHÔNG đạt cũng đi tiếp Phase 6 — cấu hình được chọn, kể
cả C0, vẫn phải đóng gói tái lập, vì đó mới là thứ quyết định bị loại hay không.

Cấm tuyệt đối: thêm cấu hình thứ 5 sau khi đã nhìn số trên gold_real (quy tắc 11
— đó là overfit bằng cách chọn); dò tham số cho tới khi qua cổng; báo cáo số
trên corpus sinh ra; gộp ba bộ gold.
