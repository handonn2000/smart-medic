# Phân tích dữ liệu trước khi code

**Ngày:** 25/07/2026 · **Phạm vi:** toàn bộ 100 file `data/test/` + `ICD10.csv` + `RXNCONSO.RRF`
**Mục đích:** kiểm chứng lại mọi con số trong PRD tab 4 bằng đo trực tiếp, phát hiện bẫy chưa được ghi nhận, và chốt dev set 20 file trước khi viết pipeline.

Mọi con số dưới đây đo trên **toàn bộ 100 file** (khác PRD tab 4 — nhiều bảng ở đó chỉ đo trên 10–12 file).

---

## 1. Đối chiếu với PRD — cái gì đúng, cái gì lệch

| Chỉ số | PRD tab 4 | Đo lại | Kết luận |
|---|---|---|---|
| Số ký tự corpus | 203.817 | **203.817** | ✅ khớp tuyệt đối |
| TB / min / max ký tự | 2.038 / 1.293 / 4.481 | **2.038 / 1.293 / 4.481** | ✅ khớp |
| File lệch NFD | 20 | **20** | ✅ khớp |
| File có token thuốc bị che | 30 · 99 token | **30 · 99 token** | ✅ khớp |
| File chứa tên ICD nguyên văn | 94/100 | **94/100** | ✅ khớp |
| Mention nguyên văn nhập nhằng mã | 0 | **0** | ✅ khớp |
| Tên ICD nhập nhằng trong bảng | 1,2% | **1,1%** (164/14.270) | ✅ khớp |
| File bị che có neo co-reference | 17/30 | **17/30** | ✅ khớp (xem §5) |
| Cue "không" | 561 lần / 100 file | **561 / 100** | ✅ khớp |
| Cluster near-duplicate | 20 cluster · 42 file | **22 cluster · 56 file** | ⚠️ PRD đếm thiếu |
| Số mention ICD nguyên văn | 274 | **494 thô · 106 cặp (tên,mã) duy nhất** | ⚠️ khác cách dedup |
| Thể loại (bệnh án / hỏi–đáp / khác / giáo dục) | 38 / 44 / 16 / 2 | **49 / 41 / 7 / 3** | ⚠️ heuristic khác nhau |

**Đọc bảng này thế nào:** phần đo lường cứng của PRD (ký tự, NFD, token che, coverage gazetteer, co-reference) **tái lập được chính xác** — số liệu đáng tin. Ba dòng ⚠️ là khác biệt phương pháp, không phải sai. Riêng dòng cluster là PRD đếm thiếu thật (§4).

---

## 2. Phát hiện mới #1 — gazetteer ICD **không phải** đường tất định

PRD kết luận: *"Phần trọng số cao nhất (0.4) có một đường tất định — với 94/100 file, mã ICD đúng lấy được bằng tra bảng nguyên văn, độ chính xác tuyệt đối."*

Coverage thì đúng. **Độ chính xác thì không.** Soi 494 mention khớp nguyên văn theo chương ICD:

| Chương | Mention | Ý nghĩa |
|---|---|---|
| **R** | **134 (27%)** | **Triệu chứng & dấu hiệu bất thường — không phải chẩn đoán** |
| L | 68 | Bệnh da |
| D | 53 | U & bệnh máu |
| K | 49 | Tiêu hóa |
| A | 39 | Nhiễm khuẩn |
| I | 36 | Tuần hoàn |
| còn lại | 115 | N, M, Z, E, G, H |

**27% mention khớp nguyên văn rơi vào chương R**: `khó thở`→R06.0 (65 lần), `đau đầu`→R51 (32), `đánh trống ngực`→R00.2 (13), `chán ăn`→R63.0, `buồn nôn và nôn`→R11, `hắt hơi`→R06.7.

Đây gần như chắc chắn là **TRIỆU_CHỨNG**, mà theo schema thì `candidates` của TRIỆU_CHỨNG **phải rỗng**. Gán R06.0 cho "khó thở" là điền mã vào chỗ đáng lẽ rỗng → Jaccard = 0 cho mention đó, và checklist §7 của chính PRD cấm việc này.

### Rác trong bảng ICD10.csv sinh false positive trực tiếp

| Chuỗi khớp | Mã trả về | Tên trong bảng | Vấn đề |
|---|---|---|---|
| `thận` | D30.0 | "Thận" (nhóm: U lành) | Tên bị **cắt cụt** — mất chữ "U lành". Khớp 27 lần, sai 100% |
| `test` | D15.098 | "test" | **Dòng rác** của người nhập liệu. Mã D15.098 không tồn tại trong ICD-10 |
| `ngứa` | L29 | "Ngứa" | Là triệu chứng trong hầu hết ngữ cảnh |
| `tim to` | I51.7 | "Tim to" | Là dấu hiệu cận lâm sàng |
| `đột tử` | R96.0 | "Đột tử" | Chương R |

Soi ngữ cảnh thật của `thận` trong corpus: *"…sỏi **thận** không ứ nước…"* · *"…bệnh **thận** mạn…"* · *"…hội chứng **thận** hư…"* · *"…ảnh hưởng đến tim, mạch, gan, **thận**…"* — không lần nào là u lành thận. Longest-match không cứu được vì các cụm dài kia **không có** trong bảng dưới dạng nguyên văn.

Bảng còn **42 tên bệnh ≤6 ký tự** (`Bí đái`, `Chắp`, `Chốc`, `Lao kê`, `Khô da`, `Hở mi`…) — mọi tên ngắn đều là mìn false positive khi quét substring.

### Vệ sinh bảng ICD10.csv (đo trên 36.689 dòng)

- **2.120 dòng (5,8%)** có mã sai format ICD-10 chuẩn — chủ yếu hậu tố `*` và `†` của hệ thống dagger/asterisk (`H28.0*`, `H32*`). Phải quyết định strip hay giữ; trả `H28.0*` khi đáp án là `H28.0` là **sai chuỗi** → Jaccard 0.
- **955 dòng** có `Hiệu lực = Không` (mã đã hết hiệu lực) → nên loại khỏi gazetteer.
- **11.781 tên** xuất hiện nhiều lần trong bảng.
- 1 mã có 3 chữ số thập phân (`D15.098` — dòng rác nói trên).

### ⇒ Sửa lại thứ tự pipeline

PRD lộ trình #1 viết *"gazetteer trước, embedding sau"*. Đúng ở tầng retrieval, nhưng **thứ tự thật phải là:**

```
NER + entity typing  →  CHỈ span type=CHẨN_ĐOÁN mới đi vào gazetteer  →  ICD code
                        (span type=TRIỆU_CHỨNG dừng ở đây, candidates=[])
```

Type quyết định gazetteer, không phải ngược lại. Chạy gazetteer trên văn bản thô rồi mới gán type là công thức tự bắn vào chân — vì 27% khớp sẽ kéo mã cho triệu chứng.

Kèm theo: stoplist cho tên ≤6 ký tự, lọc `Hiệu lực=Có`, chuẩn hóa hậu tố `*`/`†`, và giữ kỷ luật longest-match (`suy tim` I50 lồng trong `suy tim, không đặc hiệu` I50.9).

**6 file gazetteer không phủ:** 37, 48, 56, 88, 94, 95 → đây là phần bắt buộc phải dùng retrieval ngữ nghĩa.

---

## 3. Phát hiện mới #2 — cue gia đình "ông" nổ bên trong chữ "không"

Đếm ngây thơ chuỗi `"ông "` trong corpus: **644 lần**. Đếm có ranh giới từ: **14 lần**.

**630/644 = 98% là mảnh của chữ "kh-ông".** Một matcher substring cho cue gia đình sẽ gắn `isFamily` cho gần như mọi câu phủ định trong corpus — đúng những câu đáng lẽ là `isNegated`. Hai loại assertion đá nhau bằng đúng một chuỗi ký tự.

Sau khi áp ranh giới từ, con số thật nhỏ hơn nhiều so với PRD ước lượng (381):

| Cue | Lần | Cue | Lần |
|---|---|---|---|
| mẹ | 30 | người nhà | 9 |
| gia đình | 17 | cha | 3 |
| ông | 14 | bà | 3 |
| | | bố | 1 |

**Tổng 80 cue / 36 file.** Lọc tiếp còn **35 câu** vừa có cue gia đình vừa có từ chỉ bệnh. Soi tay 4 câu đầu thì **3 là bẫy**:

| File | Câu | Vì sao KHÔNG phải isFamily |
|---|---|---|
| 1 | "trẻ mắc bệnh là do nhận gen lặn bất thường… từ bố và/hoặc mẹ" | Cơ chế di truyền, không ai trong nhà đang mắc |
| 2 | "cha mẹ cần đưa trẻ đến bệnh viện ngay khi trẻ sốt cao…" | Lời khuyên, cha mẹ là người thực hiện |
| 5 | "bà ấy cho biết có một chút đau khi sờ nắn…" | "bà ấy" = **chính bệnh nhân**, không phải bà nội/ngoại |
| 6 | "người nhà nhận thấy bệnh nhân có biểu hiện bất thường" | Người nhà là **người quan sát**, bệnh là của BN |

⇒ `isFamily` thật trong corpus này gần như bằng 0. Quy ước **mặc định rỗng** không chỉ là chiến thuật ăn điểm Jaccard — nó là mô tả đúng dữ liệu.

### Negation: 21% cue "không" chứng minh được là không phủ định

Trong 561 lần chữ "không", **119 lần (21%)** nằm trong cụm cố định không phủ định gì:

`không được` 24 · `không đặc hiệu` 21 · `không rõ` 18 · `không thể` 16 · `không phải` 11 · `không xác định` 10 · `không nên` 7 · `không khí` 7

Nguy hiểm nhất vẫn là **`không đặc hiệu`** — nó là **thành phần của chính tên bệnh trong ICD-10**: **2.487 dòng** trong bảng chứa cụm này, gồm cặp kinh điển `I50 Suy tim` / `I50.9 Suy tim, không đặc hiệu`. Matcher ngây thơ sẽ gắn `isNegated` cho đúng cái chẩn đoán mà nó là một phần — và nếu cắt span tại chữ "không" thì mất luôn mã I50.9.

442 lần còn lại chỉ là **ứng viên**, chưa phải phủ định thật — nhiều trường hợp là lời khuyên hành vi ("không tự ý mua thuốc", "không dùng long não"), tức phủ định một **hành động**, không phủ định một **concept y tế**.

Cue khác: `chưa` 54 · `âm tính` 20 · `phủ nhận` 16 · `loại trừ` 1.

### Historical: nên lấy theo phạm vi mục, không theo cue cục bộ

270 cue / 73 file (`tiền sử` 138 · `trước khi nhập viện` 76 · `trước đây` 16 · `cách đây` 9).

Nhưng tín hiệu mạnh hơn là **tiêu đề mục**: 58 file có mục "tiền sử", 55 file "tiền sử bệnh", 22 file "thuốc trước khi nhập viện", 23 file "bệnh sử". Mọi concept nằm trong phạm vi mục đó gần như chắc chắn là `isHistorical` — luật này chính xác hơn và rẻ hơn cue cục bộ.

---

## 4. Near-duplicate: 22 cluster / 56 file (PRD đếm thiếu)

Jaccard 8-gram > 0,25, gom bằng union-find (transitive closure) → **49 cặp, 22 cluster chứa 56 file, 44 file lẻ**.

Cặp mạnh nhất: **[86,94] J=0,90** · [76,83] 0,88 · [75,84] 0,85 · [67,94] 0,80 · [67,86] 0,79 · [7,9] 0,76.

PRD ghi cặp mạnh nhất là [67,86] J=0,80 và [7,9] J=0,76 — cả hai tái lập được, nhưng PRD **bỏ sót file 94** vốn gần 86 hơn (0,90). Vì clustering là transitive, sót một cặp làm vỡ cả cluster.

| Cluster | Files | | Cluster | Files |
|---|---|---|---|---|
| C01 (5) | 35, 56, 67, 86, 94 | | C12 (2) | 37, 48 |
| C02 (4) | 14, 19, 28, 52 | | C13 (2) | 39, 47 |
| C03 (4) | 30, 44, 76, 83 | | C14 (2) | 42, 62 |
| C04 (3) | 13, 16, 20 | | C15 (2) | 43, 63 |
| C05 (3) | 21, 32, 79 | | C16 (2) | 49, 65 |
| C06 (3) | 23, 45, 50 | | C17 (2) | 51, 70 |
| C07 (3) | 41, 59, 60 | | C18 (2) | 55, 93 |
| C08 (3) | 53, 57, 58 | | C19 (2) | 72, 98 |
| C09 (2) | 6, 11 | | C20 (2) | 73, 74 |
| C10 (2) | 7, 9 | | C21 (2) | 75, 84 |
| C11 (2) | 12, 15 | | C22 (2) | 80, 95 |

**Hệ quả:** rủi ro leak lớn hơn PRD nghĩ — 56 file (không phải 42) không được phép chia hai phía dev/eval.

---

## 5. Nhánh RxNorm — trạng thái thật của repo

### 5.0 Hai nguồn đang chồng lấn, một cái đã bị xóa khỏi đĩa

`git status` báo `D data/knowledge_base/RXNORM.csv`. File **vẫn còn trong git HEAD** (commit `a039dfe`, đúng 637.977 dòng như PRD ghi) nhưng **không còn trên đĩa**; thay vào đó là `RxNorm_full_07062026/` untracked. Phải chốt một nguồn rồi commit — để lẫn lộn thì pipeline gãy trên máy khác, đúng kịch bản bị loại vì BTC không cài lại được.

| | `RXNORM.csv` (git HEAD) | `RXNCONSO.RRF` (trên đĩa) |
|---|---|---|
| Dòng | 637.977 | 1.202.603 → **202.495** sau lọc `SAB=RXNORM`+`SUPPRESS=N` |
| Nguồn | **Đa nguồn**: RXNORM 323.426 · MTHSPL 217.714 · VANDF 70.254 · MSH 25.714 · CVX 858 | Thuần RxNorm sau lọc |
| Bảng phụ | không có | **`RXNCUI.RRF`** (remap) · `RXNSTY.RRF` · `RXNREL.RRF` |
| tty nổi bật | DP 193k · SY 62k · SCD 37.980 | SY 36.286 · PSN 27.387 · **SCD 17.552** · **IN 14.648** · SCDC 14.352 · **SBD 9.696** |

**Khuyến nghị dùng RRF** — chính thống hơn và có `RXNCUI.RRF`, thứ cần đến ngay ở §5.1.

### 5.1 🔴 Mã RxNorm trong đề bài đã hết hiệu lực từ 2019

PRD ghi ví dụ `360047 ↔ Chlorpheniramine 0.4 MG/ML`. Tra `RXNCUI.RRF`:

```
360047 | RXNORM_17AA_170905F | RXNORM_19AA_190701F | 1 | 2178097
                                ^hết hiệu lực 07/2019  ^remap sang
```

Đã kiểm tra **cả hai** nguồn trong repo: `360047` **không có trong `RXNORM.csv` lẫn `RXNCONSO.RRF`**. **Không nguồn nào trong repo tái tạo được đáp án mẫu của đề.**

**Cập nhật 25/07 (nặng hơn nữa):** mã kế nhiệm `2178097` tuy có mặt trong `RXNCONSO.RRF` nhưng mang cờ **`SUPPRESS=O`** (obsolete) trong bản 07/2026:

```
2178097 | SAB=RXNORM | TTY=SCD  | SUPPRESS=O | chlorpheniramine maleate 0.4 MG/ML / ...
```

Tức là **cả chuỗi kế thừa đã chết**: mã gốc bị retire 2019, mã thay thế nay cũng obsolete. Lọc `SUPPRESS=N` — điều kiện bắt buộc để index sạch — sẽ loại luôn cả hai. Không có đường nào từ bản RxNorm trong repo dẫn tới đáp án mẫu của đề, kể cả đi qua bảng remap.

Quy mô: `RXNCUI.RRF` có 30.269 dòng — **22.330 mã đã bị remap**, 7.939 mã bị xóa hẳn. Đỉnh remap rơi vào 2009–2012.

Nếu gold label sinh từ bản RxNorm cũ mà ta retrieve từ bản trong repo → trả mã "đúng theo bản mới" nhưng **Jaccard = 0**. Mất điểm **hệ thống** ở đúng phần trọng số 0.4, không phải do model kém.

**Hai việc rẻ:** (a) hỏi BTC gold dùng bản RxNorm nào — ưu tiên ngang câu hỏi công thức metric; (b) dựng sẵn bảng remap hai chiều từ `RXNCUI.RRF` để đổi hướng mà không phải build lại index.

### 5.2 ✅ Đã chốt được TTY đích cho nhánh THUỐC

Tra ngược 6 mã trong các ví dụ của đề — **5/6 là `TTY=SCD`**:

| Mã | TTY | Chuỗi |
|---|---|---|
| 308135 | SCD | amlodipine 10 MG Oral Tablet |
| 243670 | SCD | aspirin 81 MG Oral Tablet |
| 866436 | SCD | 24 HR metoprolol succinate 50 MG Extended Release Oral Tablet |
| 197528 | SCD | clonazepam 1 MG Oral Tablet |
| 1660761 | SCD | capsaicin 0.38 MG/ML / menthol 40 MG/ML / methyl salicylate… |
| 360047 | — | đã retire (§5.1) |

⇒ **Target `SCD`, phụ `SBD`**, không phải `IN`. Ràng buộc này còn làm luôn việc của bộ lọc chất phân tích XN: SCD bắt buộc có hàm lượng + dạng bào chế nên một mention `glucose` trơ trọi trong bảng XN không khớp được gì.

Lưu ý: tôi đã thử dùng semantic type của `RXNSTY.RRF` để lọc chất phân tích một cách có nguyên tắc thay vì danh sách viết tay — **không sạch**. `glucose` và `prothrombin` đều mang nhãn *Pharmacologic Substance* y hệt `aspirin`. Bộ lọc đúng nằm ở ràng buộc TTY, không ở semantic type.

### Danh sách loại trừ quyết định con số co-reference

Với 30 file có token che, tìm tên thuốc plaintext khớp RxNorm ở chỗ khác trong cùng văn bản:

- Không lọc gì → **20/30 file "có neo"** — nhưng sai.
- Lọc chất phân tích xét nghiệm (glucose, albumin, creatinine…) → 20/30.
- **Lọc thêm `prothrombin`, `fibrinogen`, `citrate`** → **17/30**, khớp đúng PRD.

Ba file 24, 45, 87 chỉ có `prothrombin` làm "neo" — đó là **xét nghiệm PT**, không phải thuốc. Bốn chữ này là toàn bộ khác biệt giữa 20 và 17. Danh sách loại trừ không phải chi tiết phụ, nó là tham số quyết định.

**17 file có neo:** 4, 7, 9, 14, 15, 16, 19, 25, 30, 40, 41, 44, 53, 54, 64, 72, 100
**13 file không neo → `candidates: []`:** 1, 2, 18, 24, 28, 45, 46, 49, 65, 76, 83, 87, 97

Ví dụ neo tốt: `[100] aspirin` (đúng như PRD mô tả) · `[53] carvedilol, crestor, isosorbide, rosuvastatin, torsemide` · `[19] tylenol` · `[14]/[54] gleevec`.

Chất phân tích XN xuất hiện dày trong corpus và **đều có mã RxNorm** — phải chặn ở nhánh THUỐC: protein (9 file), glucose (8), troponin (8), insulin (4), cholesterol (4), creatinine (4), hemoglobin (3), bilirubin (3), lactate (3), albumin (2). Lưu ý `insulin` vừa là thuốc vừa là xét nghiệm — phải phân biệt bằng ngữ cảnh, không bằng từ điển.

---

## 6. Dev set 20 file đề xuất

**Thiết kế:** phủ hết 14 tổ hợp (thể loại × lệch NFD × có token che) — mỗi tổ hợp ít nhất 1 file — rồi bù theo tỉ lệ thể loại của corpus, với ràng buộc cứng **không hai file cùng cluster near-duplicate**.

```
1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94
```

| Thuộc tính | Dev set | Corpus |
|---|---|---|
| Số ký tự | 55.588 (27%) | 203.817 |
| Bệnh án / hỏi–đáp / khác / giáo dục | 8 / 6 / 4 / 2 | 49 / 41 / 7 / 3 |
| File lệch NFD | 6/20 | 20/100 |
| File có token thuốc che | 7/20 | 30/100 |
| Hai file cùng cluster | **0 (không leak)** | — |
| Cluster được đại diện | 8/22 + 12 file lẻ | — |

Thể loại hiếm (giáo dục, khác) được **over-sample có chủ đích** — chúng là nơi model dễ over-predict nhất, cần nhìn thấy trong dev. Nếu muốn dev phản ánh đúng tỉ lệ corpus để ước lượng điểm, dùng trọng số theo thể loại khi tính trung bình.

Chi phí gán tay ước tính: 55.588 ký tự ≈ 27% corpus, ~13,6 concept/1.000 ký tự → **~750 concept phải gán**.

---

## 7. Bốn test bắt buộc viết trước khi viết pipeline

Đây là hạ tầng, không phải model — nhưng chặn hết bốn lỗi âm thầm đã đo được ở trên:

1. **Offset**: `raw[start:end] == entity["text"]` cho **mọi** entity, đặc biệt 20 file NFD `[13,14,16,17,19,20,28,34,35,42,52,54,56,67,72,81,86,94,97,100]`. NFC hóa chỉ trong bộ nhớ để so khớp; position tính trên chuỗi thô. (File 14: raw 2.672 ký tự vs NFC 2.538 — lệch 134.)
2. **Không candidates cho non-mappable**: assert `candidates == []` với mọi span type TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM / KẾT_QUẢ_XÉT_NGHIỆM. Đây là lá chắn cho vấn đề chương R ở §2.
3. **Tên nhãn đầy đủ có dấu**: `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM` — không viết tắt. PRD ghi nhận lỗi này đã làm hỏng toàn bộ 471 record một lần.
4. **Cue có ranh giới từ**: regex `(?<![\wăâđêôơư])ông\b`, không phải `"ông " in text`. Bằng chứng: 630/644 false positive.

---

## 8. Điều chỉnh lộ trình PRD

| # | Việc theo PRD | Điều chỉnh sau khi đo |
|---|---|---|
| 1 | Gazetteer ICD nguyên văn | **Giữ, nhưng hạ kỳ vọng.** Không phải "chính xác tuyệt đối": 27% mention là chương R, bảng có tên cắt cụt và dòng rác. Phải gate bằng entity type, stoplist tên ngắn, lọc `Hiệu lực=Có`, xử lý hậu tố `*`/`†` |
| 2 | Rerank LLM trong top-5 | Giữ nguyên. Chỉ áp cho 6 file gazetteer không phủ + mention dân dã |
| 3 | Nhánh RxNorm + co-reference | **Thêm việc chưa có trong PRD:** dựng `RXNORM.csv` từ RRF (repo không có sẵn). Chốt danh sách loại trừ chất phân tích XN — nó quyết định 20 vs 17 file có neo |
| 4 | Xác nhận metric với BTC | Không đổi — vẫn là blocker số 1 |
| 5 | Index bảng thật + đo lại Recall@k | Không đổi. Lưu ý bảng thật có 5,8% mã phi chuẩn cần chuẩn hóa trước khi index |
| 6 | Dev set 20 file | **Xong** — danh sách ở §6, 0 leak, phủ 14/14 tổ hợp rủi ro |
| 7 | Tuning α, THRESH | Mở khóa được sau khi gán nhãn dev set |

---

## Phụ lục — cách tái lập

Mọi số liệu đo bằng Python thuần trên `data/test/*.txt`, `data/knowledge_base/ICD10.csv` (`skiprows=4`, `encoding=utf-8-sig`) và `RxNorm_full_07062026/rrf/RXNCONSO.RRF` (phân tách `|`, lọc cột 12 `sab=RXNORM`, cột 17 `suppress=N`).

Tham số dùng: near-duplicate = Jaccard trên tập 8-gram từ, ngưỡng 0,25, gom transitive; gazetteer = longest-match không chồng lấn, có kiểm tra ranh giới ký tự alphanumeric hai đầu, so khớp trên chuỗi NFC lowercase.
