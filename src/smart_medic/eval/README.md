# L7 · `eval/` — phép đo, ngoài đường suy luận

Layer duy nhất **không** nằm trên đường suy luận. Nó đọc JSON từ đĩa, không import bất kỳ
layer nào khác. Nhờ vậy, chấm điểm không bao giờ có thể ảnh hưởng tới cái được chấm.

`scoring.py` cài **đúng đặc tả chính thức của BTC** (sửa 30/07/2026) — 3 cách đọc × 4 chế độ
căn chỉnh, 12 self-test. **Dùng nó, đừng viết lại.**

## Chạy

```bash
PYTHONPATH=src python3 -m smart_medic.eval.scoring --pred data/output --gold <gold_dir> --json
PYTHONPATH=src python3 -m smart_medic.eval.scoring --pred data/output --describe   # không cần gold
```

Hoặc dùng lệnh `/score` — nó chạy cổng offset trước, rồi chấm.

## API

```python
MetricConfig(alignment, aggregation, cand_formula, clamp_text, doc_aggregation)
#   frozen · .hash() 12 ký tự — GHIM hash vào mọi manifest, nó là danh tính của phép đo
#   MẶC ĐỊNH = ĐẶC TẢ CHÍNH THỨC. Đổi một trường là số đó không còn chính thức.
#   alignment   ∈ {overlap_type (mặc định), greedy_iou, overlap, exact}
#   aggregation ∈ {penalised (mặc định), matched, docbag}
#   cand_formula∈ {official (mặc định, có trọng số W_i), plain (không trọng số)}
#   clamp_text   = False (mặc định) — đặc tả KHÔNG có max(0, 1−WER)

align(gold, pred, mode) -> (pairs, unmatched_gold, unmatched_pred)
#   xác định hoàn toàn (−IoU → chỉ số gold → chỉ số pred)
#   ⚠ greedy_iou KHÔNG so `type` ở bất cứ đâu ⇒ CHỈ dùng làm chẩn đoán.
#     Đặc tả: sai loại ⇒ tính 2 lần, mỗi lần 0 điểm cả 3 metric ⇒ overlap_type.

score_corpus(docs, cfg) -> {text_score, assertions_score, candidates_score,
                            final_score, leaderboard, missing, spurious, per_doc}
#   docs = [(key, gold_list, pred_list)] · macro theo TÀI LIỆU, không micro theo entity
#   text/assertions là trung bình thường; candidates có TRỌNG SỐ theo W_i

score_document(gold, pred, cfg) -> {text, assertions, candidates, cand_weight, ...}
#   cand_weight = W_i = Σ_k(len(gold_codes(k))+1) — chỉ đọc gold, nên hai hệ chấm
#   trên cùng gold luôn dùng chung trọng số (điều làm paired bootstrap hợp lệ)

diagnostics(docs) -> strict/relaxed F1 theo type · boundary_errors 7 kiểu ·
                     boundary_delta_median · tp/fp/fn từng cờ · code_accuracy ·
                     type_confusions
#   LUÔN greedy_iou cứng trong code — đọc như chẩn đoán, không như điểm

load_dir(d) -> dict[str, list]      # chỉ nhận JSON là list ⇒ sidecar tự bị loại
```

## Số chính thức

**`penalised / overlap_type`, dạng `/100`, 2 chữ số thập phân. Trần = 100,00.**

BTC đã công bố đủ công thức (30/07/2026, xem ADR 0002 §"Đặc tả CHÍNH THỨC"):

```
text_score       = Σ_i (1 − WER(i)) / len(test)
assertions_score = Σ_i J_assertions(i) / len(test)
candidates_score = Σ_i J_candidates(i)·W_i / Σ_i W_i     W_i = Σ_k(len(gt(k))+1)
```

`i` là **một tài liệu**, `k` là một khái niệm trong đó. Ba điều từng đoán sai, nay đã sửa:

1. **`+1` là TRỌNG SỐ TÀI LIỆU, không phải mẫu số.** Nó không vào trong `J` nên **không
   chặn gì** — dự đoán hoàn hảo đạt 1,0 ở candidates, không phải 0,2501. Cách đọc cũ
   (`Σ|gt∩pred| / Σ(len(gt)+1)`) trả về **đúng 0,00** khi dự đoán không mang mã nào, và đó
   là lý do một bài nộp thật sự được 41,68 lại bị báo là 0,00 — **lệch 16,53 điểm**.
2. **Căn chỉnh CÓ so `type`.** Đặc tả: đúng text mà sai loại ⇒ *"tính 2 lần, mỗi lần 0 điểm
   với cả 3 loại metric"*. Sai type bị phạt **hai lần**. ⇒ `overlap_type`, không `greedy_iou`.
3. **`1 − WER(i)` KHÔNG chặn ở 0.** WER không chặn trên, nên một tài liệu có thể âm.

`greedy_iou` giờ **chỉ là chẩn đoán**: nó không so `type` nên không bao giờ cho thấy việc
sửa type đáng bao nhiêu. Hiệu số `greedy_iou − overlap_type` **chính là** giá của lỗi type.

`matched` **suy biến**: xoá 30% dự đoán của chính mình làm nó *tăng*. Chỉ dùng làm trần.
Cải thiện `matched` mà `penalised` không nhúc nhích là **lách metric** — nói thẳng ra.

Cột `exact` là **đèn báo bug offset**: lệch span đúng một ký tự cho 0,00 điểm. Nếu `exact`
sụt về gần 0 mà hai cột kia bình thường ⇒ **bug offset**, không phải khoảng trống mô hình.

`tests/test_alignment_parity.py` biến quy tắc "không làm `overlap_type` giảm quá 0,010"
thành lỗi build, và chứng minh nó chặn được một thay đổi xấu biết trước.

## Bar nghiệm thu cho mọi delta

```
Δ > max(0,010 ; 1,96·SE_bootstrap)   và   CI95 không chứa 0
```

Paired bootstrap B = 10.000, resample **theo tài liệu**, ghép cặp trên cùng tập tài liệu
(`bootstrap.py --calibrate` in bốn ca hiệu chuẩn cạnh giá trị tham chiếu).

Sàn 0,010 **chỉ** hợp lệ cho cặp hệ thống *tương quan cao*. Hai hệ thống bỏ sót entity ở
những chỗ **khác nhau** không phân biệt được dưới **~1,04 điểm** (SE đo được 0,531 dưới
công thức đã sửa), kể cả khi tỷ lệ bỏ sót y hệt. Báo nhiều lát thì hiệu chỉnh FDR
(Benjamini–Hochberg, q = 0,10).

## File

| File | Trạng thái | Phase |
|---|---|---|
| `scoring.py` | ✅ sửa theo đặc tả chính thức 30/07, 12 self-test | — · **P2** |
| `slices.py` — bảng lát cắt bắt buộc kèm `n` và MDE | ✅ 4 trục, 60 lát | P2 |
| `bootstrap.py` — paired bootstrap + CI | ✅ 4 ca hiệu chuẩn tái lập | P2 |
| `probe.py` — sinh biến thể probe từ một tập dự đoán | ✅ A · A′ · B (C chờ P4) | P2 |

## Bất biến

- **Không import layer nào khác.** `eval/` đọc JSON trên đĩa.
- Chạy `pytest tests/test_offsets.py -q` **trước** mọi phép chấm. Điểm trên offset đã lệch
  còn tệ hơn không có điểm.
- Báo **cả ba** chế độ căn chỉnh mỗi lần chạy, không có ngoại lệ.
