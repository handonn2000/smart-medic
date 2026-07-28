# Silver 100 file — cần làm gì (2026-07-27)

## Chặn trước: `data/dev_gold/` chưa phân xử

`diff -rq data/dev_gold data/dev_gold_consensus` → giống hoàn toàn. Nghĩa là gold
hiện tại = **giao của hai model** (689 mention), 314 mục trong
`data/dev_adjudication.json` vẫn chưa ai đọc, và 96 span mà chỉ một model bắt được
(`opus_only` 71 + `sonnet_only` 25) đang **vắng khỏi gold**.

Việc này chặn silver vì hai lẽ:

1. `train_ner.py --gold data/dev_gold` **ghi đè** silver ở file trùng tên
   (`load_dataset`: "thư mục SAU thắng"). Gold là nhãn thật cho 20/100 file train.
2. §4c dùng chính `data/dev_gold` làm thước đo "v4 > v3". Thước đo lệch thì kết luận lệch.

Gold hiện tại lệch về **precision** đúng cái hướng ngược với vấn đề đã đo
(recall 41–46% vs precision 74–97%). Giao hai model bỏ 9.6% span; train trên đó
là dạy model dè dặt hơn nữa.

## Ba điều đo được về silver

### 1. Chỉ cần 80 file, không phải 100 — tiết kiệm 20%

`data/silver_prompts/` có file 1–100, và cả 20 file dev đều nằm trong đó.
`load_dataset([silver, gold])` cho gold thắng ở mọi file trùng, nên nhãn silver của
20 file đó **bị bỏ hoàn toàn**. Chạy LLM cho chúng là công toi.

→ Chạy 80 file: `{1..100} \ {1,3,4,5,6,7,8,10,12,14,16,17,21,25,26,27,31,42,54,94}`

### 2. Train chỉ dùng `position` + `type`

`encode_document()` đọc `record["position"]` và `record["type"]`, hết.
`bio_labels()` chỉ sinh `O` + `B-/I-` cho 5 ConceptType. **`candidates` và
`assertions` của silver không đi vào training một bit nào.**

Hệ quả: chất lượng silver chỉ cần đúng ở *ranh giới span* và *nhãn loại* — phần
dễ hơn. Mã ICD/RxCUI sai trong silver không ảnh hưởng model. Có thể dùng model
rẻ hơn cho silver mà không mất gì cho §4.

(Ngược lại: `candidates` chiếm trọng số 0.4 lúc chấm, nhưng phần đó do KB +
`stages/` lo, không phải model NER.)

### 3. §4c đo trên chính dữ liệu train

`data/test/` = 100 file, `data/silver_prompts/` = cùng 100 file đó, `data/dev_gold/`
= 20 file trong số đó. Silver là pseudo-label cho chính tập test.
`train_ner.py` **không tách holdout** (không có split, không eval trên tập riêng).

Nên "v4 > v3 trên gold" ở §4c là so sánh không công bằng: v4 đã train trên đúng 20
file gold đó, v3 thì không. Số sẽ lạc quan, có thể chỉ là ghi nhớ.

→ Cách sửa rẻ: train với `--gold` trỏ vào thư mục chỉ có 14/20 file gold, giữ 6 file
làm holdout, rồi chấm v3 và v4 trên 6 file đó. Kém chính xác hơn nhưng trung thực.

## Merge self-consistency: 2/3 thay vì 3/3

TODO §3 gợi ý "giữ span mà cả 3 lần đều đồng ý". Với số đã đo thì nên là **đa số 2/3**:

- Giao 2 model đã bỏ 96/1003 span (9.6%). Giao 3 model sẽ bỏ nhiều hơn nữa.
- Nút thắt đã đo là **recall**, và `--unmatched zero` xác nhận mention thiếu bị phạt.
- Silver có nhiệm vụ dạy model *chỗ nào có mention*. Nhãn giao-ba-lần cho precision
  cao/recall thấp, dạy đúng cái tật đang có.

Đa số 2/3 vẫn lọc được nhiễu (một model sai lẻ bị loại) mà không cắt recall.

Dùng **ba model khác họ** thay vì lặp một model ba lần — cùng model sai giống nhau
ba lần, không lọc được lỗi hệ thống. Đã kiểm: `claude-opus-5`, `claude-sonnet-5`,
`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` đều nhận task này.
`claude-fable-5` **từ chối** (`stop_reason=refusal`, 20/20, ổn định) — không dùng được.

## Chi phí đo được (80 file × 3 model)

| | input | output | thời gian |
|---|---|---|---|
| 1 lượt 80 file | ~174k token | ~269k token | ~30 phút |
| 3 model | ~522k token | ~807k token | ~90 phút |

System prompt giống nhau toàn bộ 100 file (2821 ký tự) nên prompt cache ăn từ file
thứ hai. `max_tokens=32768` bắt buộc — thinking chiếm 70–87%.

## Thứ tự

1. **Phân xử 314 mục** → `data/dev_gold/` chốt. Ưu tiên 96 span một-model-bắt
   (đây là phần recall) và 84 mục lệch mã.
2. Tách 6 file gold làm holdout.
3. Fan-out 80 file × 3 model → `data/silver_responses_{tag}/`.
4. Ingest từng lượt, **kiểm cột `drop`** (§3c). Drop cao ở nhiều file = dừng, đừng train.
5. Merge đa số 2/3 → `data/silver/`.
6. Train, rồi chấm v3 vs v4 trên 6 file holdout.
