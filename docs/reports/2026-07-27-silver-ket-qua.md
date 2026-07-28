# Silver 80 file — triển khai xong (2026-07-27)

## Đã làm

Fan-out `data/silver_prompts` qua **ba model độc lập**, hợp nhất bằng **bầu đa số 2/3**,
ghi vào `data/silver/`. Bỏ toàn bộ 20 file dev (loader override bằng gold nên chạy là lãng phí).

| lượt | model | span sau ingest | drop |
|---|---|---|---|
| 1 | `claude-opus-5` | 2.607 | 0 |
| 2 | `claude-sonnet-5` | 2.455 | 2 (file 71, sai type) |
| 3 | `claude-opus-4-8` | 2.320 | 2 (file 35, 56 — không định vị) |

Drop tổng 4/7.382 = 0,05%. §3c yêu cầu điều tra nếu drop tập trung — ở đây rải đều, không hệ thống.

**Một sự cố đã xử lý:** lượt sonnet-5 lần đầu bị cắt giữa dòng ở file 87 (`truncated_prefix`,
mất 30 span). Chạy lại riêng file đó → 25 span, `stop_reason=end_turn`, sạch.

## Kết quả bầu phiếu

| | span | |
|---|---|---|
| cả 3 lượt đồng ý | 2.128 | 76,7% union |
| 2/3 lượt đồng ý | 350 | 12,6% |
| chỉ 1 lượt → loại | 298 | 10,7% |
| **giữ lại** | **2.478** | **89,3%** |

108 cụm span có ≥2 lượt đồng ý về *sự tồn tại* nhưng khác *type* — bầu theo đa số type.

`validate_file` sạch 80/80: không lỗi schema, không lệch offset.

## So với gold đã phân xử

Bạn đã phân xử `data/dev_gold` (979 span, mtime 18:07): thêm 33 span không có trong
`dev_gold_prefill`, bỏ 57, sửa candidates/assertions ở 56 mục. Nút chặn tôi nêu trong memo
trước đã được giải.

| | gold (20 file) | silver (80 file) |
|---|---|---|
| span | 979 | 2.478 |
| span/1.000 ký tự (median) | 17,2 | 14,8 |
| lặp (text,type) | 43,1% | 49,5% |

Mật độ silver thấp hơn gold 14% — đây là cái giá của bầu 2/3 (loại 298 span chỉ một model
thấy). Phân bố type lệch rõ: silver nhẹ `CHẨN_ĐOÁN` (22,2% vs 28,8%) và nặng
`KẾT_QUẢ_XÉT_NGHIỆM` (12,3% vs 6,4%). Nếu train ra model thiên về xét nghiệm và yếu chẩn đoán
thì nguyên nhân nằm ở đây, không phải ở hyperparameter.

## Holdout cho §4c

`train_ner.py` không tách holdout, còn §4c đo trên chính file đã train — gate "bản mới thắng
bản cũ" vì thế lạc quan. Đã tách:

- `data/dev_gold_train/` — 14 file, 739 span
- `data/dev_gold_holdout/` — 6 file (4, 12, 21, 31, 54, 94), 240 span

Silver không giao holdout (silver đã bỏ hết 20 file dev), nên holdout sạch tuyệt đối.

## Bước tiếp

1. Train: `data/silver/` + `data/dev_gold_train/`, eval trên `data/dev_gold_holdout/`.
2. Chỉ khi holdout thắng mới train lại trên toàn bộ 20 file gold để nộp.
3. `train_ner.py` chỉ học `position` + `type` — sai mã trong silver vô hại với train,
   nhưng vẫn ảnh hưởng nếu bạn dùng silver cho phần candidates.
