# F2 — mở rộng tiêu chí TRIỆU_CHỨNG (V5 + V6)

> **Nguồn chuẩn:** [`docs/reports/leaderboard-gap-analysis.md`](../../../docs/reports/leaderboard-gap-analysis.md) §11.
> Sửa ở báo cáo trước, rồi đồng bộ sang đây.
>
> Rủi ro: **Trung bình** · Cần nộp thử: **Nên**

---

Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §6, §9, §10.
Đọc trước: src/smart_medic/stages/ner.py (SYMPTOM_HEADS, Gazetteer.from_kb).

Vấn đề đã đo, ghép span giữa bài nộp của ta và bài 23đ:
  179 span ta gọi CHẨN_ĐOÁN thì tham chiếu gọi TRIỆU_CHỨNG (ngược lại chỉ 73)
  ta BỎ SÓT 430 span TRIỆU_CHỨNG, mà chỉ THỪA 17
  ta THỪA 432 CHẨN_ĐOÁN và 261 TÊN_XÉT_NGHIỆM
⇒ Ta bắn SAI CHỖ: thừa ở chẩn đoán/xét nghiệm, thiếu ở triệu chứng.

Nguyên nhân: ner.py chỉ gán TRIỆU_CHỨNG khi mã thuộc chương R hoặc cụm mở đầu
bằng SYMPTOM_HEADS (tập từ đóng, quá hẹp). Nhiều triệu chứng tiếng Việt ánh xạ
sang mã NGOÀI chương R — tham chiếu gán 'tiêu chảy'→K92.2, 'mụn'→B07,
'xuất huyết'→A97.9.

Việc:
1. Nguồn mở rộng ĐÃ CÓ SẴN và đã đóng băng:
   data/curated/surface_forms.v1.jsonl — 40 nhóm TRIỆU_CHỨNG, 306 cách nói dân
   dã (sốt/nóng sốt/phát sốt, khó thở/hụt hơi/ngộp thở, tim đập nhanh/hồi hộp
   đánh trống ngực...). Nạp nhánh TRIỆU_CHỨNG của file này vào gazetteer với
   nhãn TRIỆU_CHỨNG, ƯU TIÊN CAO HƠN nhãn suy ra từ chương ICD.
2. Rà lại SYMPTOM_HEADS — bổ sung đầu ngữ còn thiếu, nhưng ĐO trước khi thêm.
3. Không đụng nhánh THUỐC (P 0,942, đang mạnh nhất).

CỔNG CHẶN:
- 5 bất biến pass, 0 span lệch offset
- pytest xanh
- cụm bẫy gold_real/README.md không bị phủ THÊM so với trước khi sửa

CỔNG ĐỊNH TUYẾN:
- recall TRIỆU_CHỨNG trên gold_real tăng >= 0,05
- precision CHẨN_ĐOÁN không giảm
- Δfinal >= 0

Nếu có bài nộp tham chiếu, kiểm lại ma trận nhầm lẫn: ô
(tham chiếu=TRIỆU_CHỨNG, ta=CHẨN_ĐOÁN) phải giảm từ 179 xuống dưới 120.
