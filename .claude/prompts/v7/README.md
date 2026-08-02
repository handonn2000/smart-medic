# Prompt triển khai — kế hoạch v7.1 (synth corpus + tagger lai)

Bảy prompt tự chứa, mỗi prompt cho một phase. Agent thực thi đọc prompt + các
file nó chỉ tới là đủ làm, không cần đọc lại lịch sử hội thoại.

**Nguồn chuẩn là [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.**
Các file ở đây là bản sao để tiện copy — sửa ở tài liệu trước rồi đồng bộ sang,
đừng để hai phía trôi khỏi nhau.

| # | file | nội dung | thời lượng |
|---|---|---|---|
| 0 | [`00-eval-harness.md`](00-eval-harness.md) | Hạ tầng đánh giá | 0,5 ngày |
| 1 | [`01-labtest-rules.md`](01-labtest-rules.md) | Nhánh xét nghiệm bằng luật | 1,5 ngày |
| 2 | [`02-synth-corpus.md`](02-synth-corpus.md) | Bộ sinh corpus | 3 ngày |
| 3 | [`03-tagger.md`](03-tagger.md) | Tagger XLM-R | 2 ngày |
| 4 | [`04-arbiter.md`](04-arbiter.md) | Arbiter + lai | 1,5 ngày |
| 5 | [`05-select-config.md`](05-select-config.md) | Chọn cấu hình nộp | 1 ngày |
| 6 | [`06-packaging.md`](06-packaging.md) | Đóng gói tái lập | 1 ngày |

## Hai loại cổng — đọc trước khi chạy prompt nào

| | **cổng CHẶN** | **cổng ĐỊNH TUYẾN** |
|---|---|---|
| hỏi gì | *code có đúng không?* | *thành phần này có đáng ship không?* |
| không đạt = | **có bug** → sửa rồi chạy lại | **có số đo** → ghi lại, tắt cờ, **đi tiếp** |
| làm dừng phase? | có | **không bao giờ** |

Không phase nào có tiêu chí dừng. Thành phần không qua cổng định tuyến vẫn
được xây, test và commit — chỉ là cờ trong `data/curated/pipeline.v1.yaml`
mặc định `false`. Phase 5 bật/tắt các cờ để chọn cấu hình nộp.

## Ba điều cấm xuyên suốt

1. **`gold_real` không bao giờ là NGUỒN** — không lấy phân bố, không lấy hạt
   giống, không chọn epoch, không dò ngưỡng. Nó chỉ là cổng.
2. **Không gọi LLM lúc build** — sinh một lần, đóng băng, commit kèm `sha256`.
3. **Không công bố số không có khoảng tin cậy** trên n = 9 tài liệu.

Danh sách đầy đủ 12 quy tắc: tài liệu nguồn §5.
