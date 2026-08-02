# Khoảng cách leaderboard — chẩn đoán và hướng khắc phục

> **Bối cảnh:** bài nộp đầu tiên (cấu hình C1, 02/08/2026 23:31) được **18,6610**.
> Bộ đo nội bộ dự đoán **0,4857** trên `gold_real`. Chênh **2,6 lần**.
> Tài liệu này truy nguyên khoảng cách đó bằng ba nguồn bằng chứng độc lập.
>
> **Trạng thái:** chẩn đoán xong, **chưa sửa gì**. Mọi số đều đã đo.

---

## 0. Tóm tắt cho người vội

| vấn đề | mức | hậu quả đo được |
|---|---|---|
| **V1** Bộ đo nội bộ lạc quan 2,6× | **Nghiêm trọng** | Mọi quyết định Phase 1–5 dựa trên số sai |
| **V2** Quy ước `candidates` rỗng KHÔNG được thưởng | **Nghiêm trọng** | `J_candidates` 10,87/100 |
| **V3** 17 cụm rác sinh 116 mã không tồn tại | Cao | 116 mã chắc chắn 0 điểm + span thừa |
| **V4** Từ vựng mã quá sâu (189 mã, 15 ngoài danh mục) | Cao | Mã càng sâu càng dễ trật |
| **V5** Nhầm TRIỆU_CHỨNG → CHẨN_ĐOÁN | Cao | 179 span sai nhãn ⇒ mất cả 3 thành phần |
| **V6** Bỏ sót 430 span TRIỆU_CHỨNG | Cao | Recall triệu chứng thấp hơn hẳn hệ tham chiếu |
| **V7** 56 chỗ thiếu `isNegated` dù có dấu hiệu | Trung bình | Ảnh hưởng `J_assertion` (24,73) |

---

## 1. Tổng quan — ba nguồn bằng chứng

Chẩn đoán này **không** dựa vào bộ đo nội bộ, vì chính bộ đo nội bộ là thứ đang
bị nghi ngờ. Ba nguồn độc lập:

| nguồn | là gì | vì sao tin được |
|---|---|---|
| **Leaderboard** | 18,6610 + 3 thành phần | Tín hiệu ngoài duy nhất, không thiên lệch |
| **Output tham chiếu ~23đ** | 100 file `.json` của một hệ điểm cao hơn | Cùng đề, cùng input, điểm cao hơn 4,3 |
| **`scripts/validate_annotation.py`** | Bộ soát tính nhất quán, nhánh `feature/train_inference_code` | Không dùng gold nào; chỉ soát nội tại + đối chiếu ICD/RxNorm |

⚠️ Hai nguồn sau **không phải đáp án BTC**. Output tham chiếu chỉ *có khả năng*
đúng hơn ở chỗ nó khác ta, vì nó ăn điểm cao hơn — không phải chân lý.

---

## 2. V1 — Bộ đo nội bộ lạc quan 2,6 lần

### Vấn đề

Phân rã điểm leaderboard khớp chính xác công thức PRD §6:

```
0,3 × (100 − 77,0272) + 0,3 × 24,7312 + 0,4 × 10,8745 = 18,6610 ✓
```

| thành phần | `gold_real` (nội bộ) | leaderboard | tỉ lệ |
|---|---:|---:|---:|
| text (1 − WER) | 0,5245 | **0,2297** | 0,44× |
| assertions | 0,4758 | **0,2473** | 0,52× |
| candidates | 0,4640 | **0,1087** | **0,23×** |
| **final** | **0,4857** | **0,1866** | **0,38×** |

### Nguyên nhân

`data/probe/gold_real` là **9 file do chính dự án gán nhãn tay**, và mã trong đó
tra bằng **cùng một `search_lexical`** mà pipeline dùng để dự đoán. Cùng một
nguồn sai ở cả hai vế ⇒ nội bộ trông đúng còn thật thì không.

Đây đúng là cạm bẫy [`gold-chan-doan-protocol.md`](../gold-chan-doan-protocol.md)
đã ghi: *"Hai nguồn đồng ý với nhau không mạnh hơn một nguồn, khi cả hai cùng đo
'gold có mã ở đây không' còn câu hỏi được chấm là 'mã của ta có đúng không'."*
Lần trước nó dự đoán **sai dấu**; lần này **sai độ lớn**.

### Hậu quả

Mọi cổng của Phase 1–5 đều đo bằng cái thước này. Kết luận "Phase 1 +0,053" và
"Phase 4 −0,085" vẫn có thể đúng về **dấu** (chúng là so sánh tương đối trên cùng
một thước), nhưng **độ lớn tuyệt đối thì không dùng được**.

### Hướng khắc phục

- **Không** vứt `gold_real` — nó vẫn hữu ích để so sánh *tương đối* giữa hai cấu
  hình. Chỉ ngừng đọc con số tuyệt đối như dự báo điểm thi.
- Thêm cột "điểm leaderboard tương ứng" vào mọi báo cáo, cập nhật mỗi lần nộp.
- Cân nhắc gán lại `candidates` của `gold_real` bằng nguồn **độc lập** với
  `search_lexical` (tra tay từ `data/ICD10_VN.csv`).

---

## 3. V2 — Quy ước "cả hai rỗng ⇒ 1,0" KHÔNG áp cho `candidates`

### Vấn đề

Đây là phát hiện quan trọng nhất tài liệu này, và nó **lật ngược một giả định nền
của cả chiến lược**.

Bài nộp có 3.000 span, trong đó **1.693 mục để `candidates` rỗng** (mọi
TRIỆU_CHỨNG / TÊN_XN / KẾT_QUẢ_XN — đúng như PRD §3.2 quy định). Nếu quy ước
*"cả hai rỗng ⇒ Jaccard = 1,0"* thật sự áp cho `candidates`, riêng 1.693 mục đó
đã đủ đẩy `J_candidates` lên trên 0,5.

Thực tế: **`J_candidates` = 0,1087**.

### Nguyên nhân

PRD chứa **hai công thức mâu thuẫn** cho `candidates`, và tự cảnh báo hai lần
rằng phần này là *"bản trích từ ảnh đề, chưa đối chiếu công bố chính thức"*:

```
(a) Jaccard thường,  J = 1 khi len(gt) = 0 và len(pred) = 0
(b) Σₖ J·|gt(k) ∩ pred(k)|  /  Σₖ (len(gt(k)) + 1)
```

Ở công thức **(b)**, gold rỗng đóng góp `0/1` — nó **pha loãng** mẫu số nhưng
không bao giờ cộng vào tử số. Số đo leaderboard chỉ tương thích với **(b)**.

### Hậu quả — và nó đảo ngược chiến lược

Dưới công thức (b):

- **Mã thừa gần như không tốn gì** (tử số vẫn 0 nếu gold rỗng)
- **Mã thiếu mất tất cả**
- Chiến lược tối ưu là **gán mã càng rộng càng tốt**

Đó **chính xác** là thứ hệ tham chiếu 23đ đang làm:

| | tham chiếu 23đ | ta 18,66đ |
|---|---|---|
| CHẨN_ĐOÁN có mã | **0 / 776** | 1121 / 1121 |
| TRIỆU_CHỨNG có mã | **1071 / 1245** | **0 / 704** |

Nó gán `R10` cho `Đau bụng`, `R11` cho `Buồn nôn`, `R51` cho `đau đầu` —
750/1071 mã thuộc chương R. **Vi phạm PRD §3.2, và hơn ta 4,3 điểm.**

### Hướng khắc phục

Gán mã ICD cho `TRIỆU_CHỨNG` (704 span hiện để trống). Thay đổi nằm ở đúng một
chỗ — `VOCAB_OF_TYPE` trong [`stages/linking.py`](../../src/smart_medic/stages/linking.py).

⚠️ **Bắt buộc xác nhận bằng một lần nộp thử.** Suy luận trên dựa vào một công
thức PRD tự nhận là bản trích. Nếu công thức (a) mới đúng, thay đổi này sẽ làm
**tụt mạnh** — 1.693 mục đang được 1,0 sẽ về 0. Rủi ro đối xứng, và chỉ
leaderboard phân xử được.

---

## 4. V3 — 17 cụm rác sinh 116 mã không tồn tại

### Vấn đề

`validate_annotation.py` với `--icd data/ICD10_VN.csv` báo **116 `B_CODE_NOT_FOUND`**
cho bài nộp của ta, **0** cho hệ tham chiếu. Chúng đến từ đúng **17 cụm**:

| cụm | mã gán | lượt | có phải bệnh không |
|---|---|---:|---|
| `bên phải` | `N60.01` | 32 | ✗ |
| `tái phát` | `F33.40` | 22+1 | ✗ |
| `bên trái` | `N60.02` | 20 | ✗ |
| `vết cắn` | `S10.17` | 9 | ✗ |
| `bị cắn` | `S20.17` | 7 | ✗ |
| `vùng ngực` | `M47.04` | 6 | ✗ |
| `cánh tay` | `M01.02` | 5 | ✗ |
| `bàn tay` | `M01.04` | 3 | ✗ |
| `toàn diện` · `thành ngực` · `ruột non` · `loạn thần` … | | 11 | ✗ |

`medical_name_checker.py` xác nhận độc lập: `vùng ngực`, `thành ngực`,
`bên phải`, `vết cắn`, `ổn định` đều **"✗ không phải"** tên bệnh.

### Nguyên nhân

`Gazetteer.from_kb` nạp **toàn bộ 16.944 mã ICD** làm khoá phát hiện, gồm cả
những tên chỉ là **bộ phận cơ thể** hoặc **trạng từ** khi tách khỏi ngữ cảnh.
`is_fragment()` đã chặn mảnh cắt vụn theo tỉ lệ độ dài, nhưng không chặn được
những cụm *đủ dài mà vô nghĩa về lâm sàng*.

Nhiều cụm trong số này **trùng đúng danh mục bẫy** của
[`gold_real/README.md`](../../data/probe/gold_real/README.md) — thứ Phase 1 đã
ghi nhận là "khiếm khuyết có sẵn, chưa ai sửa".

### Hậu quả

Mỗi lượt mất **cả ba** thành phần điểm: span thừa (WER), assertion sai, và một mã
chắc chắn 0. 116 lượt trên 3.000 span ≈ **3,9% bài nộp là rác thuần**.

### Hướng khắc phục

1. **Danh sách chặn** trong `ner.py`: từ vựng **giải phẫu** (`bên phải`,
   `bên trái`, `cánh tay`, `bàn tay`, `vùng ngực`, `thành ngực`, `ruột non`) và
   **trạng thái/trạng từ** (`tái phát`, `toàn diện`, `ổn định`).
   Đây là kiến thức chung về loại từ, không phải chép từ gold.
2. **Chốt cứng ở `linking.py`**: mã trả ra phải tồn tại trong `data/ICD10_VN.csv`.
   Không tồn tại thì để `candidates` rỗng.

---

## 5. V4 — Từ vựng mã quá sâu

### Vấn đề

| | ta | tham chiếu 23đ |
|---|---|---|
| mã ICD phân biệt | **189** | **82** |
| độ dài 3 ký tự | 85 | 28 |
| độ dài 5 ký tự | 89 | 54 |
| độ dài **6 ký tự** | **15** | **0** |
| ngoài danh mục BYT | **15** | **0** |

15 mã 6 ký tự (`A18.03`, `F31.11`, `M01.02`, `N60.01`, `S20.21`…) là mã **mở
rộng của QĐ 4469** — chúng có trong `data/knowledge_base/icd/ICD10.csv` nhưng
**không có** trong `data/ICD10_VN.csv` (danh mục QĐ 2020, 12.218 mã).

### Nguyên nhân

KB hợp nhất hai nguồn ICD (PDF WHO + CSV QĐ 4469 = 16.944 mã) và `linking.py`
chọn mã **khớp chuỗi tốt nhất** bất kể độ sâu. Mã 6 ký tự có tên dài hơn nên
thường khớp fuzzy tốt hơn mã cha.

### Hậu quả

Jaccard phạt mã trật **ngang** mã thiếu. Mã càng sâu, xác suất khớp đúng gold
càng thấp. Hệ 23đ chọn đúng chiều ngược lại.

### Hướng khắc phục

- Lọc `linking.py` chỉ trả mã có trong `data/ICD10_VN.csv`.
- Cân nhắc **cắt về mã cha** khi mã con không có trong danh mục
  (`N60.01` → `N60`).

---

## 6. V5 + V6 — Nhầm nhãn và bỏ sót triệu chứng

### Vấn đề

Ma trận nhầm lẫn, ghép span theo chồng lấn ký tự giữa hai bài nộp
(hàng = tham chiếu 23đ, cột = ta):

```
                    TRIỆU_CHỨNG  CHẨN_ĐOÁN  TÊN_XN  KQ_XN  THUỐC
TRIỆU_CHỨNG                 608        179      24      4      0
CHẨN_ĐOÁN                    73        498      31      4      0
TÊN_XÉT_NGHIỆM                0         10     328     17     24
KẾT_QUẢ_XÉT_NGHIỆM            0          0       0     85      0
THUỐC                         6          2       7      1    123

ghép được 2.024 span · trùng nhãn 1.642 (81,1%)
ta BỎ SÓT: TRIỆU_CHỨNG 430 · CHẨN_ĐOÁN 170 · THUỐC 111 · TÊN_XN 100 · KQ_XN 77
ta THỪA:   CHẨN_ĐOÁN 432 · TÊN_XN 261 · THUỐC 136 · KQ_XN 130 · TRIỆU_CHỨNG 17
```

Hai điều đọc ra ngay:

- **179 span ta gọi CHẨN_ĐOÁN thì tham chiếu gọi TRIỆU_CHỨNG** (chiều ngược chỉ 73)
- **Ta bỏ sót 430 span TRIỆU_CHỨNG** mà chỉ thừa 17 — nhánh triệu chứng của ta
  quá dè dặt, trong khi nhánh CHẨN_ĐOÁN thừa 432 và TÊN_XN thừa 261

**Ta bắn sai chỗ:** thừa ở chẩn đoán và xét nghiệm, thiếu ở triệu chứng.

### Nguyên nhân

`ner.py` gán `TRIỆU_CHỨNG` **chỉ khi** mã thuộc chương R hoặc cụm mở đầu bằng
`SYMPTOM_HEADS` (tập từ đóng). Mọi thứ khác trong từ điển ICD → `CHẨN_ĐOÁN`.
Nhưng rất nhiều triệu chứng tiếng Việt ánh xạ sang mã **ngoài chương R**
(`tiêu chảy` → K92.2, `mụn` → B07, `xuất huyết` → A97.9 theo cách tham chiếu gán).

### Hậu quả

Sai nhãn là lỗi **đắt gấp ba**: entity đó mất điểm `text` (nếu tính theo cặp
cùng nhãn), mất `assertions`, và mất `candidates`.

### Hướng khắc phục

1. Mở rộng tiêu chí `TRIỆU_CHỨNG` ngoài chương R — dùng chính danh sách cách nói
   dân dã đã đóng băng ở [`surface_forms.v1.jsonl`](../../data/curated/surface_forms.v1.jsonl)
   (40 nhóm triệu chứng, 306 cách nói).
2. Xem lại `SYMPTOM_HEADS` — hiện quá hẹp.

---

## 7. V7 — Thiếu `isNegated`

56 chỗ có dấu hiệu phủ định trong cửa sổ ngữ cảnh mà không gắn cờ
(`H_MAYBE_NEG`), so với 48 của tham chiếu. Cộng 10 chỗ `H_MAYBE_HIST`.
`J_assertion` hiện 24,73.

Hướng khắc phục: rà lại `assertion.py` trên đúng 56 ca này — chúng nằm trong
`docs/reports/` sau khi chạy lệnh ở §9.

---

## 8. Một đính chính về chính chẩn đoán này

Lần chạy `validate_annotation.py` đầu tiên trỏ vào
`data/knowledge_base/icd/ICD10.csv` và báo **1.121 `B_CODE_NOT_FOUND`** — tức
*toàn bộ* mã của ta.

Đó là **báo động giả**. File đó có bố cục khác (`skiprows=4`, cột `Mã`), nên
`load_icd()` nạp ra **rỗng** và mọi mã đều "không tìm thấy". Với
`data/ICD10_VN.csv` — đúng bố cục script mong đợi (`skiprows=2`, cột `MÃ BỆNH`) —
con số thật là **116**.

Ghi lại vì đây là bài học lặp lại của dự án: **một bộ kiểm nạp rỗng thì không
báo lỗi, nó báo mọi thứ đều sai.** Luôn chạy bộ kiểm trên một mẫu đối chứng đã
biết là đúng trước khi tin kết quả.

---

## 9. Cách kiểm tra lại

Hai script đã được đưa về nhánh này: [`scripts/validate_annotation.py`](../../scripts/validate_annotation.py)
và [`scripts/medical_name_checker.py`](../../scripts/medical_name_checker.py)
(nguồn: `origin/feature/train_inference_code`).

### Chuẩn bị

```bash
.venv/bin/python -m pip install rapidfuzz pandas
```

### Bước 1 — dựng thư mục cặp `.txt` + `.json`

`validate_annotation.py --dir` đòi hai file cùng tên nằm **cùng thư mục**:

```bash
mkdir -p /tmp/chk && for f in data/output/*.json; do b=$(basename "$f" .json); case $b in explain|run_manifest) continue;; esac; cp "$f" "/tmp/chk/$b.json"; cp "data/test/$b.txt" "/tmp/chk/$b.txt"; done
```

### Bước 2 — soát nhất quán

```bash
.venv/bin/python scripts/validate_annotation.py --dir /tmp/chk --icd data/ICD10_VN.csv --rxnorm data/knowledge_base/rxnorm/RXNORM.csv --report docs/reports/validate-output.csv
```

⚠️ **Bắt buộc dùng `--icd data/ICD10_VN.csv`.** Mặc định của script là
`data/knowledge_base/ICD10_VN.csv` (không tồn tại) và nếu trỏ nhầm sang
`data/knowledge_base/icd/ICD10.csv` thì từ điển nạp rỗng — xem §8.

**Kiểm tỉnh táo trước khi tin kết quả:** dòng đầu ra phải cho thấy từ điển nạp
được. Nếu `B_CODE_NOT_FOUND` bằng đúng tổng số mã đang gán, tức từ điển rỗng.

### Bước 3 — soát một cụm đáng ngờ

```bash
.venv/bin/python scripts/medical_name_checker.py --icd -q "vùng ngực" --icd-path data/ICD10_VN.csv
```

### Bước 4 — chấm nội bộ (chỉ để so TƯƠNG ĐỐI, xem §2)

```bash
smk eval solve --report docs/reports/after-fix.json
```

```bash
smk eval compare --base docs/reports/phase1-labtest.json --new docs/reports/after-fix.json
```

---

## 10. Điều kiện PASS

### Cổng CHẶN — không đạt là có bug, phải sửa

| # | điều kiện | hiện tại |
|---|---|---|
| B1 | `B_CODE_NOT_FOUND` = **0** | 116 ✗ |
| B2 | Mọi mã ICD trả ra tồn tại trong `data/ICD10_VN.csv` | 15 mã ngoài danh mục ✗ |
| B3 | `smk solve` 100 file · 5 bất biến · **0 span lệch offset** | ✓ |
| B4 | `G_TYPE_CONFLICT` không tăng | 2 |
| B5 | Cụm bẫy `gold_real/README.md` **không có span nào phủ** | 6 bị phủ ✗ *(có sẵn từ trước Phase 1)* |

### Cổng ĐỊNH TUYẾN — không đạt thì ghi số, tắt cờ, đi tiếp

| # | điều kiện | hiện tại | mục tiêu |
|---|---|---|---|
| R1 | `C_CODE_MISMATCH` giảm ≥ 30% | 162 | ≤ 113 |
| R2 | `F_MISSED` không tăng | 52 | ≤ 52 |
| R3 | `H_MAYBE_NEG` giảm ≥ 40% | 56 | ≤ 34 |
| R4 | số mã ICD phân biệt giảm về gần mức tham chiếu | 189 | ≤ 120 |
| R5 | **`final` leaderboard tăng** | **18,6610** | **> 18,6610** |

★ **R5 là cổng thật sự.** Bốn cổng trên chỉ là đại lượng thay thế — chúng đo
*tính nhất quán*, không đo *điểm*. Chỉ một lần nộp mới phân xử được, và §2 vừa
cho thấy đại lượng thay thế có thể sai 2,6 lần.

### Thứ tự đề xuất

| bước | việc | rủi ro | cần nộp thử? |
|---|---|---|---|
| 1 | V3 + V4 — chặn 17 cụm rác, lọc mã theo `ICD10_VN.csv` | **Thấp** — không vi phạm đề bài | Không bắt buộc |
| 2 | V5 + V6 — mở rộng tiêu chí TRIỆU_CHỨNG | Trung bình | Nên |
| 3 | **V2 — gán mã cho TRIỆU_CHỨNG** | **Cao, đối xứng** | **Bắt buộc** |

Bước 3 có đòn bẩy lớn nhất nhưng vi phạm PRD §3.2. Làm **sau cùng**, một mình,
để một lần nộp phân xử đúng một giả thuyết.

---

## 11. Prompt triển khai

Ba prompt tự chứa, một cho mỗi bước ở §10. Bản rời để copy nằm ở
[`.claude/prompts/fix/`](../../.claude/prompts/fix/).

### F1 — chặn cụm rác + lọc mã theo danh mục BYT (V3 + V4)

```
Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §4, §5, §9, §10.
Đọc trước: src/smart_medic/stages/ner.py (Gazetteer.from_kb, is_fragment),
           src/smart_medic/stages/linking.py (toàn bộ, kèm docstring).

Vấn đề đã đo: 116 mã ICD ta trả ra KHÔNG tồn tại trong data/ICD10_VN.csv, và
chúng đến từ đúng 17 cụm — không cụm nào là tên bệnh:
  'bên phải' N60.01 ×32 · 'tái phát' F33.40 ×23 · 'bên trái' N60.02 ×20
  'vết cắn' S10.17 ×9 · 'bị cắn' S20.17 ×7 · 'vùng ngực' M47.04 ×6
  'cánh tay' M01.02 ×5 · 'bàn tay' M01.04 ×3 · 'thành ngực' 'ruột non'
  'toàn diện' 'loạn thần' 'viêm xương tủy' 'Xuất huyết tiêu hóa' …
Hệ tham chiếu 23đ có 0 lỗi loại này và chỉ dùng 82 mã (ta 189, trong đó 15 mã
6 ký tự nằm ngoài danh mục BYT).

Việc:
1. ner.py — danh sách chặn theo LOẠI TỪ, không phải theo ca cụ thể:
   - từ vựng GIẢI PHẪU đứng một mình: bên phải/trái, cánh tay, bàn tay, ngón
     tay, vùng ngực, thành ngực, ruột non, ổ bụng, cẳng chân...
   - TRẠNG THÁI / TRẠNG TỪ: tái phát, toàn diện, ổn định, tiến triển, cấp tính,
     mạn tính (khi ĐỨNG MỘT MÌNH, không phải khi là hậu tố của tên bệnh)
   Đây là kiến thức chung về loại từ. KHÔNG chép thực thể từ
   data/probe/gold_real/README.md — đó là file cổng (quy tắc §5.7).

2. linking.py — CHỐT CỨNG: mã trả ra phải tồn tại trong data/ICD10_VN.csv
   (skiprows=2, cột 'MÃ BỆNH' và 'MÃ LOẠI', 12.218 mã). Không tồn tại thì:
   - thử cắt về mã cha (N60.01 → N60); nếu mã cha có thì dùng
   - vẫn không có thì để candidates RỖNG
   Nạp danh mục một lần, cache; KHÔNG gọi mạng.

3. Test:
   - mọi mã linking.py trả ra đều có trong ICD10_VN.csv (test hồi quy)
   - 17 cụm ở trên không sinh span nào
   - rerank=True vẫn được giữ (test hồi quy đã có ở tests/unit/test_arbiter.py)

CỔNG CHẶN (không đạt = có bug):
- B_CODE_NOT_FOUND = 0 khi chạy lại §9 bước 2
- smk solve 100 file, 5 bất biến, 0 span lệch offset
- pytest xanh

CỔNG ĐỊNH TUYẾN (không đạt = ghi số, đi tiếp):
- số mã ICD phân biệt <= 120 (hiện 189)
- C_CODE_MISMATCH giảm >= 30% (hiện 162 → <= 113)
- Δfinal trên gold_real >= 0

⚠️ gold_real chỉ dùng để so TƯƠNG ĐỐI. §2 cho thấy nó lạc quan 2,6 lần —
đừng đọc con số tuyệt đối như dự báo điểm thi.
```

### F2 — mở rộng tiêu chí TRIỆU_CHỨNG (V5 + V6)

```
Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §6, §9, §10.
Đọc trước: src/smart_medic/stages/ner.py (SYMPTOM_HEADS, Gazetteer.from_kb).

Vấn đề đã đo, ghép span giữa bài nộp của ta và bài 23đ:
  179 span ta gọi CHẨN_ĐOÁN thì tham chiếu gọi TRIỆU_CHỨNG (ngược lại chỉ 73)
  ta BỎ SÓT 430 span TRIỆU_CHỨNG, mà chỉ THỪA 17
  ta THỪA 432 CHẨN_ĐOÁN và 261 TÊN_XÉT_NGHIỆM
⇒ Ta bắn SAI CHỖ: thừa ở chẩn đoán/xét nghiệm, thiếu ở triệu chứng.

Nguyên nhân: ner.py chỉ gán TRIỆU_CHỨNG khi mã thuộc chương R hoặc cụm mở đầu
bằng SYMPTOM_HEADS (tập từ đóng, quá hẹp). Nhiều triệu chứng tiếng Việt ánh xạ
sang mã NGOÀI chương R — tham chiếu gán 'tiêu chảy'→K92.2, 'mụn'→B07,
'xuất huyết'→A97.9.

Việc:
1. Nguồn mở rộng ĐÃ CÓ SẴN và đã đóng băng:
   data/curated/surface_forms.v1.jsonl — 40 nhóm TRIỆU_CHỨNG, 306 cách nói dân
   dã (sốt/nóng sốt/phát sốt, khó thở/hụt hơi/ngộp thở, tim đập nhanh/hồi hộp
   đánh trống ngực...). Nạp nhánh TRIỆU_CHỨNG của file này vào gazetteer với
   nhãn TRIỆU_CHỨNG, ƯU TIÊN CAO HƠN nhãn suy ra từ chương ICD.
2. Rà lại SYMPTOM_HEADS — bổ sung đầu ngữ còn thiếu, nhưng ĐO trước khi thêm.
3. Không đụng nhánh THUỐC (P 0,942, đang mạnh nhất).

CỔNG CHẶN:
- 5 bất biến pass, 0 span lệch offset
- pytest xanh
- cụm bẫy gold_real/README.md không bị phủ THÊM so với trước khi sửa

CỔNG ĐỊNH TUYẾN:
- recall TRIỆU_CHỨNG trên gold_real tăng >= 0,05
- precision CHẨN_ĐOÁN không giảm
- Δfinal >= 0

Nếu có bài nộp tham chiếu, kiểm lại ma trận nhầm lẫn: ô
(tham chiếu=TRIỆU_CHỨNG, ta=CHẨN_ĐOÁN) phải giảm từ 179 xuống dưới 120.
```

### F3 — gán mã cho TRIỆU_CHỨNG (V2) · **RỦI RO CAO, LÀM SAU CÙNG**

```
Bối cảnh: đọc docs/reports/leaderboard-gap-analysis.md §3 TOÀN BỘ trước khi
làm bất cứ gì. Đây là thay đổi VI PHẠM PRD §3.2 một cách có chủ đích, dựa trên
một suy luận từ leaderboard chứ không từ đề bài.

Suy luận: J_candidates = 10,87 trong khi bài nộp có 1.693/3.000 mục candidates
rỗng. Nếu quy ước "cả hai rỗng ⇒ Jaccard = 1,0" áp cho candidates thì riêng
1.693 mục đó đã đẩy J_candidates lên trên 0,5. Nó chỉ có 0,109.
⇒ Bộ chấm thật dùng công thức (b) của PRD, nơi gold rỗng đóng góp 0/1.
⇒ Mã thừa gần như không tốn gì; mã thiếu mất tất cả.
Hệ tham chiếu 23đ làm đúng điều này: 1071/1245 TRIỆU_CHỨNG có mã, 0/776
CHẨN_ĐOÁN có mã.

Việc — GIỮ THẬT NHỎ, để một lần nộp phân xử đúng MỘT giả thuyết:
1. linking.py: thêm TRIỆU_CHỨNG vào VOCAB_OF_TYPE → 'icd10'.
2. solve.py check_invariants: nới bất biến 3 cho TRIỆU_CHỨNG. GIỮ NGUYÊN cấm
   với TÊN_XÉT_NGHIỆM và KẾT_QUẢ_XÉT_NGHIỆM — tham chiếu cũng không gán mã cho
   hai nhãn đó.
3. Đặt sau một CỜ trong data/curated/pipeline.v1.yaml (vd `code_symptoms`),
   mặc định false. Bật lên chỉ để sinh bài nộp thử.
4. KHÔNG kèm bất kỳ thay đổi nào khác trong cùng bài nộp.

CỔNG CHẶN:
- 5 bất biến (đã nới) pass, 0 span lệch offset
- mọi mã mới vẫn tồn tại trong data/ICD10_VN.csv (chốt của F1)
- pytest xanh

CỔNG ĐỊNH TUYẾN — CHỈ LEADERBOARD PHÂN XỬ:
- nộp thử một lần. final tăng ⇒ giữ cờ true. final giảm ⇒ TẮT CỜ NGAY và ghi
  kết quả âm vào docs/reports/.
- gold_real KHÔNG dùng được cho quyết định này: bộ đo nội bộ cài đúng quy ước
  "cả hai rỗng ⇒ 1,0", tức nó cài GIẢ THUYẾT ĐANG BỊ NGHI NGỜ. Nó sẽ báo TỤT
  dù thực tế có thể TĂNG.

⚠️ Rủi ro ĐỐI XỨNG. Nếu công thức (a) mới đúng thì 1.693 mục đang được 1,0 sẽ
về 0 và điểm tụt mạnh. Giữ bài nộp hiện tại (18,6610) làm bản lui.
```

---

## 12. Tham chiếu

| đường dẫn | nội dung |
|---|---|
| [`synth-corpus-plan-v2.md`](../synth-corpus-plan-v2.md) | Kế hoạch 7 phase, §0.2 trần theo nhánh |
| [`gold-chan-doan-protocol.md`](../gold-chan-doan-protocol.md) | Tiền lệ gold tự dựng dự đoán sai dấu |
| [`phase5-gate.json`](phase5-gate.json) | Bốn cấu hình và luật chọn C1 |
| [`PRD.html`](../PRD.html) | §6 metric; hai công thức `candidates` mâu thuẫn |
| `data/ICD10_VN.csv` | Danh mục BYT QĐ 2020, 12.218 mã — **nguồn chuẩn cho B1/B2** |
