# Phase 6 — đóng gói tái lập

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **1 ngày** · Tiền đề: **Phase 5**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §4 Phase 6, và PRD tab 01 mục 5
("Nếu BTC không cài đặt lại được source code của nhóm → nhóm thi sẽ bị loại").

Tình trạng hiện tại: pyproject.toml CỐ Ý tách torch (~1GB) khỏi dependency lõi;
image runtime chỉ mang nhánh từ vựng. Phase 3–4 phá ranh giới đó.

Việc:
1. Thêm optional-dependency group "train" (torch, transformers) — CHỈ image
   builder dùng. Không đưa vào dependency lõi.
2. stages/tagger.py: import torch bên trong hàm, không ở top-level. Thiếu torch
   → trả rỗng, pipeline chạy tiếp bằng proposer luật (degrade, không crash).
   Đây là fallback offline mà PRD §8 khuyến nghị.
3. Weights vào data/artifacts/tagger/v1/ kèm sha256, revision base model, seed.
   Đóng gói trong bài nộp. KHÔNG tải lúc chạy (quy tắc 3: không gọi mạng).
4. Chạy thử trong container sạch. Tiền lệ: chính việc này đã lộ 3 bug mà máy dev
   không bao giờ thấy.
5. README cài đặt từ máy sạch, có mục riêng "chạy khi không có torch".

CỔNG CHẶN — đây là phase duy nhất mà không đạt = BỊ LOẠI KHỎI CUỘC THI, nên
KHÔNG nới: container sạch, ngắt mạng, `smk solve` ra đủ 100 file đúng định dạng
— kiểm CẢ HAI trường hợp: có nhóm "train" và không có.

Ngưỡng này dễ đạt hơn nó nghe: nếu Phase 5 chọn C0 thì torch không nằm trên
đường chạy nào, và cổng thu về đúng trạng thái repo hiện tại.
