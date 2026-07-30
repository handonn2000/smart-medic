# ADR 0006 — Gold gán mã cho TRIỆU_CHỨNG: **bật mã cho cả ba loại**

- **Trạng thái:** ĐÃ QUYẾT
- **Ngày:** 2026-07-31
- **Ảnh hưởng:** `io/labels.py` · `decision/emit.py` · `configs/pipeline.yaml`
- **Đảo lại:** quyết định tắt `CHẨN_ĐOÁN` ở commit `cfe764c` (30/07 22:11)

## Bối cảnh

Commit `cfe764c` tắt mã CHẨN_ĐOÁN với lý do: lần nộp C (948 mã, 764 mã chẩn đoán) cho
21,5945 điểm, thấp hơn lần nộp B (228 mã thuốc) 1,63 điểm. Kết luận ghi lại là *"gold của
test không gán mã cho CHẨN_ĐOÁN"*.

Kết luận đó dựa trên một phép so sánh bị nhiễu, và hai cách đọc độc lập từ chính
leaderboard nói ngược lại.

## Bằng chứng 1 — lần nộp C không phải "B cộng mã chẩn đoán"

`text` và `J_assertion` **không phụ thuộc** vào trường `candidates`. Một thí nghiệm chỉ
thêm mã bắt buộc phải để nguyên hai cột đó:

| | text | J_assertion | J_candidates |
|---|---|---|---|
| A · span+type, 0 mã | 26,6300 | 30,9496 | 11,0259 |
| B · A + 228 mã THUỐC | 26,6300 | 30,9496 | 14,8832 |
| C · đầy đủ 948 mã | 26,**8300** | 31,**2028** | 10,4617 |

A→B: hai cột đầu **không đổi một chữ số nào** — đây là một A/B sạch, và nó chứng minh
mã thuốc đáng +3,8573 trên J_candidates.

B→C: text +0,2000 và J_assertion +0,2532. **Tập span đã thay đổi.** C gộp bản sửa type
của P3 với mã chẩn đoán trong cùng một lần nộp. Quy toàn bộ −1,63 cho mã chẩn đoán là
gán một hiệu ứng hỗn nhiễu cho một nguyên nhân — đúng loại ngoại suy mà tab 09 của
plan-v4 được viết ra để cảnh báo. **Mã chẩn đoán chưa từng được đo cô lập.**

## Bằng chứng 2 — tỷ lệ triệt tiêu `m`, và nó chặn trên tỷ lệ gold có mã

Ở lần nộp A hệ phát `assertions: []` và `candidates: []` cho **toàn bộ** span. Khi đó,
với quy ước "cả hai rỗng ⇒ J = 1":

```
J_candidates = m · P(gold candidates rỗng | slot)
J_assertion  = m · P(gold assertions rỗng | slot)
```

`m` (tỷ lệ khái niệm gold được ghép) xuất hiện ở cả hai, nên **tỷ lệ của chúng không
phụ thuộc `m`** — không cần biết recall thật là bao nhiêu:

```
P(cand rỗng) / P(assert rỗng) = 11,0259 / 30,9496 = 0,356
P(assert rỗng) ≤ 1   ⇒   P(gold candidates rỗng | slot) ≤ 0,356
```

Mô phỏng trên `proxy_gold_test/` (20 file test thật gán nhãn tay, 724 span), trọng số
`W_i` tính đúng theo công thức chính thức:

| giả thuyết | P(cand rỗng) | tỷ lệ dự đoán | so với 0,356 |
|---|---|---|---|
| gold mã DX+THUỐC · scope tất cả khái niệm | 0,276 | **0,799** | cao gấp 2,2× |
| gold mã DX+THUỐC · scope chỉ loại có mã | — | **0,061** | thấp 5,8× |
| **gold mã DX+THUỐC+TRIỆU_CHỨNG · scope tất cả** | 0,137 | **0,407** | **lệch 1,14×** |

Giả thuyết thứ ba là giả thuyết duy nhất nằm gần con số đo được.

## Hai lời giải thích thay thế, đều đã loại

**"Proxy gold lệch tỷ lệ loại, không phải gold có thêm mã."** Nếu tỷ lệ 0,356 chỉ do tập
test thật có nhiều CHẨN_ĐOÁN/THUỐC hơn proxy đo được, thì cần tỷ lệ hai loại đó lên tới
~90% tổng số khái niệm. Quét toàn dải: 0,34 → 0,776 · 0,65 → 0,590 · 0,90 → 0,500 ·
0,95 → 0,485. **Ngay cả ở 95% vẫn không chạm 0,356.** Lệch tỷ lệ loại không thể là lời
giải thích, dù lệch đến mức phi lý.

**"Scorer chỉ chấm candidates trên các loại có mã."** Cách đọc này cho 0,061 — sai 5,8
lần theo chiều ngược lại. Loại.

## Quyết định

`CODEABLE_TYPES = {CHẨN_ĐOÁN, THUỐC, TRIỆU_CHỨNG}`, với
`max_candidates_per_type: {CHẨN_ĐOÁN: 1, THUỐC: 2, TRIỆU_CHỨNG: 1}`.
`linking/icd.py` phục vụ cả CHẨN_ĐOÁN và TRIỆU_CHỨNG — chương XVIII của ICD-10
(R00–R99, *"Triệu chứng, dấu hiệu và phát hiện bất thường"*) chính là một từ điển
triệu chứng, nên cùng một chỉ mục Việt–Việt trả lời được cả hai.

**Hai loại xét nghiệm vẫn giữ mã rỗng.** Chúng chiếm ~31% khái niệm gold và không có
bằng chứng nào cho thấy chúng được gán mã; đây cũng là chiều duy nhất mà một mã có thể
biến điểm đang có thành 0.

## Vì sao đây không phải canh bạc

Jaccard trên tập mã của một entity **đã ghép**:

| tình huống | J | ghi chú |
|---|---|---|
| gold có mã, ta bỏ trống | 0 | đang mất sẵn |
| gold có mã, ta đoán sai | 0 | không mất thêm gì |
| gold có mã, ta đoán đúng | **1** | được thêm |
| gold rỗng, ta bỏ trống | 1 | đang có sẵn |
| gold rỗng, ta phát mã | **0** | rủi ro duy nhất |

Span sinh thừa chấm 0 bất kể mang gì, nên mã trên span thừa là **miễn phí**. Toàn bộ rủi
ro nằm ở hàng cuối, và xác suất của nó bị chặn trên ở 0,320 — phần lớn trong đó là hai
loại xét nghiệm ta không gán mã. Điểm hoà: với độ chính xác `a`, phát mã có lãi khi tỷ lệ
gold có mã `c > 1/(1+a)`; ở `a = 0,61` (hit-rate đo trên gold tổng hợp) ngưỡng là 0,62,
còn tỷ lệ khớp với leaderboard là ~1,0.

## Điểm gold **giảm**, và điều đó đã được dự báo

| cấu hình | điểm gold tổng hợp | code hit-rate |
|---|---|---|
| CĐ 0 · THUỐC 2 · SYM 0 (trước) | 55,67 | 0,363 |
| CĐ 1 · THUỐC 2 · SYM 0 | **58,21** | 0,601 |
| CĐ 1 · THUỐC 2 · SYM 1 (chốt) | 53,31 | 0,609 |

Gold tổng hợp gán mã cho TRIỆU_CHỨNG ở tỷ lệ **0/1849 = 0,0%**. Trên corpus đó, mọi mã
triệu chứng ta phát đều biến một J=1 thành J=0, nên điểm **phải** giảm. Đây là hệ quả
tất yếu của giả thuyết, không phải bằng chứng chống lại nó.

Việc bật mã CHẨN_ĐOÁN (+2,54) được cả hai nguồn ủng hộ. Việc bật mã TRIỆU_CHỨNG chỉ
được leaderboard ủng hộ, và **leaderboard là thứ chúng ta bị chấm**. ADR này áp dụng
đúng bài học của chính dự án — *nhánh candidates chỉ nghiệm thu bằng leaderboard* — lần
này theo chiều mà gold nói "không" còn leaderboard nói "có".

## Cách bác bỏ

Nộp bản hiện tại. Ba kết quả có thể:

- **J_candidates > 14,88** → giả thuyết đúng, giữ nguyên.
- **J_candidates ≈ 14,88** → mã triệu chứng đúng nhưng độ chính xác retrieval quá thấp;
  giữ `CHẨN_ĐOÁN: 1`, hạ `TRIỆU_CHỨNG: 0`, đầu tư vào containment matching (W4).
- **J_candidates < 11,03** → giả thuyết sai bất chấp số học ở trên; hạ cả hai về 0 và
  đọc lại việc suy ra cột.

Chỉ tốn **một** lần nộp để phân định, và nó phải là một lần nộp **chỉ đổi mã** — tập
span phải giữ nguyên y hệt, đúng như A→B đã làm và B→C đã không làm.
