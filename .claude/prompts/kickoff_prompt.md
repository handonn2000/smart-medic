# Prompt khởi động — dùng MỘT LẦN, cho agent chính

> Không phải prompt phase. Dùng khi một người/agent **tiếp quản dự án** và cần bối cảnh
> toàn cảnh trước khi phân phase. Trích từ `docs/reports/plan-v4.html` tab 07 §B.

---

```
Bạn tiếp quản dự án smart-medic — hệ trích xuất và chuẩn hoá khái niệm y khoa tiếng Việt
cho Viettel AI Race 2026, Vòng 1. HẠN NỘP 04/08/2026. Hôm nay 30/07/2026 ⇒ CÒN 6 NGÀY.
Pipeline suy luận CHƯA CÓ DÒNG NÀO. Ràng buộc này chi phối mọi quyết định của bạn.

## Đọc trước khi làm bất cứ việc gì
1. docs/reports/plan-v4.html — KẾ HOẠCH HIỆN HÀNH. Tab 03 = ngân sách điểm,
   tab 04 = 8 phase kèm tiền đề + tiêu chí nghiệm thu, tab 07 = prompt từng phase.
2. src/smart_medic/README.md — bản đồ 8 layer + quy tắc phụ thuộc.
3. docs/PRD.html — đề bài gốc.
4. docs/decisions/000{1,2,3}-*.md — ba quyết định đã chốt. ĐỪNG mở lại.
5. docs/reports/research-directions.html — căn cứ khoa học. Tra ở đây TRƯỚC khi đề
   xuất một hướng "mới"; ~90 tài liệu đã xác minh và một danh sách kết luận âm tính dài.
⚠ docs/reports/plan.html là bản v3 ĐÃ BỊ THAY THẾ (còn dùng trần 69,16 đo trên 98 file).
  Giữ làm bản ghi lịch sử; ĐỪNG trích số từ nó.

## Chạy ngay, theo thứ tự
    python3 -m pytest tests/ -q
    python3 scripts/analysis/measure_data.py
    python3 scripts/analysis/leverage_map.py --seeds 6 --extras
    PYTHONPATH=src python3 -m smart_medic.eval.scoring --pred data/output --describe

## SỰ THẬT SỐ 1 — TRẦN THẬT LÀ 70,00/100
Mẫu số candidates chứa `+1`: Σ_k (len(gold(k)) + 1), cộng cho MỌI entity đã ghép kể cả
3 loại không có mã. Chấm gold-vs-gold trên 162 file:
    text 1,0000 → 30,00 · assertions 1,0000 → 30,00 · candidates 0,2501 → 10,00
Top 1 công khai = 50,41 = 72% của trần này.

## SỰ THẬT SỐ 2 — KHOẢNG TRỐNG LỚN NHẤT LÀ RECALL SPAN, KHÔNG PHẢI CANDIDATES
data/output/ trích 1.585 entity = 15,8/file. Gold có 45,9/file (7.435/162). Thiếu 2,9×.
Nếu mật độ test giống gold thì hệ đang mất ~46 điểm chỉ vì không NHÌN THẤY entity.
So sánh: toàn bộ nhánh candidates đáng 10,00 điểm, và đi từ 30% mã sai xuống 10% mã sai
chỉ đáng 2,00 điểm.
⚠ PHẢI xác nhận bằng Probe A TRƯỚC khi đầu tư nặng: recall ≈ điểm_probe_A / 51,55.
  Nếu Probe A < 25 thì mật độ test khác gold căn bản và TOÀN BỘ thứ tự ưu tiên phải
  xét lại. Đây là phase P2, và tiền đề của nó chỉ là P0 + một tập dự đoán — làm được
  bằng data/output/ hiện có, ĐỪNG đợi có extractor tốt.

## SỰ THẬT SỐ 3 — RỦI RO TYPE-ALIGNMENT
scoring.py có 4 chế độ căn chỉnh. Dưới greedy_iou (mặc định, và là SỐ CHÍNH THỨC nội bộ),
trường `type` KHÔNG được so sánh ở ĐÂU CẢ — sai type 10% mất ĐÚNG 0,00 điểm.
Dưới overlap_type, sai 10% type mất 12,35 điểm (sd ±0,82).
BTC KHÔNG công bố quy tắc căn chỉnh (ADR 0002: hộp đen vĩnh viễn).
⇒ Số chính thức nội bộ KHÔNG BAO GIỜ thưởng cho việc sửa type. ĐỪNG kết luận
  "type không đáng làm". Làm type cho đúng dù nội bộ đo thấy nó miễn phí.

## Ba quyết định đã chốt — đọc ADR, ĐỪNG mở lại
Q1 tty thuốc: TẠM CHỐT `IN` (ADR 0001 bản 3); lựa chọn khi NỘP còn chờ Probe B.
   Bằng chứng: gold của đội 100% IN, 220/220 RxCUI ở mức IN. Trần ảnh hưởng ~1,1 điểm.
   PHẢI tham số hoá target_tty trong configs/, KHÔNG hard-code.
Q2 c_i là hộp đen, BTC không công bố (ADR 0002). Giải bằng ĐO, không bằng hỏi.
   Scorer phải VĨNH VIỄN báo cả ba cách đọc.
Q3 Dữ liệu bạc GPT-4o HỢP LỆ (ADR 0003) — chỉ ở build-time.

## Đã có sẵn — DÙNG, đừng viết lại
src/smart_medic/eval/scoring.py (451 dòng, 3 cách đọc × 4 alignment, 8 self-test) ·
tests/test_offsets.py · tests/test_scoring.py · tests/data_test_manifest.json ·
.claude/settings.json (2 hook) · .claude/agents/{span-eval,kb-linker,probe-builder} ·
.claude/commands/score.md (/score) · data/output/ (100 file baseline, offset sạch) ·
scripts/analysis/{measure_data,leverage_map}.py · docs/decisions/ (3 ADR) ·
data/generated_medical_records/ (543 bạc + 162 GOLD, 0 lỗi offset/schema trên gold) ·
8 thư mục layer đã có __init__.py và README.md.
CHƯA CÓ: mọi file .py trong io/ layout/ extract/ assertion/ linking/ decision/
validate/, configs/*.yaml, resources/*.yaml, pyproject.toml, Makefile.

## Việc đầu tiên của bạn — theo thứ tự, KHÔNG đảo
1. Đọc 5 tài liệu ở trên; chạy 4 lệnh ở trên.
2. Báo cáo: bạn hiểu gì về ngân sách 70,00 điểm, bản đồ đòn bẩy, và rủi ro
   type-alignment. Nêu recall span hiện tại và bạn định đo nó trên test thế nào.
   DỪNG Ở ĐÂY, chờ tôi xác nhận.
3. Sau xác nhận: mở cửa sổ agent mới cho P0 (prompt ở tab 07 §C), và song song
   dựng Probe A.

ĐỪNG viết code trước khi báo cáo cho tôi.
```
