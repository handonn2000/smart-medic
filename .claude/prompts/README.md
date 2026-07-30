# `.claude/prompts/` — prompt thực thi từng phase

Mỗi phase chạy trong **một cửa sổ agent mới**. Mỗi file dưới đây **tự đứng được**: HEADER CHUNG
(ngân sách điểm, 4 ràng buộc cứng, bản đồ đòn bẩy, cách đo) đã được nhúng sẵn ở đầu, nên dán
nguyên một file là đủ — không cần ghép thêm gì.

## Cách dùng

1. Mở cửa sổ agent mới.
2. Dán nguyên nội dung `pN_prompt.md`.
3. Agent tự kiểm **tiền đề** trước khi viết code — mọi prompt mở đầu bằng khối `KIỂM TIỀN ĐỀ`
   và **dừng lại** nếu tiền đề chưa thoả. Đừng bảo nó bỏ qua bước đó.
4. Agent dừng ở **điểm dừng báo cáo** cuối prompt và chờ bạn xác nhận.

## Thứ tự và phụ thuộc

| File | Phase | Nội dung |
|---|---|---|
| [`p0_prompt.md`](p0_prompt.md) | **P0** | NỀN MÓNG & CỔNG SỐNG CÒN |
| [`p1_prompt.md`](p1_prompt.md) | **P1** | ĐƯỜNG LÙI TỐI THIỂU — sàn recall không model |
| [`p2_prompt.md`](p2_prompt.md) | **P2** | HIỆU CHUẨN HỘP ĐEN — 3 probe + hạ tầng đo |
| [`p3_prompt.md`](p3_prompt.md) | **P3** | RECALL SPAN — đòn bẩy lớn nhất dự án |
| [`p4_prompt.md`](p4_prompt.md) | **P4** | ASSERTIONS — đồ thị phạm vi |
| [`p5_prompt.md`](p5_prompt.md) | **P5** | CANDIDATES + TẦNG KIỂM CHỨNG CẠNH |
| [`p6_prompt.md`](p6_prompt.md) | **P6** | LỚP QUYẾT ĐỊNH & HIỆU CHUẨN |
| [`p7_prompt.md`](p7_prompt.md) | **P7** | TÁI LẬP & NỘP BÀI |

Phụ thuộc: `P0 → P1 → P2 → P3 → {P4, P5} → P6 → P7`.
**P2 chỉ cần P0** (probe chạy được bằng `data/output/` hiện có — đừng đợi có extractor tốt).
Hai cổng cứng: **Probe A ≥ 25** để khởi động P3, và **recall ≥ 0,65** để khởi động P4.
Đồ thị đầy đủ + tiêu chí nghiệm thu: [`plan-v4.html`](../../docs/reports/plan-v4.html) tab 04.

[`kickoff_prompt.md`](kickoff_prompt.md) không phải phase — dùng một lần khi ai đó tiếp quản
toàn bộ dự án.

## Nguồn

Sinh từ `docs/reports/plan-v4.html` tab 07. **Plan là nguồn chân lý**; nếu sửa prompt thì sửa
ở cả hai chỗ, đừng để hai bản trôi khỏi nhau.
