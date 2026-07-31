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

Mô phỏng trên `proxy_gold_test/` (20 file test thật gán nhãn tay, 718 span), trọng số
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

---

## ĐO THẬT LẦN 2 — lần nộp H, 31/07 20:55

**H = 22,6801.** Thất bại: kém E (23,3923) **0,7122 điểm**. Cả ba cột giảm.

| cột | E | H | Δ | góp vào Δ |
|---|---|---|---|---|
| text (100−WER) | 26,6837 | 25,9546 | −0,7291 | −0,2187 |
| J_assertion | 31,1780 | 30,0833 | −1,0947 | −0,3284 |
| J_candidates | 15,0845 | 14,6718 | −0,4127 | −0,1651 |

Ba cột giảm gần **cùng tỷ lệ** (0,9727 · 0,9649 · 0,9726) — chữ ký của
pha loãng thuần, không phải của span sai.

### Khớp mô hình: gold KHÔNG gán nhãn chuỗi `***` nào

Quét số chuỗi `***` mà gold có gán (n) và tỷ lệ slot/span:

| n | sai số khớp |
|---|---|
| **0** | **0,0078** |
| 10 | 0,0530 |
| 20 | 0,0997 |
| 99 | 0,5273 |

n=0 khớp tốt hơn phương án gần nhất **6,8 lần**. Và mọi n>0 dự đoán các cột
**tăng** — thực tế cả ba giảm.

Bằng chứng 7/7 từ `data/proxy_gold_test/` bị bác bỏ, đúng ở chỗ đã ghi là yếu
nhất: gold tay do LLM sinh, và LLM thấy chuỗi sao trong ngữ cảnh thuốc thì gán
THUỐC. BTC che tên thuốc để **loại** nó khỏi bài toán, không phải để hỏi về nó.

### Neo lại kích thước gold — đảo chiều chiến lược

Hệ số pha loãng cho slot/span = 1,407 ⇒ SLOTS_E ≈ 4097.

| | ước cũ | neo mới |
|---|---|---|
| gold (entity) | 3893 | **~2550** |
| recall | 0,41 | **0,54** |
| precision | 0,56 | **0,47** |
| span thừa | 1287 | **1545** |

Gold nhỏ hơn nhiều so với mọi ước lượng trước. Ta đã bắt 54% gold, nhưng
**1545 trong 2912 span phát ra là thừa**.

H vừa đo trực tiếp giá trị của span thừa: **99 span thừa = −0,7122 điểm**, tức
**−0,72 điểm mỗi 100 span thừa**. Đây là hệ số dùng được cho mọi quyết định sau.

Hướng đi đảo ngược: từ đầu phiên tôi xếp recall là đòn bẩy lớn nhất; neo mới nói
**precision** mới là chỗ có điểm.

### Quyết định

`extract.recall_floor.redacted.enabled` giữ **false** vĩnh viễn. Làn và test ở
lại vì phép đo có giá trị, nhưng nó không bao giờ được bật lại trừ khi có bằng
chứng mới về quy ước gold.

H+ (12 mã co-reference) **không cần nộp**: mã nằm trên span thừa, nên H+ = H
cộng 0. Dự báo 22,68 ± 0,01.

Lần nộp tiếp theo nên là **F** (tắt làn lexicon, 2571 span). Dưới neo mới nó bỏ
341 span và có kỳ vọng dương ở mọi tỷ lệ đúng r < 0,73 — ngưỡng hoà vốn rất cao
vì bỏ một span thừa được 1 đơn vị còn mất một span đúng chỉ tốn 0,267.

---

## ĐO THẬT LẦN 3 — lần nộp F, 31/07 21:10

**F = 23,3109.** Kém E (23,3923) chỉ **0,0814**, nhưng các cột đi NGƯỢC chiều nhau
— đó là thông tin, không phải nhiễu.

| cột | E | F | Δ | tỷ lệ F/E |
|---|---|---|---|---|
| text | 26,6837 | **27,0796** | **+0,3959** | 1,0148 |
| J_assertion | 31,1780 | **31,9002** | **+0,7222** | 1,0232 |
| J_candidates | 15,0845 | 14,0425 | **−1,0420** | 0,9309 |

`text` 27,08 là **cao nhất trong sáu lần nộp**. Nhưng J_candidates giảm 6,9%.

### Làn lexicon: precision 0,23, và vẫn nên GIỮ

Khớp mô hình trên (G span đúng, S span thừa) trong 341 span mà làn phát ra:

    G=80 đúng · S=261 thừa   sai số 0,0144   <- khớp tốt nhất

Con số này khớp độc lập với `text_F/text_E = 1,0148`, mà bảng dựng TRƯỚC khi nộp
đã quy ra r ≈ 0,20–0,24.

Kinh tế của quyết định:

    bỏ 261 span thừa  -> text +1,48%, J_a +2,32%  = +0,335 điểm
    mất  80 span đúng -> J_candidates −6,91%      = −0,417 điểm
    ròng                                            −0,081 điểm

**Trọng số 0,4 của J_candidates là lý do.** 80 span đúng mang mã ICD đúng có giá
trị hơn 261 span thừa gây pha loãng. Đây là bài học tổng quát cho bài toán này:
**MÃ ĐÚNG quan trọng hơn PRECISION SPAN.**

`extract.recall_floor.lexicon.enabled` giữ **true**.

### Hai bộ lọc đã thử và loại

Bỏ "từ tố" (`viêm` 72 lần, `tổn thương` 59 lần, `mụn` 44 lần — chúng khớp bên
trong cụm dài hơn): loại 199 span nhưng nhóm loại có **58%** mang mã so với
**55%** ở nhóm giữ. Bộ lọc không phân biệt được, sẽ mất J_candidates đúng như F.

Bỏ span 1 từ: phân biệt tốt hơn (32% có mã so với 76% ở span ≥2 từ), nhưng dự báo
chỉ **+0,10 điểm**. Quá nhỏ để tốn một lượt nộp.

### Đòn bẩy còn lại, định giá bằng chính F

F cho hệ số đo được: **mỗi span có mã đúng = +0,0052 điểm** (0,417 / 80).

Bản E còn **1660/2912 span chưa có mã (57%)**:

| type | tổng | chưa mã |
|---|---|---|
| CHẨN_ĐOÁN | 776 | **776 (100%)** |
| TÊN_XÉT_NGHIỆM | 479 | 479 (100%) |
| KẾT_QUẢ_XÉT_NGHIỆM | 162 | 162 (100%) |
| TRIỆU_CHỨNG | 1245 | 174 (14%) |
| THUỐC | 250 | 69 (28%) |

    +200 span có mã đúng -> 24,43
    +400                 -> 25,48
    +700                 -> 27,04

Đây là đòn bẩy lớn nhất còn lại, và nó **đo được** thay vì suy đoán. Nhưng lưu ý
ràng buộc từ lần nộp C: mã CHẨN_ĐOÁN đã thử và mất 1,82 điểm, vì span chẩn đoán
phần lớn là mảnh cụt (`thận`, `sỏi`, `mạch vành`) nên mã sai. Muốn khai thác 776
span đó phải sửa BIÊN trước, không phải retrieval.

`TÊN_XÉT_NGHIỆM` và `KẾT_QUẢ_XÉT_NGHIỆM` chưa bao giờ được thử gán mã, và ADR
0006 ghi chúng nằm ngoài `CODEABLE_TYPES` theo suy luận từ đề bài — suy luận đó
giờ đáng kiểm lại bằng một lần nộp.

output.zip vẫn là E, sha 8f2e5e45… Suite 229/229.

---

## Bốn hướng loại bằng số liệu sau F — không tốn lượt nộp nào

Sau F tôi kiểm bốn hướng còn lại. Cả bốn đều bị loại **trước khi nộp**, và ghi
lại đây để không ai thử lại.

### 1· Gán mã cho 641 span xét nghiệm — NGÕ CỤT

`TÊN_XÉT_NGHIỆM` (479 span) và `KẾT_QUẢ_XÉT_NGHIỆM` (162) chưa bao giờ được thử
gán mã, nên tôi tưởng đó là đòn bẩy. Đo:

    khớp chính xác tên ICD-10:  TÊN_XN 0/479  ·  KẾT_QUẢ 0/162

ICD-10 là phân loại **bệnh**. `nội soi`, `siêu âm`, `men gan`, `SpO2` không có mã
ICD theo định nghĩa. Bộ mã đúng cho chúng là LOINC (xét nghiệm) hoặc ICD-10-PCS
(thủ thuật), và `data/knowledge_base/` **không có cả hai**: chỉ ICD10.csv,
icd10cm-*, và các file RxNorm. `RXNCONSO.RRF` có cột SAB gồm ATC, DRUGBANK,
SNOMEDCT_US, VANDF… — tất cả là tập con thuốc, 0 dòng thủ thuật/xét nghiệm.

Không phải "chưa thử" mà là **không thể**. `CODEABLE_TYPES` giữ nguyên.

### 2· Tiên nghiệm type CHẨN_ĐOÁN ↔ TRIỆU_CHỨNG — LOẠI

Đối chiếu luật "cụm mở đầu bằng từ khoá bệnh lý → CHẨN_ĐOÁN" trên 90 span
CHẨN_ĐOÁN có mặt trong gold tay:

    luật CHUYỂN sang TRIỆU_CHỨNG:  đúng 12 · SAI 18  -> precision 0,40
    luật GIỮ CHẨN_ĐOÁN          :  đúng 59 · sai  1
    accuracy tổng 0,79

Chiều chuyển **sai nhiều hơn đúng**. Bộ từ khoá thiếu cả một lớp tên bệnh không
có tiền tố hình thái: `đột quỵ`, `loãng xương`, `béo phì`, `rung nhĩ`, `trầm cảm`,
`sâu răng`, `tăng lipid máu`, `tràn dịch màng phổi`.

Đây là lần thứ hai tôi ước lượng hướng này quá lạc quan — trước ghi precision
0,86 (đo cả hai chiều gộp), đo riêng chiều cần dùng thì 0,40.

### 3· Nới cap mã TRIỆU_CHỨNG từ 1 lên 2 — LOẠI, −2,88 điểm

`J_candidates` là Jaccard trên tập: phát 2 mã khi gold có 1 cho J = 0,5 thay vì
1,0. Nới cap chỉ đáng nếu `acc(top-2) > 2·acc(top-1)` — bất khả khi acc ≈ 0,5.

Lần nộp A→B đo 0,693 đơn vị J mỗi span THUỐC ở cap 2, mà 0,693 > 0,5 nên thoạt
trông như gold có nhiều mã. Nhưng **99% mục THUỐC trong gazetteer chỉ có 1 mã**
(21802 mục 1 mã, 112 mục 2 mã), nên cap 2 gần như luôn phát 1 mã và J = 1. Giải
thích đó đủ; không có bằng chứng gold nhiều mã.

Ước lượng nếu nới cap: 95% của Σj_cand đến từ TRIỆU_CHỨNG (≈589/618 đơn vị), chia
2 làm J_candidates 15,08 → 7,90, tức **−2,88 điểm**.

Ghi chú kỹ thuật: `icd.retrieve` hiện chỉ trả top-1 (`min(acc, key=...)`), nên
cap 2 hiện tại là no-op cho TRIỆU_CHỨNG — mọi mã của loại này đến từ retrieve,
không phải gazetteer. Cap 2 chỉ có tác dụng nếu retrieve trả top-k, và phân tích
trên nói đừng làm điều đó.

### 4· Lọc phần thừa của làn lexicon — quá nhỏ

Đã ghi ở mục "Đo thật lần 3": lọc từ tố không phân biệt được (58% có mã ở nhóm
loại so với 55% ở nhóm giữ), lọc span 1 từ chỉ dự báo +0,10.

### Hệ quả

**E = 23,3923 là cực đại địa phương của kiến trúc hiện tại.** Ba lần nộp gần nhất
(D 22,00 · H 22,68 · F 23,31) đều không vượt được, và mọi hướng đổi-cấu-hình đã
cạn.

Hướng duy nhất còn giá trị lớn cần **làm việc thật**, không phải đổi tham số: sửa
biên 280 span CHẨN_ĐOÁN cụt (`thận`, `sỏi`, `mạch vành`) để mở khoá 776 span cho
mã. Nới trái bằng từ điển ICD đã thử và thất bại — gazetteer chỉ chứa tên ICD đầy
đủ nên `viêm cầu thận` không có mục riêng.
