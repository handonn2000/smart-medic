# Phase 4 — arbiter + lai

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **1,5 ngày** · Tiền đề: **Phase 3**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.1, §2.7, §4 Phase 4, §5 quy tắc 9.

Việc: thay chuỗi detector nối tiếp bằng kiến trúc proposer → arbiter → enricher.

1. src/smart_medic/stages/arbiter.py
   Bài toán: cho N span có thể chồng lấn, mỗi span có trọng số, chọn tập con
   KHÔNG chồng lấn có tổng trọng số lớn nhất.
   Đây đúng là WEIGHTED INTERVAL SCHEDULING (Kleinberg & Tardos §6.1):
     - sắp theo `end`;
     - p(j) = span cuối cùng kết thúc <= start(j), tìm bằng bisect;
     - OPT(j) = max(w_j + OPT(p(j)), OPT(j-1));
     - truy vết để lấy tập nghiệm.
   O(n log n), tất định. Tie-break bằng (start, end, tên proposer) để kết quả
   không phụ thuộc thứ tự đầu vào.

2. Bọc 4 proposer về cùng một giao diện, trả (span, type, conf, tên_proposer):
   P1 ner.Gazetteer · P2 labtest · P3 detect_masked_drugs · P4 tagger.

3. Trọng số khởi tạo theo NHÃN, dựa trên precision đã đo trên gold_real:
   - THUỐC: luật P 0.942 → luật thắng model
   - TRIỆU_CHỨNG: luật P 0.646 → model thắng luật
   - còn lại: hiệu chỉnh trên dev TỔNG HỢP, KHÔNG trên gold_real.

4. Giữ nguyên enricher: assertion.py; linking.py với rerank=True.
   ⚠️ `rerank` mặc định TẮT ở search_lexical. Quên bật = mất 45 điểm R@1 nhánh
   thuốc. Thêm test hồi quy khoá cứng điều này.

5. Sau arbiter, check_invariants bất biến 2 (không chồng lấn) trở thành đúng
   theo kiến tạo — giữ lại phép kiểm làm lưới an toàn, đừng bỏ.

CỔNG CHẶN: check_invariants pass; arbiter TẤT ĐỊNH (cùng đầu vào → cùng đầu ra,
không phụ thuộc thứ tự proposer); pytest xanh.

CỔNG ĐỊNH TUYẾN: Δfinal >= 0 so với cấu hình Phase 1. Không đạt →
arbiter_model_weight: 0.0, arbiter suy biến về đúng pipeline luật. AN TOÀN THEO
KIẾN TẠO: phase này không thể làm hỏng thứ đang có, nên không cần dừng.
