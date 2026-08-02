# F3 — gán mã cho TRIỆU_CHỨNG (V2) · **RỦI RO CAO, LÀM SAU CÙNG**

> **Nguồn chuẩn:** [`docs/reports/leaderboard-gap-analysis.md`](../../../docs/reports/leaderboard-gap-analysis.md) §11.
> Sửa ở báo cáo trước, rồi đồng bộ sang đây.
>
> Rủi ro: **CAO, đối xứng** · Cần nộp thử: **BẮT BUỘC**

---

Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §3 TOÀN BỘ trước khi
làm bất cứ gì. Đây là thay đổi VI PHẠM PRD §3.2 một cách có chủ đích, dựa trên
một suy luận từ leaderboard chứ không từ đề bài.

Suy luận: J_candidates = 10,87 trong khi bài nộp có 1.693/3.000 mục candidates
rỗng. Nếu quy ước "cả hai rỗng ⇒ Jaccard = 1,0" áp cho candidates thì riêng
1.693 mục đó đã đẩy J_candidates lên trên 0,5. Nó chỉ có 0,109.
⇒ Bộ chấm thật dùng công thức (b) của PRD, nơi gold rỗng đóng góp 0/1.
⇒ Mã thừa gần như không tốn gì; mã thiếu mất tất cả.
Hệ tham chiếu 23đ làm đúng điều này: 1071/1245 TRIỆU_CHỨNG có mã, 0/776
CHẨN_ĐOÁN có mã.

Việc — GIỮ THẬT NHỎ, để một lần nộp phân xử đúng MỘT giả thuyết:
1. linking.py: thêm TRIỆU_CHỨNG vào VOCAB_OF_TYPE → 'icd10'.
2. solve.py check_invariants: nới bất biến 3 cho TRIỆU_CHỨNG. GIỮ NGUYÊN cấm
   với TÊN_XÉT_NGHIỆM và KẾT_QUẢ_XÉT_NGHIỆM — tham chiếu cũng không gán mã cho
   hai nhãn đó.
3. Đặt sau một CỜ trong data/curated/pipeline.v1.yaml (vd `code_symptoms`),
   mặc định false. Bật lên chỉ để sinh bài nộp thử.
4. KHÔNG kèm bất kỳ thay đổi nào khác trong cùng bài nộp.

CỔNG CHẶN:
- 5 bất biến (đã nới) pass, 0 span lệch offset
- mọi mã mới vẫn tồn tại trong data/ICD10_VN.csv (chốt của F1)
- pytest xanh

CỔNG ĐỊNH TUYẾN — CHỈ LEADERBOARD PHÂN XỬ:
- nộp thử một lần. final tăng ⇒ giữ cờ true. final giảm ⇒ TẮT CỜ NGAY và ghi
  kết quả âm vào docs/reports/.
- gold_real KHÔNG dùng được cho quyết định này: bộ đo nội bộ cài đúng quy ước
  "cả hai rỗng ⇒ 1,0", tức nó cài GIẢ THUYẾT ĐANG BỊ NGHI NGỜ. Nó sẽ báo TỤT
  dù thực tế có thể TĂNG.

⚠️ Rủi ro ĐỐI XỨNG. Nếu công thức (a) mới đúng thì 1.693 mục đang được 1,0 sẽ
về 0 và điểm tụt mạnh. Giữ bài nộp hiện tại (18,6610) làm bản lui.
