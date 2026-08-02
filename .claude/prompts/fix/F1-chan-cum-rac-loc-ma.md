# F1 — chặn cụm rác + lọc mã theo danh mục BYT (V3 + V4)

> **Nguồn chuẩn:** [`docs/reports/leaderboard-gap-analysis.md`](../../../docs/reports/leaderboard-gap-analysis.md) §11.
> Sửa ở báo cáo trước, rồi đồng bộ sang đây.
>
> Rủi ro: **Thấp** · Cần nộp thử: **Không bắt buộc**

---

Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §4, §5, §9, §10.
Đọc trước: src/smart_medic/stages/ner.py (Gazetteer.from_kb, is_fragment),
           src/smart_medic/stages/linking.py (toàn bộ, kèm docstring).

Vấn đề đã đo: 116 mã ICD ta trả ra KHÔNG tồn tại trong data/ICD10_VN.csv, và
chúng đến từ đúng 17 cụm — không cụm nào là tên bệnh:
  'bên phải' N60.01 ×32 · 'tái phát' F33.40 ×23 · 'bên trái' N60.02 ×20
  'vết cắn' S10.17 ×9 · 'bị cắn' S20.17 ×7 · 'vùng ngực' M47.04 ×6
  'cánh tay' M01.02 ×5 · 'bàn tay' M01.04 ×3 · 'thành ngực' 'ruột non'
  'toàn diện' 'loạn thần' 'viêm xương tủy' 'Xuất huyết tiêu hóa' …
Hệ tham chiếu 23đ có 0 lỗi loại này và chỉ dùng 82 mã (ta 189, trong đó 15 mã
6 ký tự nằm ngoài danh mục BYT).

Việc:
1. ner.py — danh sách chặn theo LOẠI TỪ, không phải theo ca cụ thể:
   - từ vựng GIẢI PHẪU đứng một mình: bên phải/trái, cánh tay, bàn tay, ngón
     tay, vùng ngực, thành ngực, ruột non, ổ bụng, cẳng chân...
   - TRẠNG THÁI / TRẠNG TỪ: tái phát, toàn diện, ổn định, tiến triển, cấp tính,
     mạn tính (khi ĐỨNG MỘT MÌNH, không phải khi là hậu tố của tên bệnh)
   Đây là kiến thức chung về loại từ. KHÔNG chép thực thể từ
   data/probe/gold_real/README.md — đó là file cổng (quy tắc §5.7).

2. linking.py — CHỐT CỨNG: mã trả ra phải tồn tại trong data/ICD10_VN.csv
   (skiprows=2, cột 'MÃ BỆNH' và 'MÃ LOẠI', 12.218 mã). Không tồn tại thì:
   - thử cắt về mã cha (N60.01 → N60); nếu mã cha có thì dùng
   - vẫn không có thì để candidates RỖNG
   Nạp danh mục một lần, cache; KHÔNG gọi mạng.

3. Test:
   - mọi mã linking.py trả ra đều có trong ICD10_VN.csv (test hồi quy)
   - 17 cụm ở trên không sinh span nào
   - rerank=True vẫn được giữ (test hồi quy đã có ở tests/unit/test_arbiter.py)

CỔNG CHẶN (không đạt = có bug):
- B_CODE_NOT_FOUND = 0 khi chạy lại §9 bước 2
- smk solve 100 file, 5 bất biến, 0 span lệch offset
- pytest xanh

CỔNG ĐỊNH TUYẾN (không đạt = ghi số, đi tiếp):
- số mã ICD phân biệt <= 120 (hiện 189)
- C_CODE_MISMATCH giảm >= 30% (hiện 162 → <= 113)
- Δfinal trên gold_real >= 0

⚠️ gold_real chỉ dùng để so TƯƠNG ĐỐI. §2 cho thấy nó lạc quan 2,6 lần —
đừng đọc con số tuyệt đối như dự báo điểm thi.
