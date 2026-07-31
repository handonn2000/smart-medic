# ADR 0006 — Gold gán mã cho TRIỆU_CHỨNG: **bật THUỐC + TRIỆU_CHỨNG, tắt CHẨN_ĐOÁN**

- **Trạng thái:** ĐÃ QUYẾT — đã sửa 31/07 sau khi có kết quả đo
- **Ngày:** 2026-07-31
- **Ảnh hưởng:** `io/labels.py` · `decision/emit.py` · `configs/pipeline.yaml`

> ## ⚠ ĐÍNH CHÍNH — bản gốc của ADR này đảo ngược `cfe764c` và đã sai một nửa
>
> Lần nộp D (bản bật mã cả ba loại) được **22,0015**, thấp hơn lần nộp B
> (23,2276) đúng 1,23 điểm, và toàn bộ khoảng cách nằm ở `J_candidates`
> (14,8832 → 11,6075). Phân rã theo loại ở [mục "Đo thật"](#đo-thật) cho:
>
> | | đóng góp J_candidates | điểm |
> |---|---|---|
> | mã THUỐC | +3,8573 pp | **+1,54** |
> | mã CHẨN_ĐOÁN | −4,5433 pp | **−1,82** |
> | mã TRIỆU_CHỨNG | +1,25…+2,27 pp | **+0,50…+0,91** |
>
> **Luận điểm chính của ADR vẫn đứng vững:** gold thật CÓ gán mã cho
> TRIỆU_CHỨNG, và mã triệu chứng dương trong mọi kịch bản. Phần **sai** là gộp
> mã CHẨN_ĐOÁN bật lại cùng lúc — `cfe764c` đã đúng và tôi đã đảo nhầm.
>
> Chỗ hổng trong lập luận: ADR chứng minh gold **có** mã, đó là điều kiện *cần*.
> Nó chưa bao giờ chứng minh mã **của ta** đủ chính xác để vượt điểm hoà vốn
> `a/(1−a) > P(gold ∅)/(1−P(gold ∅)) = 0,553`. Triệu chứng vượt vì chương XVIII
> là từ vựng đóng, nhỏ, đúng những từ bệnh nhân viết; chẩn đoán là cụm danh từ
> mở, nơi một mã "gần đúng" chỉ đơn giản là một mã sai.

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

Hai mô hình mô phỏng được chạy, và **các cột dưới đây không được trộn giữa hai
mô hình** — mỗi hàng là một mô hình, đọc trọn vẹn.

*Mô hình 1 — gán mã tất định (mọi entity thuộc loại có mã đều có mã):*

| giả thuyết | P(cand rỗng) | P(assert rỗng) | tỷ lệ |
|---|---|---|---|
| gold mã DX+THUỐC | 0,276 | 0,357 | **0,774** |
| **+ TRIỆU_CHỨNG** | 0,137 | 0,357 | **0,385** |

*Mô hình 2 — gán mã theo tỷ lệ quan sát trên gold tổng hợp (DX 0,95 · THUỐC 0,94
· TRIỆU_CHỨNG 1,0), và thử thêm cách đọc scope hẹp:*

| giả thuyết | J_cand | J_assert | tỷ lệ |
|---|---|---|---|
| gold mã DX+THUỐC · scope mọi khái niệm | 28,50 | 35,69 | **0,799** |
| gold mã DX+THUỐC · scope chỉ loại có mã | 2,16 | 35,69 | **0,061** |
| **+ TRIỆU_CHỨNG · scope mọi khái niệm** | 14,52 | 35,69 | **0,407** |

Kết luận không phụ thuộc chọn mô hình nào: **cả hai** đều cho giả thuyết
DX+THUỐC ra tỷ lệ ~0,77–0,80 (cao hơn 0,356 hơn hai lần) và giả thuyết có
TRIỆU_CHỨNG ra ~0,39–0,41 (lệch 1,1×). Cách đọc scope hẹp sai 5,8 lần theo chiều
ngược lại. Giả thuyết có TRIỆU_CHỨNG là giả thuyết duy nhất nằm gần con số đo
được, dưới mọi cách mô phỏng đã thử.

## Hai lời giải thích thay thế, đều đã loại

**"Proxy gold lệch tỷ lệ loại, không phải gold có thêm mã."** Nếu tỷ lệ 0,356 chỉ do tập
test thật có nhiều CHẨN_ĐOÁN/THUỐC hơn proxy đo được, thì cần tỷ lệ hai loại đó lên tới
~90% tổng số khái niệm. Quét toàn dải: 0,34 → 0,776 · 0,65 → 0,590 · 0,90 → 0,500 ·
0,95 → 0,485. **Ngay cả ở 95% vẫn không chạm 0,356.** Lệch tỷ lệ loại không thể là lời
giải thích, dù lệch đến mức phi lý.

**"Scorer chỉ chấm candidates trên các loại có mã."** Cách đọc này cho 0,061 — sai 5,8
lần theo chiều ngược lại. Loại.

## Quyết định (đã sửa theo số đo 31/07)

`CODEABLE_TYPES = {CHẨN_ĐOÁN, THUỐC, TRIỆU_CHỨNG}` — giữ nguyên, vì đây là cổng
schema và bằng chứng tỷ lệ vẫn nói gold có mã cho cả ba.

`max_candidates_per_type: {CHẨN_ĐOÁN: 0, THUỐC: 2, TRIỆU_CHỨNG: 1}`.

`CHẨN_ĐOÁN: 0` là **kết quả đo**, không phải kết luận suy diễn: cùng một cấu hình
đó đã được nộp và mất 1,82 điểm. Nếu sau này có cách sinh mã chẩn đoán tốt hơn
(containment matching, hoặc làn M), chỉ cần đổi số này về 1 và nộp lại một lần
**chỉ-đổi-mã** để đo — cổng schema không cản.
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

Việc bật mã CHẨN_ĐOÁN được **cả hai nguồn ủng hộ** — gold tổng hợp +2,54, và lập
luận tỷ lệ ở trên — và **cả hai đều sai**: leaderboard đo được −1,82. Đây là chi
tiết đắt nhất trong toàn bộ ADR này, nên ghi rõ: hai nguồn cùng đồng ý không
mạnh hơn một nguồn, khi cả hai đo *"gold có mã không"* còn thứ quyết định điểm là
*"mã của ta có đúng không"*.

Việc bật mã TRIỆU_CHỨNG chỉ được leaderboard ủng hộ (gold tổng hợp nói không, và
điểm gold giảm đúng như dự báo) — và leaderboard đo được **+0,50…+0,91**. Bài học
*nhánh candidates chỉ nghiệm thu bằng leaderboard* đứng vững ở cả hai chiều: nó
cứu mã triệu chứng khỏi bị gold bác oan, và nó là thứ duy nhất bắt được mã chẩn
đoán mà gold khen nhầm.

## Đo thật

Bản gốc ADR này viết sẵn ba kịch bản và bảo "chỉ tốn một lần nộp để phân định".
Đã nộp — lần nộp D, 31/07 08:49:

| | WER | text | J_assertion | J_candidates | điểm |
|---|---|---|---|---|---|
| A · span+type, 0 mã | 73,3700 | 26,6300 | 30,9496 | 11,0259 | 21,6847 |
| B · A + 228 mã THUỐC | 73,3700 | 26,6300 | 30,9496 | 14,8832 | 23,2276 |
| C · 948 mã dx+thuốc | 73,1700 | 26,8300 | 31,2028 | 10,4617 | 21,5945 |
| **D · W0–W5** | 73,3163 | 26,6837 | 31,1780 | **11,6075** | **22,0015** |

`J_candidates = 11,6075` rơi vào đúng nhánh thứ ba đã viết sẵn: **thấp hơn B**.

### Cách khử `m` mà bản gốc chưa nghĩ ra

Bản gốc kêu rằng B→C bị hỗn nhiễu vì tập span đổi. Đúng, nhưng vẫn khử được:
**lần nộp C phát `assertions: []` khắp nơi**, nên `J_assertion` của nó bằng
`m_C · P(gold assert ∅)` — chia cho A là ra thẳng tỷ số match rate, **không cần
giả định gì về `q`**:

```
m_C / m_A = 31,2028 / 30,9496 = 1,00818
q_C / q_A = (26,8300/26,6300) / 1,00818 = 0,99933    (biên gần như không đổi)
```

Có `m` rồi thì các đóng góp trở nên **cộng tính** — mỗi cặp đã ghép thuộc đúng
một loại, nên mã của các loại không chồng lấn nhau:

```
mã THUỐC       = J_c(B) − J_c(A)                        = +3,8573 pp  → +1,54 điểm
mã CHẨN_ĐOÁN   = J_c(C) − m_C·[J_c(A) + mã THUỐC]       = −4,5433 pp  → −1,82 điểm
mã TRIỆU_CHỨNG = J_c(D) − m_D·[J_c(A) + hai mã trên]    = +1,25…+2,27 → +0,50…+0,91
```

Khoảng của TRIỆU_CHỨNG quét toàn bộ `q_D/q_A` từ 1,00 đến 1,11 (giới hạn trên là
mức W4 đo trên proxy gold); **nó dương ở mọi điểm**, nên kết luận đó không phụ
thuộc ẩn số.

### Điều này khẳng định gì và bác bỏ gì

**Khẳng định:** gold thật có gán mã cho TRIỆU_CHỨNG. Ràng buộc
`P(gold cand ∅) ≤ 0,356` từ lần nộp A là số học thuần, không đụng tới, và mã
triệu chứng đo được là dương.

**Bác bỏ:** việc bật lại mã CHẨN_ĐOÁN. Hiệu chỉnh `m` làm nó trông **tệ hơn**
(−4,54 pp) so với con số −1,77 mà `cfe764c` đã quy cho nó. `cfe764c` đúng.

**Lỗ hổng lập luận, ghi lại để không lặp:** ADR chứng minh gold **có** mã — điều
kiện *cần*. Điều kiện *đủ* là mã **của ta** phải chính xác hơn điểm hoà vốn
`a/(1−a) > P(∅)/(1−P(∅)) = 0,553`. Hai điều kiện này bị tôi gộp làm một. Triệu
chứng vượt ngưỡng vì chương XVIII là từ vựng đóng và nhỏ; chẩn đoán không vượt vì
là cụm danh từ mở, nơi mã "gần đúng" vẫn là mã sai.

## Đã bác bỏ xong — lần nộp E, 31/07 11:35

Dự báo trước khi nộp: `J_candidates ≈ 15,7…16,2`, điểm **23,6…23,8**, với hai
điều kiện bất biến vì đây là lần nộp **chỉ-đổi-mã**.

| | dự báo | thực tế | |
|---|---|---|---|
| `WER` | 73,3163 (bắt buộc) | **73,3163** | ✅ khớp đến chữ số cuối |
| `J_assertion` | 31,1780 (bắt buộc) | **31,1780** | ✅ khớp đến chữ số cuối |
| `J_candidates` | 15,7…16,2 | **15,0845** | hụt 0,6 |
| **điểm** | 23,6…23,8 | **23,3923** | hụt 0,21 — **kỷ lục mới** |

`0,3·26,6837 + 0,3·31,178 + 0,4·15,0845 = 23,3923` — khớp chính xác số BTC báo.

### Hai cột bất biến khớp khít, nên đây là phép đo sạch

Không cần hiệu chỉnh `m` gì cả. Giá trị của 756 mã CHẨN_ĐOÁN đo trực tiếp:

```
J_cand(D, có mã CĐ) = 11,6075
J_cand(E, bỏ mã CĐ) = 15,0845
                      ────────
chênh               = +3,4770 pp  →  +1,3908 điểm
```

**Dấu đúng, độ lớn hụt 24%** so với dự báo +1,82. Nguồn sai số đã xác định: dự
báo dùng `m_C/m_A = 1,00818` suy từ lần nộp C, mà C có tập span khác D/E — tỷ lệ
đó không chuyển hoàn hảo sang một tập span khác. Ghi lại như một giới hạn của
phương pháp khử `m` xuyên-lần-nộp: nó cho **dấu** đáng tin, **độ lớn** thì không.

Kết luận của ADR không đổi: `cfe764c` đúng, việc W1 đảo lại là sai, và
`CHẨN_ĐOÁN: 0` là cấu hình đúng.

### Neo mới cho các tham số ẩn

Từ E, với `J_assert = m·P(gold assert ∅) ≤ m`:

```
m ≥ 0,3118          (chặt hơn cận từ q ≤ 1, vốn chỉ cho m ≥ 0,2668)
q = 0,2668 / m      →  m = 0,3118 ⇒ q = 0,856
E[J_cand | đã ghép] = 0,1508 / m  →  ≈ 0,48
```

Đọc: trong số entity **đã ghép**, ta mới ăn ~48% điểm mã tối đa. Còn dư địa ở
nhánh candidates, và cận `m ≥ 0,3118` này là neo chính xác nhất hiện có cho mọi
dự báo sau.
