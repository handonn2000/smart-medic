# Phase 0 — hạ tầng đánh giá

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **0,5 ngày** · Tiền đề: **không có — đây là phase đầu**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §0.2, §4 Phase 0, §5 quy tắc 1/2/8.

Việc: dựng hạ tầng đánh giá làm điều kiện tiên quyết cho mọi cổng sau này.

1. Thêm lệnh `smk eval solve --gold <dir> --report <json>`:
   - tự nhận cấu trúc thư mục: gold_real/gold dùng `annotations_gold/`,
     gold_batch1 dùng `annotations/`; văn bản luôn ở `text/`;
   - đọc file bằng stages.textio.read_document (KHÔNG Path.read_text);
   - chấm bằng stages.scoring, xuất: final, text, assertions, candidates,
     span_precision/recall/f1 TỔNG và **theo từng nhãn trong 5 nhãn**.

2. Thêm paired bootstrap trên tài liệu (B=10000, seed ghim trong code):
   - CI 95% cho `final` của một lần chạy;
   - CI 95% cho `Δfinal` giữa hai file báo cáo (so sánh theo cặp cùng tài liệu).
   - API: `smk eval compare --base a.json --new b.json`.

3. Chạy cho cả 3 bộ gold, ghi docs/reports/synth-baseline.json.
   BÁO CÁO RIÊNG TỪNG BỘ — tuyệt đối không gộp.

Cổng nghiệm thu:
- chạy 3 lần cho ra số y hệt (tất định);
- `final` trên gold_real tái tạo đúng 0.4327;
- bảng theo nhánh tái tạo đúng: CHẨN_ĐOÁN R 0.851/P 0.742 · TÊN_XN 0.586/0.583 ·
  TRIỆU_CHỨNG 0.670/0.646 · THUỐC 0.865/0.942 · KẾT_QUẢ_XN 0.424/0.429.
  Lệch so với các số này nghĩa là hạ tầng đo sai — dừng lại và truy nguyên,
  KHÔNG sửa số trong tài liệu.

Cấm: sửa bất kỳ file nào trong stages/ ngoài scoring.py và cli.py.
