# L7 · `eval/` — phép đo, ngoài đường suy luận

Layer duy nhất **không** nằm trên đường suy luận. Nó đọc JSON từ đĩa, không import bất kỳ
layer nào khác. Nhờ vậy, chấm điểm không bao giờ có thể ảnh hưởng tới cái được chấm.

`scoring.py` là phần **duy nhất của pipeline đã hoàn thành** — 451 dòng, 3 cách đọc × 4
chế độ căn chỉnh, 8 self-test. **Dùng nó, đừng viết lại.**

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
#   alignment   ∈ {greedy_iou, overlap, overlap_type, exact}
#   aggregation ∈ {matched, penalised, docbag}
#   cand_formula∈ {official, plain}

align(gold, pred, mode) -> (pairs, unmatched_gold, unmatched_pred)
#   xác định hoàn toàn (−IoU → chỉ số gold → chỉ số pred)
#   ⚠ greedy_iou KHÔNG so `type` ở bất cứ đâu — gốc của rủi ro type-alignment

score_corpus(docs, cfg) -> {text_score, assertions_score, candidates_score,
                            final_score, leaderboard, missing, spurious, per_doc}
#   docs = [(key, gold_list, pred_list)] · macro theo tài liệu, không micro theo entity

diagnostics(docs) -> strict/relaxed F1 theo type · boundary_errors 7 kiểu ·
                     boundary_delta_median · tp/fp/fn từng cờ · code_accuracy ·
                     type_confusions
#   LUÔN greedy_iou cứng trong code — đọc như chẩn đoán, không như điểm

load_dir(d) -> dict[str, list]      # chỉ nhận JSON là list ⇒ sidecar tự bị loại
```

## Số chính thức nội bộ

**`penalised / greedy_iou`, dạng `/100`, 2 chữ số thập phân.**

`matched` **suy biến**: xoá 30% dự đoán của chính mình làm `matched` **tăng** nhẹ
(70,00 → 69,96) còn `penalised` rơi 70,00 → 49,14. Cải thiện `matched` mà `penalised`
không nhúc nhích là **lách metric** — nói thẳng ra.

Nhưng số chính thức phải là một **cặp**: `greedy_iou` không so `type`, nên nó **không bao
giờ thưởng** cho việc sửa type, trong khi dưới `overlap_type` sai 10% type mất ~14 điểm
(sd ±6). ⇒ `overlap_type` là **cột chặn**: thay đổi chỉ được nhận nếu không làm nó giảm
quá 0,010.

Cột `exact` là **đèn báo bug offset**: lệch span đúng một ký tự cho 0,00 điểm. Nếu `exact`
sụt về gần 0 mà hai cột kia bình thường ⇒ **bug offset**, không phải khoảng trống mô hình.

## Bar nghiệm thu cho mọi delta

```
Δ > max(0,010 ; 1,96·SE_bootstrap)   và   CI95 không chứa 0
```

Paired bootstrap B = 10.000, resample **theo tài liệu**, ghép cặp trên cùng tập tài liệu.

Sàn 0,010 **chỉ** hợp lệ cho cặp hệ thống *tương quan cao*. Hai hệ thống bỏ sót entity ở
những chỗ **khác nhau** không phân biệt được dưới ~0,8 điểm (SE đo được 0,415), kể cả khi
tỷ lệ bỏ sót y hệt. Báo nhiều lát thì hiệu chỉnh FDR (Benjamini–Hochberg, q = 0,10).

## File

| File | Trạng thái | Phase |
|---|---|---|
| `scoring.py` | ✅ 451 dòng, 8 self-test | — |
| `slices.py` — bảng lát cắt bắt buộc kèm `n` và MDE | ⬜ | P2 |
| `bootstrap.py` — paired bootstrap + CI | ⬜ | P2 |
| `probe.py` — sinh biến thể probe từ một tập dự đoán | ⬜ | P2 |

## Bất biến

- **Không import layer nào khác.** `eval/` đọc JSON trên đĩa.
- Chạy `pytest tests/test_offsets.py -q` **trước** mọi phép chấm. Điểm trên offset đã lệch
  còn tệ hơn không có điểm.
- Báo **cả ba** chế độ căn chỉnh mỗi lần chạy, không có ngoại lệ.
