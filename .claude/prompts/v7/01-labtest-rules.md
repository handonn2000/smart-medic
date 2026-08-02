# Phase 1 — nhánh xét nghiệm bằng luật

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **1,5 ngày** · Tiền đề: **Phase 0**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §0.3 mục D, §2.3, §4 Phase 1.
Đọc trước: src/smart_medic/stages/labtest.py (toàn bộ, kèm docstring),
           data/probe/gold_real/README.md.

Vấn đề đã đo: KẾT_QUẢ_XÉT_NGHIỆM recall 0.424 vì `_MEASURE` là regex số+đơn vị,
mà kết quả thật phần lớn KHÔNG phải số:
  "dương tính" · "(+)" · "(-)" · "chưa phát hiện bất thường" · "nguyên vẹn" ·
  "ST chênh lên / chênh xuống" · "Sóng T đảo" · "túi mật căng to với dịch quanh
  túi mật" · "tăng men gan nhẹ" · "cải thiện đến 20.6" · "đang chờ"

Việc:
1. Dựng data/curated/lab_panels.v1.yaml theo schema ở §2.3.
   Nguồn HỢP LỆ, đúng ba nguồn này:
     (a) kiến thức panel chuẩn (công thức máu, sinh hoá, đông máu, viêm gan,
         tim mạch, nước tiểu, chẩn đoán hình ảnh);
     (b) trích mẫu `^NHÃN:` từ 91 file data/test KHÔNG nằm trong gold_real
         (gold_real dùng 1,7,18,24,30,45,53,65,100 — loại đúng 9 file này);
     (c) data/probe/gold_batch1 (218 TÊN_XN).
   NGUỒN CẤM: data/probe/gold_real — nó là cổng (quy tắc 7).

2. Mở rộng labtest.py:
   - 5 lớp giá trị mới (§2.3): định tính, mô tả bình thường, mô tả bất thường,
     xu hướng, trạng thái;
   - ghép cặp TÊN→KQ theo 4 dấu ngăn đã đo (gold_real | gold_batch1):
     ": " (10 | 57) · " " (8 | 85) · văn xuôi " là "/" cho thấy "/" đo được là "
     (6 | ~19) · xuống dòng + gạch đầu dòng (2 | ~2);
   - từ điển viết tắt: BC, N, PTT, INR, BUN, HBsAg, CK-MB, Troponin I/T...
   - GIỮ NGUYÊN SECTION_WORDS và luật loại dòng gạch đầu dòng (đã đo: tránh 38
     entity thừa — đọc docstring _LABELLED trước khi đụng).

3. ner.py:223 — cho gazetteer nhận thêm term_type='atc_vi_name'
   (654 term đã có trong KB nhưng đang bị lọc ra). Một dòng SQL.
   KHÔNG kỳ vọng điểm từ việc này (đo được: chỉ 3 tên xuất hiện trong data/test).

4. Thay labtest._free() O(n) tuyến tính bằng bisect trên mảng mốc đã sắp.

5. Tạo data/curated/pipeline.v1.yaml với cờ `labtest_extended` (xem §4.0).

CỔNG CHẶN — không đạt nghĩa là CÓ BUG, sửa rồi chạy lại:
- mọi cụm bẫy liệt kê trong gold_real/README.md vẫn không có span nào phủ
- 0 span lệch offset trên toàn bộ 100 file data/test
- pytest xanh toàn bộ

CỔNG ĐỊNH TUYẾN — không đạt nghĩa là GHI SỐ, TẮT CỜ, ĐI TIẾP Phase 2:
- Δfinal > 0 và cận dưới CI 95% > 0  →  labtest_extended: true, ship
- Δfinal > 0 nhưng CI chạm 0         →  true, ghi rõ là BIÊN, Phase 5 xét lại
- Δfinal <= 0                        →  false, giữ nguyên code đã viết, đi tiếp

KHÔNG có tiêu chí dừng. Ràng buộc precision riêng đã BỎ — Δfinal kèm CI đã tính
cả hai chiều.
KHÔNG dò tham số để ép qua cổng định tuyến (quy tắc 6): tắt cờ là hành động hợp
lệ, ép số thì không.
Ghi docs/reports/phase1-labtest.json trong CẢ BA trường hợp, kèm bảng theo nhánh
cho gold_real và gold_batch1 — báo cáo riêng từng bộ, không gộp.
