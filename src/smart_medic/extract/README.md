# L3 · `extract/` — span + type · ≈60,00 ĐIỂM

**Layer lớn nhất của dự án.** Một entity bị bỏ sót nhận **0 ở cả ba số hạng cùng lúc**
dưới cách đọc `penalised` — nên `extract/` không sở hữu 30 điểm như bản kế hoạch đầu
ghi, mà **≈60 trong 70,00**.

Đo trên gold 162 file, bỏ ngẫu nhiên 10% entity: `text` −2,99 · `assertions` −2,99 ·
`candidates` −1,00. 43% thiệt hại rơi vào `text`, 43% vào `assertions`, 14% vào
`candidates`.

**Thực trạng:** `data/output/` trích 15,8 entity/file; gold có 45,9/file. Thiếu 2,9×.

## Hai làn, thứ tự cứng

```
LÀN R · SÀN RECALL                        LÀN M · MODEL
không model · không train                 encoder ≤9B, ngưỡng THÔ 0,15
chạy được ngay ở P1                       cần checkpoint
recall KHÔNG BAO GIỜ tụt                  recall phụ thuộc train
        │                                          │
        └──────────────┬───────────────────────────┘
                       ▼
              overlap_graph.py   (hợp nhất, KHÔNG dùng ngưỡng IoU≥0,5)
                       ▼
              boundary.py        (trung vị biên có trọng số)
                       ▼
              harmonize.py       (CHỈ THUỐC↔TÊN_XÉT_NGHIỆM, đa số ≥4)
```

**Làn R đứng trước làn M** vì nó là thứ duy nhất trong dự án có recall không phụ thuộc
checkpoint, và vì nếu hết thời gian thì nó *là* bài nộp.

## Hợp đồng

```python
extract.recall_floor(doc, layout)  -> list[Span]   # làn R
extract.propose(doc, layout)       -> list[Span]   # làn M, ngưỡng THÔ 0,15
extract.merge_graph(spans, doc)    -> list[Span]   # gán cluster_id, không lồng nhau
extract.harmonize(spans, doc)      -> list[Span]

@dataclass
class Span:
    start: int; end: int
    type_dist: dict[str, float]    # PHÂN PHỐI, không phải str
    score: float                   # P(là entity) — decision/ áp ngưỡng, KHÔNG phải ở đây
    source: str                    # "aho" | "labvalues" | "kvspan" | "xlmr" | "gliner"
    cluster_id: int | None
```

## Bốn quyết định đã đo

1. **BỎ ngưỡng IoU ≥ 0,5 khi hợp nhất.** Đo được: nó loại **54,2%** biến thể ranh giới,
   **85,7%** với span 1 từ — mà 37,8% gold span dài đúng 1 từ. Thay bằng: cạnh khi chồng
   lấn ký tự > 0, cụm bằng thành phần liên thông (union-find) hoặc Leiden, cộng ràng buộc
   **không lồng nhau** (hợp lệ: 0/7.435 gold span lồng nhau).
2. **Biên lấy TRUNG VỊ có trọng số, không phải trung bình.** Chi phí WER là L1 ⇒ ước
   lượng tối ưu là trung vị.
3. **Hài hoà type CHỈ cặp THUỐC ↔ TÊN_XÉT_NGHIỆM, đa số ≥4 và tỷ lệ ≥4.** Hài hoà vô
   điều kiện tốn 0,00 dưới `greedy_iou` nhưng **1,13** dưới `overlap_type`. 61/64 xung
   đột là CHẨN_ĐOÁN ↔ TRIỆU_CHỨNG — đó là phân biệt **hợp lệ theo vị trí**, hài hoà nó
   là xoá thông tin thật.
4. **Type là argmax, KHÔNG hedging.** Phát hai type cho một span tốn 1,29 điểm dưới
   *cả hai* chế độ căn chỉnh.

## Bất biến

- **Không áp ngưỡng ở đây.** Trả `type_dist` + `score`; `decision/emit.py` quyết định phát
  hay bỏ.
- Không dùng model tokenizer mức *word* — nó phá offset. Mức âm tiết/ký tự, và luôn
  `return_offsets_mapping=True`.
- Không dùng LLM sinh làm bộ trích xuất span chính: encoder 209M thắng nó và cho offset
  chính xác theo cấu tạo.

## File

| File | Làn | Trạng thái | Phase |
|---|---|---|---|
| `aho.py` | R — Aho–Corasick, 14,7k tên ICD + ~22k tên IN/PIN/MIN | ⬜ | P1 |
| `labvalues.py` | R — regex dòng xét nghiệm (41,7% entity là 2 loại XN) | ⬜ | P1 |
| `kvspan.py` | R — mẫu `TÊN: giá trị` | ⬜ | P1 |
| `globalpointer.py` | M — XLM-R-base + Efficient GlobalPointer, W=30 | ⬜ | P3 |
| `gliner.py` | M — GLiNER-multi 209M (ensemble, chỉ nếu còn thời gian) | ⬜ | P3 |
| `overlap_graph.py` | hợp nhất trên đồ thị chồng lấn | ⬜ | P3 |
| `boundary.py` | trung vị biên có trọng số | ⬜ | P3 |
| `harmonize.py` | hài hoà type có ngưỡng | ⬜ | P6 |
| `semicrf.py` | **HOÃN** — nhắm 6,96 điểm ranh giới, ngoài đường tới hạn | — | — |

## Cái bẫy của layer này

**Sinh thừa gần đắt bằng bỏ sót.** Đường cong đo được: +10% span thừa −6,10 · +20%
−11,24 · +30% −15,60 · +50% −22,59. Tỷ giá `c_fn/c_fp = 1,14` ⇒ **không** phải "recall
bằng mọi giá": bỏ 30% + thêm 30% rác = 42,58, thấp hơn bỏ 30% thuần (49,45) tới 6,87 điểm.

## Nghiệm thu

- `pytest tests/test_offsets.py -q` sạch; `text == raw[start:end]` byte-exact 100/100.
- recall span trên gold ≥ 0,70 (đo bằng `eval/scoring.py`, không bằng cảm nhận).
- `penalised/greedy_iou` tăng ≥ +15,00 so với baseline `data/output/`.
- `overlap_type` **không** giảm quá 0,010 so với baseline.
- Bảng lát cắt thể loại × type kèm `n`; không lát nào (n ≥ 30 tài liệu) tụt.
