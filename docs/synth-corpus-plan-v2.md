# Kế hoạch triển khai v2 — nâng span recall bằng corpus tổng hợp + tagger lai

> **Thay thế** [`synth-corpus-plan.md`](synth-corpus-plan.md) (gọi là **v1**).
> **Đối tượng đọc:** agent thực thi, bắt đầu từ đầu, chưa biết bối cảnh dự án.
> **Trạng thái:** chưa triển khai.
> **Quy ước:** mọi con số trong tài liệu là **đã đo**. Số đo mới trong phiên
> khảo sát v2 đánh dấu **★**; số kế thừa từ v1/PRD không đánh dấu và đã được
> kiểm lại (§0.3).

---

## 0. Vì sao có v2

### 0.1 v1 đúng nguyên lý nhưng lệch trọng tâm

v1 chốt ba điều **đúng và giữ nguyên trong v2**:

1. **Annotation-first** (có nhãn trước → sinh văn bản sau). Cắt đúng hai nguồn
   nhiễu đã gây sự cố thật: gold dựng bằng đồng thuận LLM dự đoán *sai dấu*
   ([`gold-chan-doan-protocol.md`](gold-chan-doan-protocol.md)), và lớp bug
   offset (`sample_output.json` lệch 19/19 mục; 20/100 file `data/test` không NFC).
2. **Giá trị nằm ở độ đa dạng CÁCH NÓI, không ở số lượng tài liệu.**
3. **Kỷ luật cổng:** chấm trên `gold_real` và chỉ `gold_real`; không đạt thì ghi
   kết quả âm và giữ pipeline luật.

Chỗ v1 lệch: nó đo trần theo **thành phần điểm** (recall / precision /
candidates / assertions) nhưng chưa bao giờ đo trần theo **nhánh nhãn**. Khi đo
thêm chiều đó, thứ tự ưu tiên đảo ngược.

### 0.2 Trần theo nhánh — số đo mới ★

Chạy `solve` trên `data/probe/gold_real/text`, rồi thay **từng nhánh** bằng đáp
án và giữ nguyên phần còn lại, chấm bằng chính
[`scoring.py`](../src/smart_medic/stages/scoring.py):

| nhánh | gold | recall | precision | **Δ final nếu làm đúng hoàn toàn** |
|---|---:|---:|---:|---:|
| **TÊN_XN + KẾT_QUẢ_XN** | 91 | 0,586 / 0,424 | 0,583 / 0,429 | **+0,1544** |
| **TRIỆU_CHỨNG** | 94 | 0,670 | 0,646 | **+0,1337** |
| CHẨN_ĐOÁN | 74 | 0,851 | 0,742 | +0,0960 |
| **THUỐC** | 74 | **0,865** | **0,942** | **+0,0572** |

`final` hiện tại trên `gold_real` = **0,4327** (text 0,463 · assertions 0,426 ·
candidates 0,415).

Ba hệ quả:

- **Nhánh XÉT NGHIỆM là chỗ mất điểm lớn nhất** và là nhánh v1 dành ít công
  nhất (hai câu ở Bước 1).
- **Nhánh THUỐC đã mạnh nhất** (P 0,942) và có trần thấp nhất, nhưng v1 dành cho
  nó cả §4.4, cột giữa §4.1, bước 2a và mục rủi ro §7.1.
- XÉT NGHIỆM + TRIỆU_CHỨNG = **+0,288** trần, và cả hai **bắt buộc `candidates`
  rỗng** → bắt đúng span là ăn trọn cả ba thành phần (0,3 + 0,3 + 0,4), không
  cần KB, không cần linking, không cần assertion.

### 0.3 Bốn phát hiện khác từ khảo sát v2 ★

| # | phát hiện | bằng chứng |
|---|---|---|
| A | **Tài sản ATC gần như vô giá trị trên phân bố đích.** 346/608 tên Việt xuất hiện **0 lần** trong `gold_real`, **0 lần** trong `gold_batch1`, và **3 tên trên 4/100 file** `data/test` (`doxycyclin`, `trimetazidin`, `furosemid`). | khớp `delta = 0,000` tuyệt đối ở cả 5 bộ probe trong [`atc-vi-enrich.json`](reports/atc-vi-enrich.json) |
| B | **654 term ATC đã nạp KB nhưng gazetteer không lấy.** [`ner.py:223`](../src/smart_medic/stages/ner.py:223) lọc `t.term_type IN ('IN','PIN')`, chúng mang `term_type='atc_vi_name'`. Sửa được bằng một dòng SQL — nhưng theo (A), lợi ích ~4 mention/100 file. | truy vấn `kb.sqlite` |
| C | **Nhánh THUỐC thật là bài toán khác hẳn.** 50/74 mention `gold_real` **không có mã**: `***********` bị che, hoặc biệt dược Việt (`Aquima`, `Simenic`, `Pimperam`) không có trong RxNorm. | đếm trên `annotations_gold` |
| D | **KẾT_QUẢ_XN thật phần lớn KHÔNG phải số.** `dương tính`, `chưa phát hiện bất thường`, `nguyên vẹn`, `đang chờ`, `ST chênh lên / chênh xuống`, `túi mật căng to với dịch quanh túi mật`. `_MEASURE` trong `labtest.py` là regex *số + đơn vị* nên **không thể** bắt được lớp này → đó là lý do recall 0,424. | 26 cặp `TÊN→KQ` kề nhau ở `gold_real`, 163 cặp ở `gold_batch1` |

Số kế thừa đã kiểm lại và **khớp chính xác**: `data/test` 20/100 không NFC ·
30/100 có `***` · 90/100 gạch đầu dòng · 97/100 mẫu `NHÃN:` · trung vị 1.838 ký
tự. Ba bộ gold: 273 / 333 / 858 span.

### 0.4 Bảy khoảng trống của v1 mà v2 phải đóng

| # | khoảng trống v1 | v2 xử lý ở |
|---|---|---|
| G1 | ưu tiên đảo ngược so với trần theo nhánh | §1, Phase 1 |
| G2 | ATC bị thổi phồng | §2.4, Phase 2b (hạ cấp) |
| G3 | mã + assertion sinh ra **không module nào tiêu thụ** | §2.6 |
| G4 | không có **span âm**, trong khi precision là đòn bẩy #2 (+0,120) | Phase 2d |
| G5 | rò rỉ `gold_real` vào bộ sinh rồi lại dùng làm cổng | §4.2 |
| G6 | cổng ±0,03 trên n = 9 không có khoảng tin cậy | Phase 0, §4.1 |
| G7 | khung câu bịa ra trong khi 91 file thật đang nằm không | Phase 2d |
| G8 | đóng gói `torch` xung đột với PRD §5 | Phase 6 |

---

## 1. Mục tiêu

### 1.1 Mục tiêu cuối

**Hoàn thành toàn bộ 7 phase**, và nộp cấu hình tốt nhất đo được.

| mức | ngưỡng trên `gold_real` | ý nghĩa |
|---|---|---|
| **sàn chấp nhận** | `Δfinal > 0` với **cận dưới CI 95% > 0** | cấu hình mới thay baseline luật |
| **mục tiêu** | `final ≥ 0,50` (từ **0,4327**) | đạt được thì tốt, không đạt vẫn đi tiếp |
| **kịch trần** | `final ≈ 0,72` | tổng trần bốn nhánh §0.2 |

Không đạt mục tiêu **không** làm dừng phase nào. Toàn bộ kế hoạch vẫn chạy hết;
§4.0 giải thích cơ chế.

### 1.2 Mục tiêu theo nhánh, gắn với trần đã đo

| nhánh | hiện tại | mục tiêu | Δ final kỳ vọng | phương tiện |
|---|---|---|---|---|
| KẾT_QUẢ_XN | R 0,424 · P 0,429 | R ≥ 0,65 · P ≥ 0,60 | +0,03…0,05 | **luật** (Phase 1) |
| TÊN_XN | R 0,586 · P 0,583 | R ≥ 0,72 · P ≥ 0,65 | +0,02…0,03 | **luật** (Phase 1) |
| TRIỆU_CHỨNG | R 0,670 · P 0,646 | R ≥ 0,80 · P ≥ 0,68 | +0,03…0,05 | corpus + tagger |
| CHẨN_ĐOÁN | R 0,851 · P 0,742 | P ≥ 0,80, R không giảm | +0,01…0,02 | corpus + span âm |
| THUỐC | R 0,865 · P 0,942 | **giữ nguyên** | 0 | không đụng |

### 1.3 Phi mục tiêu — ghi rõ để không trôi phạm vi

- **Không** tối ưu `gold_batch1`. Nó là bài kiểm khái quát hoá ngoài miền
  (MTSamples Mỹ, văn phong SOAP) — báo cáo riêng, không đặt cổng.
- **Không** nới luật ingest biệt dược (+146.691 concept). Chờ tín hiệu
  leaderboard, không tự quyết bằng số đo nội bộ.
- **Không** bật dense retrieval. Đã đo có hại (R@20: lexical 1,000 vs dense
  0,574) — điều kiện thử lại nằm ở [`solution-backlog.md`](solution-backlog.md) S4.
- **Không** thay `linking.py`. Nhánh mã là trần +0,033, và `rerank=True` đã
  gánh 45 điểm R@1.
- **Không** đầu tư thêm vào tên thuốc tiếng Việt (§0.3 A).

---

## 2. System design

### 2.1 Nguyên lý kiến trúc: proposer → arbiter → enricher

Pipeline hiện tại là chuỗi detector nối tiếp, mỗi detector nhận `taken` rồi tự
tránh chồng lấn (`ner.detect` → `labtest.detect` → `detect_masked_drugs`). Thêm
một model vào chuỗi đó bằng cách nối thêm một mắt xích sẽ khiến **thứ tự quyết
định thắng thua**, mà thứ tự thì không có căn cứ đo được.

v2 tách rõ ba tầng:

```
  read_document()          ← textio, newline='', KHÔNG normalize
        │
        ▼
  ┌─────────────── PROPOSERS (song song, được phép chồng lấn) ──────────────┐
  │  P1 gazetteer KB        (ner.Gazetteer)              conf = tiên nghiệm │
  │  P2 cấu trúc xét nghiệm (labtest, MỞ RỘNG ở Phase 1) conf = theo mẫu    │
  │  P3 thuốc bị che        (ner.detect_masked_drugs)    conf = 1,0         │
  │  P4 tagger XLM-R        (stages/tagger.py, MỚI)      conf = softmax     │
  └────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
                    ARBITER (stages/arbiter.py, MỚI)
        chọn tập span KHÔNG chồng lấn có TỔNG TRỌNG SỐ lớn nhất
        → weighted interval scheduling, DP O(n log n)  (§2.7)
                                   ▼
                    ENRICHERS (giữ nguyên, đã đo là mạnh)
        assertion.py  (ConText/NegEx)
        linking.py    (rerank=True — BẮT BUỘC)
                                   ▼
                    check_invariants() → JSON
```

**Vì sao arbiter là thành phần riêng, không nhét vào `ner.py`.** Với 4 proposer,
xung đột span trở thành bài toán tối ưu chứ không còn là quy tắc "ai đến trước".
Tách ra thì: (a) thay đổi trọng số đo được độc lập với thay đổi proposer;
(b) `check_invariants` bất biến 2 (không chồng lấn) trở thành **đúng theo kiến
tạo** thay vì phải kiểm; (c) thêm/bớt proposer không đụng code cũ.

### 2.2 Corpus tổng hợp: đồ thị bệnh án → văn bản

Giữ khung v1 §4, **đảo trọng số** và **thêm hai thành phần**:

| thành phần | v1 | v2 | lý do |
|---|---|---|---|
| nút CHẨN_ĐOÁN / TRIỆU_CHỨNG | LLM sinh cách nói | **giữ** | trần +0,134 / +0,096 |
| nút **XÉT NGHIỆM** | "lấy hạt giống từ gold_real" | **danh mục panel tất định, KHÔNG LLM** | trần +0,154, §0.3 D |
| nút THUỐC | ATC, cả một mục | **hạ cấp: 10% tài liệu, chỉ để giữ ngữ cảnh** | §0.3 A/C |
| khung câu | 8 họ tự nghĩ | **khai thác 91 file `data/test` làm khuôn** | G7 |
| **span âm (distractor)** | không có | **bắt buộc** | G4, precision +0,120 |
| tiêm nhiễu | theo §3.2 | giữ, nhưng phần lớn miễn phí nếu dùng khuôn thật | G7 |

### 2.3 Nhánh XÉT NGHIỆM — thiết kế chi tiết (thành phần quan trọng nhất)

Số đo hình dạng thật ★ (cặp `TÊN_XN` → `KẾT_QUẢ_XN` kề nhau):

| dấu ngăn | gold_real | gold_batch1 |
|---|---:|---:|
| `": "` | 10/26 | 57/163 |
| `" "` | 8/26 | 85/163 |
| văn xuôi (`" là "`, `" cho thấy "`, `" đo được là "`…) | 6/26 | ~19/163 |
| xuống dòng + gạch đầu dòng | 2/26 | ~2/163 |

**Taxonomy giá trị** — đây là chỗ `labtest.py` hiện thiếu (§0.3 D):

| lớp giá trị | ví dụ thật | luật hiện có bắt được? |
|---|---|---|
| số + đơn vị | `5,38 G/l` · `51,4%` · `121/63` | ✅ `_MEASURE` |
| số trần | `623` · `1.0` · `75` · `0.7` | ⚠️ chỉ khi có nhãn `:` |
| **định tính** | `dương tính` · `(+)` · `(-)` · `âm tính` | ❌ |
| **mô tả bình thường** | `nguyên vẹn` · `chưa phát hiện bất thường` · `trong giới hạn bình thường` | ❌ |
| **mô tả bất thường** | `túi mật căng to với dịch quanh túi mật` · `ST chênh lên / chênh xuống` · `Sóng T đảo` · `Q bệnh lý` | ❌ |
| **xu hướng** | `tăng men gan nhẹ` · `cải thiện đến 20.6` · `giảm` | ❌ |
| **trạng thái** | `đang chờ` · `chưa có kết quả` | ❌ |

**Danh mục tên xét nghiệm** — `data/curated/lab_panels.v1.yaml`, dựng **tất
định**, không LLM, không lấy từ `gold_real` (G5). Ba nguồn hợp pháp:

1. **Kiến thức panel chuẩn** (công thức máu, sinh hoá, đông máu, viêm gan, tim
   mạch, nước tiểu, chẩn đoán hình ảnh) — kiến thức chung, viết tay một lần.
2. **Trích từ 91 file `data/test` chưa dùng** bằng mẫu `^NHÃN:` (97/100 file có)
   — đây là **chuỗi bề mặt thật**, không phải nhãn, nên không rò rỉ đáp án.
3. **`gold_batch1`** (858 span, 218 `TÊN_XN`) — ngoài miền nhưng lâm sàng thật,
   và **không phải cổng** nên dùng làm nguồn được.

Mỗi mục panel:

```yaml
- id: cbc_wbc
  names_vi:  ["Bạch cầu", "Số lượng bạch cầu", "công thức bạch cầu"]
  names_abbr: ["WBC", "BC"]
  value:
    kind: numeric
    unit: ["K/uL", "G/L", "G/l"]
    range: [3.5, 18.0]
    decimals: 2
    decimal_sep: [",", "."]      # cả hai đều gặp thật
  qualitative: ["tăng", "giảm", "trong giới hạn bình thường"]
```

### 2.4 Nhánh THUỐC — hạ cấp có chủ đích

Giữ ánh xạ tất định `tên Việt → ATC cấp 5 → RxCUI` vì nó đúng và đã có, nhưng:

- **Không** dùng làm nguồn đa dạng bề mặt chính (§0.3 A).
- Bổ sung lớp bề mặt **thật sự có trong phân bố đích** (§0.3 C): token bị che
  `***` độ dài trung vị 12, và biệt dược Việt **không có mã** (`candidates` rỗng
  là đáp án đúng, và Jaccard rỗng-gặp-rỗng = 1,0).
- Một dòng sửa gazetteer (§0.3 B) đưa vào Phase 1 vì rẻ, nhưng **không tính vào
  kỳ vọng điểm**.

### 2.5 Span âm — thành phần v1 thiếu hoàn toàn

Trần precision là +0,120, và tôi đếm được **102 span thừa** trên `gold_real` ★.
[`gold_real/README.md`](../data/probe/gold_real/README.md) đã có sẵn **danh mục
bẫy hoàn chỉnh** — nhưng nó là **file cổng**, nên không được dùng làm nguồn
sinh (G5). Cách hợp lệ: lấy **lớp** của bẫy (kiến thức chung về thể loại), không
lấy **thực thể** cụ thể.

`data/curated/distractors.v1.yaml` — 6 lớp:

| lớp | sinh từ | ví dụ (tự nghĩ, KHÔNG copy từ README) |
|---|---|---|
| thủ thuật / can thiệp | kiến thức chung | `đặt catheter`, `chọc dò màng phổi` |
| thiết bị y tế | kiến thức chung | `máy thở`, `ống thông tiểu` |
| thực phẩm / TPCN | kiến thức chung | `sữa chua`, `nhân sâm` |
| enzyme / protein / gen | KB (tên có `[...]`) | `men gan`, `protein C` |
| **lớp thuốc chung** | 29 nhóm thuốc ATC tiếng Việt | `thuốc lợi tiểu`, `kháng sinh` |
| rác OCR / splice | biến đổi cơ học chuỗi có sẵn | lặp cụm, hoán vị dấu |
| vị trí giải phẫu trần | SNOMED `Finding site` (§2.6) | `vùng thượng vị` |

Chèn vào tài liệu sinh **không kèm nhãn**. Đây là dữ liệu dạy model *khi nào
KHÔNG bắn* — chính là thứ distant supervision từ từ điển không bao giờ có
(xem `AutoNER`, §6).

### 2.6 Ba tài sản bị bỏ phí của v1 — quyết định dứt khoát

| tài sản | v1 | v2 |
|---|---|---|
| **mã** trong corpus | sinh ra, không ai dùng | **để dành**, xuất ra `data/synth/v1/pairs.jsonl` làm tập huấn luyện re-ranker; **treo lại**, nối vào [`s1-embedding-plan.md`](s1-embedding-plan.md), KHÔNG làm trong v2 |
| **assertion** trong corpus | sinh ra, không ai dùng | **dùng làm bộ thử `assertion.py`** — cùng `gold_batch1` (188 assertion, dày gấp 4 `gold_real`). Không huấn luyện; chỉ để tìm ca hỏng của luật ConText |
| **SNOMED** | loại vì "không có quan hệ thuốc→bệnh" | **kết luận đó đúng nhưng hỏi sai nhánh.** `Interprets` (41.441 cạnh) nối *bệnh ↔ quan sát/xét nghiệm* — đúng nhánh +0,154; `Finding site` (109.781) cho vị trí giải phẫu — nguồn distractor. **Khảo sát ở Phase 2, không cam kết**; chi phí dịch tên Anh→Việt là rào cản thật, nhưng §0.3 D cho thấy tên xét nghiệm trong văn bản Việt **phần lớn đã là viết tắt tiếng Anh** (`Troponin I/T`, `CK-MB`, `HBsAg`, `INR`, `BUN`) nên rào cản ở nhánh này thấp hơn nhánh thuốc rất nhiều |

### 2.7 Cấu trúc dữ liệu & giải thuật

| chỗ dùng | cấu trúc / giải thuật | vì sao | độ phức tạp |
|---|---|---|---|
| **arbiter** | **weighted interval scheduling**, DP + `bisect` trên mảng đã sắp theo `end` | chính xác bài toán "chọn tập span không chồng lấn tổng trọng số lớn nhất"; tất định; thay greedy `taken` hiện tại | O(n log n) |
| kiểm chồng lấn | thay `_free()` O(n) tuyến tính bằng `SortedList`/`bisect` trên mốc `end` | `labtest._free` hiện là O(n²) trên tài liệu dài | O(log n)/lần |
| gazetteer | **Aho–Corasick** thay quét n-gram `MAX_NGRAM` | quét một lượt, không phụ thuộc độ dài cụm dài nhất | O(len + #match) |
| từ điển bề mặt | trie / DAWG (nén hậu tố) | 633k term; tiết kiệm bộ nhớ khi nạp cả `atc_vi_name` | — |
| **offset NFC/NFD** | mảng song ánh `idx_chuẩn_hoá → idx_gốc` dựng theo **grapheme cluster** (UAX #29) | `100.txt` trộn NFC/NFD **bên trong một cụm**: `"tiền sản giật"` chỗ 16 ký tự chỗ 13. README ghi rõ "thử cả NFC lẫn NFD **cũng không đủ**" | O(len) |
| tagger → span ký tự | `offset_mapping` của HF fast tokenizer + **giải mã BIO có ràng buộc** (cấm `I-X` sau `O` hoặc sau `B-Y`) | subword-to-char là nguồn lệch offset kinh điển | O(#token) |
| lấy mẫu concept | **stratified sampling** theo chương ICD + **alias method** cho phân phối rời rạc có trọng số | quota theo chương, tất định theo seed | O(1)/lần rút |
| chọn khung câu | cumulative weights + `bisect` | như trên | O(log k) |
| **cổng thống kê** | **paired bootstrap** trên 9 tài liệu, B = 10.000, seed ghim | n = 9; điểm ước lượng vô nghĩa nếu không có CI (G6) | O(B·n) |
| WER | Levenshtein DP theo từ | đã có trong `scoring.py` | O(mn) |
| truy vết corpus | `sha256` file corpus ghi vào metadata checkpoint | PRD §8 tái lập | — |

---

## 3. Project structure

```
src/smart_medic/
├── stages/                        # pipeline giải bài (đang có)
│   ├── textio.py                  # GIỮ NGUYÊN — không đụng
│   ├── ner.py                     # sửa 1 dòng SQL (§0.3 B) + rút detect ra proposer
│   ├── labtest.py                 # ★ MỞ RỘNG mạnh — Phase 1
│   ├── assertion.py               # giữ nguyên; chỉ đo thêm
│   ├── linking.py                 # giữ nguyên (rerank=True)
│   ├── scoring.py                 # ✅ + TypeStats & Report.by_type() (Phase 0)
│   ├── solve.py                   # nối arbiter vào
│   ├── arbiter.py                 # ★ MỚI — weighted interval scheduling
│   └── tagger.py                  # ★ MỚI — inference; KHÔNG import torch ở top-level
│
├── eval/                          # ✅ ĐÃ XONG — Phase 0. CÁI THƯỚC, không phải
│   ├── __init__.py                #    thứ được đo; tách khỏi stages/ có chủ đích
│   ├── bootstrap.py               #    paired bootstrap, SEED=20260802, B=10000
│   └── harness.py                 #    chấm bộ gold + bảng theo nhánh + so hai báo cáo
│
├── synth/                         # ★ MỚI — chỉ chạy lúc BUILD, không vào runtime
│   ├── __init__.py
│   ├── schema.py                  # Concept · Span · Frame · Doc (dataclass, slots)
│   ├── sample.py                  # lấy mẫu concept từ kb.sqlite, phân tầng
│   ├── surface/
│   │   ├── lab.py                 # ★ danh mục panel — TẤT ĐỊNH
│   │   ├── drug.py                # ATC + mask + biệt dược không mã
│   │   └── frozen.py              # đọc surface_forms.v1.jsonl (đã đóng băng)
│   ├── frames.py                  # họ khung + khuôn khai thác từ data/test
│   ├── distractor.py              # ★ span âm
│   ├── noise.py                   # NFD 20% · mask 30% · gạch đầu dòng · rác OCR
│   ├── render.py                  # đồ thị → văn bản, GHI OFFSET LÚC CHÈN
│   └── export.py                  # xuất đúng định dạng gold_real
│
├── train/                         # ★ MỚI — optional dep "train", không vào runtime
│   ├── dataset.py                 # .json corpus → BIO, offset-safe
│   ├── train_tagger.py            # XLM-R token classification
│   └── calibrate.py               # ngưỡng tin cậy trên dev TỔNG HỢP
│
└── cli.py                         # + smk synth · smk train · smk eval solve

data/
├── curated/                       # đóng băng, commit vào git, có .sha256
│   ├── vi_synonyms.yaml           # (đang có)
│   ├── lab_panels.v1.yaml         # ★ nguồn nhánh +0,154
│   ├── distractors.v1.yaml        # ★ span âm
│   ├── frames.v1.yaml             # họ khung + khuôn từ data/test
│   ├── surface_forms.v1.jsonl     # ★ đầu ra LLM ĐÃ ĐÓNG BĂNG (chỉ CĐ + TC)
│   ├── drug_surface_atc.v1.jsonl  # 608 cặp tên Việt → RxCUI
│   ├── dose_forms_vi.v1.txt       # 71 dạng bào chế — KHÔNG vào KB
│   └── drug_groups_vi.v1.txt      # 29 nhóm thuốc — KHÔNG vào KB
├── synth/v1/
│   ├── text/                      # NNN.txt
│   ├── annotations/               # NNN.json  (cùng schema gold_real)
│   ├── pairs.jsonl                # (mention → mã) để dành cho S1
│   ├── manifest.json              # seed · sha256 · phân bố nhiễu đo được
│   └── splits.json                # train / dev TỔNG HỢP (không đụng gold_real)
└── artifacts/
    └── tagger/v1/                 # weights + config + revision + corpus sha256

docs/reports/
├── synth-baseline.json            # mốc trước mọi thay đổi (theo nhánh + CI)
├── phase1-labtest.json
├── phase2-corpus-stats.json
├── phase3-tagger.json
├── phase4-arbiter.json
└── phase5-gate.json               # kể cả khi ÂM

tests/
├── unit/test_synth_render.py      # bất biến offset
├── unit/test_synth_noise.py       # phân bố nhiễu
├── unit/test_arbiter.py           # tối ưu + tất định
├── unit/test_labtest_values.py    # taxonomy giá trị mới
├── unit/test_tagger_offsets.py    # subword → ký tự
└── integration/test_synth_gold_format.py   # corpus chấm được bằng scoring.py
```

**Ranh giới quan trọng:** `synth/` và `train/` **không bao giờ** được import từ
`stages/` (trừ `tagger.py` đọc weights). Đó là ranh giới build/runtime, cùng
tinh thần với ranh giới ĐẮT/RẺ của KB pipeline, và là điều kiện để Phase 6 đóng
gói được image runtime không có `torch`.

---

## 4. Kế hoạch theo phase

Tổng: **10–11 ngày công**. **Mọi phase đều được làm tới cùng** — không phase nào
có tiêu chí dừng.

### 4.0 Hai loại cổng — đọc trước khi làm bất cứ phase nào

v1 và bản v2 đầu tiên trộn hai thứ khác hẳn nhau vào cùng một chỗ gọi là "cổng".
Tách ra thì cả kế hoạch chạy hết mà không mất gì:

| | **cổng CHẶN** | **cổng ĐỊNH TUYẾN** |
|---|---|---|
| hỏi điều gì | *code có đúng không?* | *thành phần này có đáng ship không?* |
| ví dụ | span lệch offset · span chồng lấn · `candidates` không rỗng ở nhãn cấm · bẫy `gold_real` bị phủ · không tái lập | Δ điểm · recall · F1 |
| không đạt nghĩa là | **có bug** → sửa rồi chạy lại | **có số đo** → ghi lại, tắt cờ, **đi tiếp** |
| có làm dừng phase không | có, cho tới khi sửa xong | **không bao giờ** |
| số lượng | ít, cố định, không thương lượng | nhiều, ngưỡng đã nới ở bản này |

**Cơ chế thay cho "dừng": cờ cấu hình.** Mỗi thành phần mới được gói sau một cờ
trong `data/curated/pipeline.v1.yaml`:

```yaml
labtest_extended:  true      # Phase 1
tagger:            true      # Phase 3
arbiter_model_weight: 1.0    # Phase 4 — đặt 0.0 là pipeline luật thuần
distractor_trained: true
```

Thành phần không qua cổng định tuyến thì **vẫn được xây, vẫn được test, vẫn
được commit**, chỉ là cờ mặc định `false`. Phase 5 bật/tắt các cờ này để chọn
cấu hình nộp. Nhờ vậy:

- kế hoạch chạy hết 7 phase trong **mọi** kịch bản;
- không có công sức nào bị vứt — thứ không ship hôm nay vẫn nằm sẵn cho vòng 2;
- kỷ luật đo giữ nguyên: cấu hình nộp vẫn phải **thắng baseline có bằng chứng**.

**Cái giá phải trả, nói thẳng.** Càng nhiều cấu hình đem so trên `gold_real`
(chỉ 9 file) thì càng dễ **overfit bằng cách chọn**: thử 20 cấu hình rồi lấy cái
cao nhất thì con số cao nhất đó phần lớn là nhiễu. Nên §5 có thêm **quy tắc 11**:
đăng ký trước **tối đa 4 cấu hình** trước khi nhìn `gold_real`, sàng sơ bộ bằng
dev tổng hợp và `gold_batch1`.

### 4.1 Ngưỡng đã nới so với bản đầu

| phase | bản đầu | **bản này** |
|---|---|---|
| 1 | Δfinal ≥ +0,03; precision mỗi nhãn ≤ −0,03; **dừng nếu Δ < +0,015** | **Δfinal > 0** (CI > 0); **bỏ ràng buộc precision riêng**; **không có tiêu chí dừng** |
| 2 | nhiễu ±5pp · span âm ≥ 25% · duyệt tay ≥ 90/100 · mới ≥ 60% | nhiễu **±10pp** · span âm **≥ 15%** · duyệt tay **≥ 80/100** · mới **≥ 40%** |
| 3 | F1 dev ≥ 0,90 | F1 dev **≥ 0,80** |
| 4 | precision mỗi nhãn ≤ −0,02 | **Δfinal ≥ 0** so với cấu hình Phase 1 |
| 5 | `final` ≥ 0,50 **là cổng** | `final` ≥ 0,50 **là mục tiêu**; cổng là **Δ > 0 với CI > 0** |

**Vì sao bỏ ràng buộc precision riêng lại là siết chứ không phải nới.** Ràng
buộc kép (recall lên **và** precision không tụt) có thể chặn một thay đổi có
lợi ròng, đồng thời cho lọt một thay đổi hoà vốn. `Δfinal` kèm CI đã bao trọn cả
hai chiều — dùng một tiêu chí *tổng hợp* vừa dễ đạt hơn vừa đúng hơn.

### Phase 0 — Hạ tầng đánh giá (0,5 ngày) · ✅ **ĐÃ XONG**

Không có phase này thì mọi cổng ở v1 đều không đo được (G6).

> **Kết quả:** `smk eval solve` · `smk eval compare` ·
> [`docs/reports/synth-baseline.json`](reports/synth-baseline.json).
> Cổng CHẶN pass: ba lần chạy cho `sha256` y hệt; `gold_real` tái tạo đúng
> **0,4327**; bảng theo nhánh tái tạo đúng §0.2; **0 vi phạm bất biến** trên cả
> ba bộ.
>
> ★ Phase này lập tức trả lời một câu hỏi của chính nó: mô phỏng một thay đổi
> `Δ = +0,053` trên `gold_real` — **vượt cổng `≥ +0,03` của v1** — thì CI 95%
> ra `[−0,024, +0,131]`, tức **vẫn nằm trong nhiễu**. Cổng cũ sẽ cho nó qua.

**Việc:**
1. `smk eval solve --gold <dir> --report <json>` — chấm một bộ gold, xuất:
   `final`, ba thành phần, **và bảng theo nhánh** (recall/precision/F1 mỗi nhãn).
2. **Paired bootstrap** trên tài liệu, B = 10.000, seed ghim → CI 95% cho `final`
   và cho `Δfinal` giữa hai lần chạy.
3. Chốt `docs/reports/synth-baseline.json` cho cả 3 bộ gold, báo cáo **riêng
   từng bộ**.
4. Xử lý khác cấu trúc: `gold_batch1` để nhãn ở `annotations/`, hai bộ kia ở
   `annotations_gold/`.

**Cổng CHẶN** (đây là kiểm tra cái thước, không phải kiểm tra hiệu năng — sai
nghĩa là có bug, không phải có quyết định):
- chạy lại 3 lần cho ra số **y hệt** (tất định);
- `final` trên `gold_real` tái tạo đúng **0,4327** và bảng theo nhánh tái tạo
  đúng §0.2.

**Cổng định tuyến:** không có. Phase này không sinh ra thành phần nào để ship.

### Phase 1 — Nhánh XÉT NGHIỆM bằng luật (1,5 ngày) · **ROI cao nhất**

Không corpus, không model, không LLM. Đây là phase phải làm ngay cả khi toàn bộ
phần còn lại của kế hoạch bị huỷ.

**Việc:**
1. `data/curated/lab_panels.v1.yaml` theo §2.3 — nguồn (1)(2)(3), **cấm** lấy từ
   `gold_real`.
2. Mở rộng [`labtest.py`](../src/smart_medic/stages/labtest.py):
   - **taxonomy giá trị** (§2.3): định tính, mô tả bình thường/bất thường,
     xu hướng, trạng thái — 5 lớp `_MEASURE` hiện không bắt được;
   - **ghép cặp `TÊN → KQ`** theo 4 dấu ngăn đã đo, ưu tiên `": "` và `" "`;
   - **từ điển viết tắt** (`BC`, `N`, `PTT`, `INR`, `BUN`, `HBsAg`…) — nhánh mà
     `TEST_HEADS` (đầu cụm tiếng Việt) không với tới;
   - giữ nguyên `SECTION_WORDS` và luật loại gạch đầu dòng (đã đo: tránh 38
     entity thừa).
3. Sửa gazetteer nhận `atc_vi_name` (§0.3 B) — một dòng, không kỳ vọng điểm.
4. Thay `_free()` O(n²) bằng `bisect` (§2.7).

**Cổng CHẶN:**
- các cụm bẫy ở `gold_real/README.md` vẫn **không có span nào phủ** (luật phủ
  lên bẫy là sai luật, không phải điểm thấp);
- 0 span lệch offset trên toàn bộ 100 file `data/test`;
- `pytest` xanh.

**Cổng ĐỊNH TUYẾN** — quyết định giá trị mặc định của cờ `labtest_extended`:

| kết quả | cờ | hành động |
|---|---|---|
| `Δfinal > 0` **và** cận dưới CI 95% > 0 | `true` | ship |
| `Δfinal > 0` nhưng CI chạm 0 | `true` | ship, ghi rõ là **biên**, xét lại ở Phase 5 |
| `Δfinal ≤ 0` | `false` | giữ code, tắt cờ, **đi tiếp Phase 2** |

Không có tiêu chí dừng. Ghi số theo nhánh vào `phase1-labtest.json` trong cả ba
trường hợp; báo cáo riêng `gold_batch1` (218 `TÊN_XN` + 202 `KQ_XN`) để quan sát.

> Ràng buộc `precision` riêng đã **bỏ** — `Δfinal` kèm CI đã tính cả hai chiều
> (§4.1).

### Phase 2 — Bộ sinh corpus (3 ngày)

**2a — Khung + bất biến (test trước, code sau).** `schema.py`, `render.py`,
`export.py`. Bốn bất biến kiểm bằng test:
1. `text[start:end] == span.text` với **mọi** span (tất cả tài liệu);
2. span không chồng lấn;
3. `candidates` rỗng với `TRIỆU_CHỨNG` / `TÊN_XN` / `KẾT_QUẢ_XN`;
4. corpus chấm được bằng `scoring.py` mà không sửa gì.

Dùng lại `solve.check_invariants` — nó đã cài sẵn 1–3.

**2b — Bề mặt tất định.** `surface/lab.py` (chính), `surface/drug.py` (phụ,
10% tài liệu). Không gọi LLM. Không cần cổng duyệt tay.

**2c — Bề mặt LLM, chỉ CHẨN_ĐOÁN + TRIỆU_CHỨNG.** Gọi **một lần**, đóng băng ra
`surface_forms.v1.jsonl` + `.sha256`, commit. Dùng model **khác họ** với model
dùng ở pipeline (sai số không tương quan).

> **Hai phép đo bắt buộc ghi lại** (ngưỡng đã nới, và cả hai đều **không** làm
> dừng phase):
> - *hợp lý y khoa*: duyệt tay **100 cặp `(cách nói → mã)` ngẫu nhiên**, **≥ 80**
>   hợp lý. Dưới ngưỡng → siết prompt, sinh lại **đúng một lần**, rồi đi tiếp
>   với kết quả tốt hơn trong hai lần.
> - *độ mới*: **≥ 40%** cách nói **KHÔNG khớp** term nào trong gazetteer KB.
>   Đây là phép đo chống vòng lặp tự khen (v1 §3.1). Dưới 40% vẫn đi tiếp, nhưng
>   **ghi vào `phase2-corpus-stats.json`** vì nó dự báo Phase 3 sẽ ít tác dụng —
>   Phase 5 cần con số này để diễn giải kết quả.

**2d — Span âm + khuôn thật.** `distractor.py` theo §2.5. `frames.py` khai thác
**91 file `data/test` chưa dùng** làm khuôn: giữ khung câu, thay cụm y khoa
bằng span sinh ra.

> ⚠️ Ranh giới PRD §5. Dùng **văn phong** làm khuôn **không phải** hard-code
> output theo input. Nhưng phải: (a) giữ 20 file làm holdout khung, không đưa vào
> bộ sinh; (b) không bao giờ copy nguyên câu chứa khái niệm y tế; (c) ghi rõ vào
> README nộp BTC. Nếu thấy rủi ro, dùng `gold_batch1` làm nguồn khung thay thế.

**2e — Nhiễu + thống kê.** NFD 20% · mask `***` 30% (độ dài trung vị 12) · gạch
đầu dòng 90% · `NHÃN:` 97% · giọng hỏi–đáp 49% · trung vị độ dài 1.838.

**Cổng CHẶN** (vi phạm = corpus hỏng, huấn luyện trên nó là học cái sai):
- 4 bất biến pass trên **100%** tài liệu;
- khái niệm `linking.py` không tra được mã bị **lọc tự động** khỏi corpus —
  không phải cổng mà là **một bước trong `render.py`**; sinh mã pipeline không
  trả về được là tự dựng trần điểm cho chính mình (v1 §7.1).

**Cổng ĐỊNH TUYẾN** (ngưỡng đã nới; không đạt thì ghi số và đi tiếp):
- phân bố nhiễu khớp §3.2 trong **±10 điểm phần trăm** (`phase2-corpus-stats.json`);
- **≥ 15%** span là **span âm** (không nhãn);
- hai phép đo của 2c.

Corpus không đạt cổng định tuyến vẫn đem huấn luyện — chỉ là kỳ vọng thấp hơn,
và Phase 5 biết điều đó khi đọc `phase2-corpus-stats.json`.

### Phase 3 — Tagger (2 ngày)

- Kiến trúc: token classification BIO, 5 nhãn → 11 tag. Base **XLM-R**
  (`xlm-roberta-base`, **ghim revision**) — syllable-level nên **không cần tách
  từ VnCoreNLP**, bước mà làm sai là nguồn lỗi phổ biến (PRD §4).
- **Offset là ưu tiên số một**, không phải F1: dùng `offset_mapping` của fast
  tokenizer + giải mã BIO có ràng buộc; test riêng
  `tests/unit/test_tagger_offsets.py` với đầu vào NFC, NFD, và **trộn cả hai**.
- Dev split **tổng hợp** (`splits.json`) cho early stopping. **Tuyệt đối không**
  dùng `gold_real` để chọn epoch/ngưỡng — đó là cổng.
- `calibrate.py`: chọn ngưỡng tin cậy trên dev tổng hợp, xuất ra file, **không**
  dò lại trên `gold_real`.
- Phần cứng: M3 Pro / MPS, ~187 mẫu/s ở cỡ BERT-base → vài phút/epoch. Không
  phải rào cản.
- Tái lập: ghim seed, ghim revision, ghi `sha256` corpus vào metadata checkpoint.

**Cổng CHẶN:** **0 span lệch offset** trên toàn bộ `data/test` (100 file, gồm 20
file không NFC). Lệch offset là bug sẽ đi thẳng vào bài nộp — không thương lượng.

**Cổng ĐỊNH TUYẾN:** F1 span trên dev **tổng hợp** ≥ **0,80** (nới từ 0,90) →
`tagger: true`. Dưới ngưỡng vẫn **đi tiếp Phase 4**: arbiter sẽ tự cho model
trọng số thấp, và Phase 5 có thể đặt `arbiter_model_weight: 0.0`.

*Không* đo `gold_real` ở phase này — không được nhìn vào nó (quy tắc 7).

### Phase 4 — Arbiter + lai (1,5 ngày)

- `arbiter.py`: weighted interval scheduling (§2.7), tất định, có test cho ca
  chồng lấn ba tầng.
- Trọng số khởi tạo: proposer luật cao hơn model ở nhãn luật đang mạnh
  (THUỐC P 0,942), model cao hơn ở nhãn luật đang yếu (TRIỆU_CHỨNG P 0,646).
  Hiệu chỉnh trên dev tổng hợp, **không** trên `gold_real`.
- Giữ nguyên: `linking.py` (**`rerank=True`** — quên là mất 45 điểm R@1 nhánh
  thuốc), `labtest.py` giá trị đo, `ner.detect_masked_drugs`.

**Cổng CHẶN:** `check_invariants` pass; arbiter **tất định** (cùng đầu vào →
cùng đầu ra, không phụ thuộc thứ tự proposer).

**Cổng ĐỊNH TUYẾN:** `Δfinal ≥ 0` so với cấu hình Phase 1. Không đạt →
`arbiter_model_weight: 0.0`, tức arbiter suy biến về đúng pipeline luật — **an
toàn theo kiến tạo**, nên phase này không thể làm hỏng thứ đang có.

### Phase 5 — Chọn cấu hình nộp & báo cáo (1 ngày)

Phase này **không dừng gì cả** — nó *định tuyến*: chọn một trong các cấu hình đã
xây ra để nộp.

**Bước 1 — đăng ký trước, TRƯỚC khi nhìn `gold_real`** (quy tắc 11). Tối đa **4**
cấu hình, sàng bằng dev tổng hợp + `gold_batch1`. Ví dụ:

| # | `labtest_extended` | `tagger` | `arbiter_model_weight` |
|---|---|---|---|
| C0 | false | false | 0,0 | ← baseline luật hiện tại |
| C1 | **true** | false | 0,0 |
| C2 | true | **true** | 0,6 |
| C3 | true | true | **1,0** |

**Bước 2 — chấm cả 4 trên `gold_real`, một lần, ghi hết.**

**Bước 3 — chọn theo luật cố định, không thương lượng:**

```
cấu hình nộp = argmax(final) trong các cấu hình có cận dưới CI 95% của
               Δ(so với C0) > 0
nếu tập đó rỗng  →  nộp C0
```

**Cổng CHẶN của cấu hình được chọn** (bất kể nó là cấu hình nào, kể cả C0):
- [ ] cụm bẫy `gold_real/README.md` vẫn **không có span nào phủ**
- [ ] `smk solve` chạy hết 100 file, 5 bất biến pass, **0 span lệch offset**
- [ ] `gold` (regression guard) không tụt quá **0,03**
- [ ] chạy lại được từ máy sạch, **không gọi mạng**

**Báo cáo — luôn viết, dù kết quả thế nào:** `phase5-gate.json` ghi cả 4 cấu
hình, mỗi cấu hình có `final` + CI + bảng theo nhánh, **riêng từng bộ gold**.
Kết quả âm được ghi lại đầy đủ là sản phẩm hợp lệ — dự án này đã bỏ 2/4 nguồn
làm giàu KB và toàn bộ hướng dense vì đo thấy có hại, và chính các báo cáo âm đó
là thứ ngăn khảo sát lại lần hai.

**Mục tiêu `final ≥ 0,50` không đạt cũng đi tiếp Phase 6.** Cấu hình được chọn —
kể cả C0 — vẫn cần đóng gói tái lập, vì đó mới là thứ quyết định bị loại hay không.

### Phase 6 — Đóng gói tái lập (1 ngày) · *rủi ro bị loại*

PRD §5: **BTC cài lại không được → bị loại.** [`pyproject.toml`](../pyproject.toml)
hiện **cố ý** tách `torch` (~1 GB) khỏi dependency lõi; image `runtime` chỉ mang
nhánh từ vựng. Phase 3–4 phá vỡ ranh giới đó.

**Việc:**
1. Thêm nhóm `train` (torch, transformers) — **chỉ image builder**.
2. `stages/tagger.py` **không import torch ở top-level**; thiếu torch thì
   pipeline chạy tiếp bằng proposer luật (degrade, không crash) — đây là
   fallback offline mà PRD §8 khuyến nghị.
3. Weights vào `data/artifacts/tagger/v1/` kèm `sha256`, revision base model,
   seed. Đóng gói trong bài nộp, **không tải lúc chạy**.
4. Chạy thử trong container sạch — tiền lệ: chính việc này đã lộ 3 bug mà máy
   dev không thấy.
5. README cài đặt từ máy sạch, có mục "chạy không có torch".

**Cổng CHẶN** (đây là phase duy nhất mà không đạt = **bị loại khỏi cuộc thi**,
nên không nới):
- container sạch, không mạng, `smk solve` ra 100 file đúng định dạng — cả khi
  **có** và **không có** nhóm `train`.

Ngưỡng này dễ đạt hơn nó nghe: nếu Phase 5 chọn C0 thì `torch` không nằm trên
đường chạy nào cả, và cổng thu về đúng trạng thái repo hiện tại.

---

## 5. Quy tắc không được phá

Kế thừa v1 §6, bổ sung 4 quy tắc mới (★):

1. **Không bao giờ báo cáo số đo trên chính tập sinh ra.** Chấm trên `gold_real`
   và chỉ `gold_real`. Tiền lệ: hai bộ đo nhỏ đã nói dối theo hướng có lợi — bộ
   3 file cho 0,530 còn bộ 9 file cho 0,407 **trên cùng một hệ**.
2. **Không gộp ba bộ gold khi báo cáo.** `gold_real` là cổng; `gold_batch1` đo
   khái quát hoá ngoài miền + đo assertion; `gold` chỉ là regression guard.
3. **Không gọi LLM lúc build.** Sinh một lần, đóng băng, commit kèm `sha256`.
4. **Không `unicodedata.normalize` trên chuỗi dùng tính offset.** Chuẩn hoá chỉ
   trên bản sao dùng để so khớp.
5. **Không đọc file bằng `Path.read_text()`.** Dùng `textio.read_document()` —
   nó đặt `newline=''`.
6. **Không chỉnh tham số để ép một ca cụ thể qua.** `gold_real` chỉ 9 file.
7. ★ **`gold_real` không bao giờ là NGUỒN.** Không lấy phân bố chương, không lấy
   hạt giống, không chọn epoch, không dò ngưỡng. Nó chỉ là cổng. (v1 vi phạm ở
   Bước 1 — G5.)
8. ★ **Không công bố một con số không có khoảng tin cậy** trên n = 9 tài liệu.
9. ★ **Không thêm proposer mà không thêm trọng số vào arbiter.** Chuỗi nối tiếp
   ẩn thứ tự ưu tiên không đo được.
10. ★ **Không để `torch` trở thành bắt buộc ở đường chạy chính.**
11. ★ **Đăng ký trước tối đa 4 cấu hình** vào `phase5-gate.json` **trước khi**
    chấm chúng trên `gold_real`. Đây là cái giá của việc nới cổng: khi thành
    phần không đạt vẫn được giữ lại sau một cờ, số cấu hình khả dĩ tăng theo cấp
    số nhân, và "chọn cái cao nhất trong 20 cấu hình trên 9 file" là overfit
    bằng cách chọn — cùng loại sai lầm với probe set đã nói dối. Sàng sơ bộ bằng
    dev tổng hợp và `gold_batch1`, hai thứ **không** phải cổng.
12. ★ **Cổng CHẶN không bao giờ được nới.** Nếu một cổng CHẶN cản đường, đó là
    bug trong code chứ không phải ngưỡng đặt cao. Nới nó là đưa lỗi offset hoặc
    span chồng lấn vào thẳng bài nộp.

---

## 6. Tham chiếu

### 6.1 Đã dẫn trong PRD (mã R giữ nguyên để đối chiếu tab 03)

| mã | công trình | dùng ở đâu trong kế hoạch này |
|---|---|---|
| R1 | Liu et al. **SapBERT** (NAACL 2021); **XL-BEL** (ACL 2021) | nhánh linking — treo lại, xem S4 backlog |
| R2 | **Hybrid Re-ranking** cho biomedical EL, BioNNE-L 2025 (CEUR Vol-4038) | mô hình cho `pairs.jsonl` §2.6 |
| R3 | Medical Entity Linking in Low-Resource Settings with Fine-Tuning-Free LLMs | bối cảnh "không có nhãn" |
| R4 | Remy et al. **BioLORD** — arXiv:2210.11892 | S4 backlog |
| R7 | Overview of BioASQ 2025 — **BioNNE-L** — arXiv:2508.20554 | nested NER cho tên XN lồng nhau |
| R11 | Multistage biomedical concept normalization; BM25 + **RRF** | fusion retriever (chưa dùng) |
| R14 | **ViMedNER** (EAI Trans., 2024) | căn cứ chọn XLM-R làm base — Phase 3 |
| R15 | Nguyen & Nguyen. **PhoBERT** (EMNLP Findings 2020) | đối chứng; cần VnCoreNLP nên **không chọn** |
| R16 | PhoBERT + **Graph Attention** — arXiv:2510.11537 | hướng nâng cao, ngoài phạm vi v2 |
| R17 | **ConText/NegEx** (Harkema, Chapman); n2c2 2022 (JBI 2023) | `assertion.py` — giữ nguyên, chỉ đo thêm |

### 6.2 Bổ sung cho v2 — sinh dữ liệu & giám sát yếu

| công trình | vì sao liên quan trực tiếp |
|---|---|
| **Dai & Adel**, *An Analysis of Simple Data Augmentation for NER* (COLING 2020) | đo bốn phép tăng cường cho NER; **label-wise token replacement** và **mention replacement** chính là phép v2 dùng ở §2.2 (thay cụm y khoa trong khuôn thật) |
| **Ding et al.**, *DAGA: Data Augmentation with a Generation Approach for Low-resource Tagging* (EMNLP 2020) | tuyến tính hoá *nhãn + văn bản* thành một chuỗi rồi sinh — chính là hình thức hoá của "annotation-first" ở v1 §2 |
| **Shang et al.**, *Learning Named Entity Tagger using Domain-Specific Dictionary* — **AutoNER** (EMNLP 2018) | giám sát xa bằng từ điển; xử lý **âm giả** khi từ điển không đầy đủ — đúng vấn đề §2.5 (span âm) và v1 §3.1 (vòng lặp tự khen) |
| **Jie et al.**, *Better Modeling of Incomplete Annotations for NER* (NAACL 2019) | corpus tổng hợp là **chú thích không đầy đủ** theo định nghĩa; bài này cho cách huấn luyện không coi "không nhãn" = "âm chắc chắn" |
| **Ratner et al.**, *Snorkel* (VLDB 2017) | khung hợp nhất nhiều nguồn giám sát yếu — mô hình lý thuyết cho arbiter §2.1 khi muốn học trọng số thay vì đặt tay |
| **Lample et al.**, *Neural Architectures for NER* (NAACL 2016) | BiLSTM-CRF; căn cứ cho việc có nên thêm CRF head lên XLM-R |
| **Lafferty, McCallum, Pereira**, *Conditional Random Fields* (ICML 2001) | nền tảng CRF; và ràng buộc chuyển trạng thái BIO ở giải mã (§2.7) |
| **Conneau et al.**, *Unsupervised Cross-lingual Representation Learning at Scale* — **XLM-R** (ACL 2020) | base model Phase 3; đặc tính syllable-level cho tiếng Việt |
| **Yu, Bohnet, Poesio**, *Named Entity Recognition as Dependency Parsing* (ACL 2020) | biaffine NER cho span lồng — dự phòng nếu tên XN lồng nhau thành vấn đề |

### 6.3 Phương pháp đo

| công trình | dùng ở |
|---|---|
| **Berg-Kirkpatrick, Burkett, Klein**, *An Empirical Investigation of Statistical Significance in NLP* (EMNLP 2012) | paired bootstrap — Phase 0, quy tắc 8 |
| **Efron & Tibshirani**, *An Introduction to the Bootstrap* (1993) | CI trên n = 9 |
| **Chapman et al.**, *A Simple Algorithm for Identifying Negated Findings and Diseases* (JBI 2001) | NegEx gốc — đối chiếu `assertion.py` |

### 6.4 Giải thuật & cấu trúc dữ liệu

| nguồn | dùng ở |
|---|---|
| **Kleinberg & Tardos**, *Algorithm Design* (2005), §6.1 **weighted interval scheduling** | arbiter §2.7 — DP O(n log n) |
| **Aho & Corasick**, *Efficient String Matching* (CACM 18(6), 1975) | gazetteer đa mẫu §2.7 |
| **Cormack, Clarke, Buettcher**, *Reciprocal Rank Fusion* (SIGIR 2009) | fusion retriever — chưa dùng, ghi để không khảo sát lại |
| **Unicode UAX #15** (Normalization Forms) | quy tắc 4 — vì sao không được normalize |
| **Unicode UAX #29** (Text Segmentation — grapheme clusters) | song ánh offset NFC/NFD §2.7; README `gold_real` ghi "thử cả hai dạng cũng không đủ" |
| **Vose's alias method** / cumulative-weight + `bisect` | lấy mẫu có trọng số §2.7 |

> ⚠️ Trước khi trích bất kỳ mục nào ở §6.2–§6.4 vào tài liệu nộp BTC, **kiểm lại
> nguyên văn**. Các mục R1–R17 đã có trong PRD; các mục bổ sung là dẫn theo trí
> nhớ về văn liệu, chưa đối chiếu bản gốc trong phiên này.

### 6.5 Tài liệu trong repo

| đường dẫn | nội dung |
|---|---|
| [`PRD.html`](PRD.html) | đề bài, metric, phân tích chiến lược, 4 bộ chuẩn (mở bằng trình duyệt) |
| [`synth-corpus-plan.md`](synth-corpus-plan.md) | **v1** — giữ lại để đối chiếu; §2 và §3.2 vẫn đúng nguyên |
| [`gold_real/README.md`](../data/probe/gold_real/README.md) | thành phần gold thật + **danh sách cụm bẫy** + bẫy Unicode `100.txt` |
| [`gold-chan-doan-protocol.md`](gold-chan-doan-protocol.md) | sự cố gold cũ dự đoán **sai dấu**; ngưỡng hoà vốn |
| [`s1-embedding-plan.md`](s1-embedding-plan.md) | vì sao hướng embedding bị hoãn (cổng đóng hai lần) |
| [`solution-backlog.md`](solution-backlog.md) | S1 (SNOMED sinh cặp đồng nghĩa), S4 (thay embedding y sinh) |
| [`kb-pipeline-plan.md`](kb-pipeline-plan.md) | KB đã dựng thế nào |
| [`reports/atc-vi-enrich.json`](reports/atc-vi-enrich.json) | ★ delta = 0,000 ở cả 5 bộ probe — bằng chứng §0.3 A |

---

## 7. Rủi ro

| rủi ro | mức | cách chặn |
|---|---|---|
| **Phase 1 không đạt** → mất luôn nhánh +0,154 | **Cao** | không dừng: tắt cờ, đi tiếp; nhánh XN được tagger đánh lại ở Phase 3 |
| ★ **Nới cổng → overfit bằng cách chọn** trên 9 file | **Cao** | quy tắc 11: đăng ký trước ≤ 4 cấu hình; sàng sơ bộ bằng dev tổng hợp + `gold_batch1` |
| ★ **Xây 6 ngày rồi ship với cờ `false`** | Trung bình | chấp nhận có ý thức (§9); thành phần tắt vẫn là tài sản cho vòng 2, có test và có báo cáo |
| Cách nói lấy từ KB → model không học gì mới | **Cao** | hai phép đo 2c: hợp lý y khoa ≥ 80/100 **và** ≥ 40% không khớp gazetteer; dưới ngưỡng thì ghi số để Phase 5 diễn giải |
| Văn bản sinh quá sạch → lệch phân bố | **Cao** | khuôn thật từ `data/test` (G7); cổng ±10 điểm phần trăm |
| **Overfit vào 9 file `gold_real`** | **Cao** | quy tắc 7 (gold_real không bao giờ là nguồn); dev tổng hợp cho mọi lựa chọn siêu tham số; bootstrap CI |
| Model phá phần luật đang mạnh (THUỐC P 0,942) | **Cao** | arbiter có trọng số theo nhãn; cổng precision Phase 4 |
| **Weights phá tái lập** (PRD §5 — cài lại không được thì **bị loại**) | **Cao** | Phase 6 toàn bộ; fallback không-torch |
| Khuôn từ `data/test` bị coi là hard-code | Trung bình | holdout 20 file; không copy câu chứa khái niệm; ghi rõ trong README nộp bài |
| Sinh biệt dược KB không tra được → dạy model gán mã pipeline không trả về được | Trung bình | cổng Phase 2: mọi concept trong corpus phải `linking.py` tra được |
| LLM gán sai mã cho cách nói nó sinh | Trung bình | cổng duyệt tay; model khác họ; **nhánh XN và THUỐC không hỏi LLM** |
| `rerank=True` bị quên khi refactor | Trung bình | test hồi quy khoá cứng — mất 45 điểm R@1 |
| Bộ sinh trở thành mục tiêu tối ưu thay vì phương tiện | Trung bình | quy tắc 1; corpus không bao giờ là bộ báo cáo |

---

## 8. Prompt triển khai theo giai đoạn

> Mỗi prompt tự chứa. Agent thực thi đọc prompt + các file nó chỉ tới là đủ làm,
> không cần đọc lại toàn bộ lịch sử.

### Prompt Phase 0 — hạ tầng đánh giá

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §0.2, §4 Phase 0, §5 quy tắc 1/2/8.

Việc: dựng hạ tầng đánh giá làm điều kiện tiên quyết cho mọi cổng sau này.

1. Thêm lệnh `smk eval solve --gold <dir> --report <json>`:
   - tự nhận cấu trúc thư mục: gold_real/gold dùng `annotations_gold/`,
     gold_batch1 dùng `annotations/`; văn bản luôn ở `text/`;
   - đọc file bằng stages.textio.read_document (KHÔNG Path.read_text);
   - chấm bằng stages.scoring, xuất: final, text, assertions, candidates,
     span_precision/recall/f1 TỔNG và **theo từng nhãn trong 5 nhãn**.

2. Thêm paired bootstrap trên tài liệu (B=10000, seed ghim trong code):
   - CI 95% cho `final` của một lần chạy;
   - CI 95% cho `Δfinal` giữa hai file báo cáo (so sánh theo cặp cùng tài liệu).
   - API: `smk eval compare --base a.json --new b.json`.

3. Chạy cho cả 3 bộ gold, ghi docs/reports/synth-baseline.json.
   BÁO CÁO RIÊNG TỪNG BỘ — tuyệt đối không gộp.

Cổng nghiệm thu:
- chạy 3 lần cho ra số y hệt (tất định);
- `final` trên gold_real tái tạo đúng 0.4327;
- bảng theo nhánh tái tạo đúng: CHẨN_ĐOÁN R 0.851/P 0.742 · TÊN_XN 0.586/0.583 ·
  TRIỆU_CHỨNG 0.670/0.646 · THUỐC 0.865/0.942 · KẾT_QUẢ_XN 0.424/0.429.
  Lệch so với các số này nghĩa là hạ tầng đo sai — dừng lại và truy nguyên,
  KHÔNG sửa số trong tài liệu.

Cấm: sửa bất kỳ file nào trong stages/ ngoài scoring.py và cli.py.
```

### Prompt Phase 1 — nhánh xét nghiệm bằng luật

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §0.3 mục D, §2.3, §4 Phase 1.
Đọc trước: src/smart_medic/stages/labtest.py (toàn bộ, kèm docstring),
           data/probe/gold_real/README.md.

Vấn đề đã đo: KẾT_QUẢ_XÉT_NGHIỆM recall 0.424 vì `_MEASURE` là regex số+đơn vị,
mà kết quả thật phần lớn KHÔNG phải số:
  "dương tính" · "(+)" · "(-)" · "chưa phát hiện bất thường" · "nguyên vẹn" ·
  "ST chênh lên / chênh xuống" · "Sóng T đảo" · "túi mật căng to với dịch quanh
  túi mật" · "tăng men gan nhẹ" · "cải thiện đến 20.6" · "đang chờ"

Việc:
1. Dựng data/curated/lab_panels.v1.yaml theo schema ở §2.3.
   Nguồn HỢP LỆ, đúng ba nguồn này:
     (a) kiến thức panel chuẩn (công thức máu, sinh hoá, đông máu, viêm gan,
         tim mạch, nước tiểu, chẩn đoán hình ảnh);
     (b) trích mẫu `^NHÃN:` từ 91 file data/test KHÔNG nằm trong gold_real
         (gold_real dùng 1,7,18,24,30,45,53,65,100 — loại đúng 9 file này);
     (c) data/probe/gold_batch1 (218 TÊN_XN).
   NGUỒN CẤM: data/probe/gold_real — nó là cổng (quy tắc 7).

2. Mở rộng labtest.py:
   - 5 lớp giá trị mới (§2.3): định tính, mô tả bình thường, mô tả bất thường,
     xu hướng, trạng thái;
   - ghép cặp TÊN→KQ theo 4 dấu ngăn đã đo (gold_real | gold_batch1):
     ": " (10 | 57) · " " (8 | 85) · văn xuôi " là "/" cho thấy "/" đo được là "
     (6 | ~19) · xuống dòng + gạch đầu dòng (2 | ~2);
   - từ điển viết tắt: BC, N, PTT, INR, BUN, HBsAg, CK-MB, Troponin I/T...
   - GIỮ NGUYÊN SECTION_WORDS và luật loại dòng gạch đầu dòng (đã đo: tránh 38
     entity thừa — đọc docstring _LABELLED trước khi đụng).

3. ner.py:223 — cho gazetteer nhận thêm term_type='atc_vi_name'
   (654 term đã có trong KB nhưng đang bị lọc ra). Một dòng SQL.
   KHÔNG kỳ vọng điểm từ việc này (đo được: chỉ 3 tên xuất hiện trong data/test).

4. Thay labtest._free() O(n) tuyến tính bằng bisect trên mảng mốc đã sắp.

5. Tạo data/curated/pipeline.v1.yaml với cờ `labtest_extended` (xem §4.0).

CỔNG CHẶN — không đạt nghĩa là CÓ BUG, sửa rồi chạy lại:
- mọi cụm bẫy liệt kê trong gold_real/README.md vẫn không có span nào phủ
- 0 span lệch offset trên toàn bộ 100 file data/test
- pytest xanh toàn bộ

CỔNG ĐỊNH TUYẾN — không đạt nghĩa là GHI SỐ, TẮT CỜ, ĐI TIẾP Phase 2:
- Δfinal > 0 và cận dưới CI 95% > 0  →  labtest_extended: true, ship
- Δfinal > 0 nhưng CI chạm 0         →  true, ghi rõ là BIÊN, Phase 5 xét lại
- Δfinal <= 0                        →  false, giữ nguyên code đã viết, đi tiếp

KHÔNG có tiêu chí dừng. Ràng buộc precision riêng đã BỎ — Δfinal kèm CI đã tính
cả hai chiều.
KHÔNG dò tham số để ép qua cổng định tuyến (quy tắc 6): tắt cờ là hành động hợp
lệ, ép số thì không.
Ghi docs/reports/phase1-labtest.json trong CẢ BA trường hợp, kèm bảng theo nhánh
cho gold_real và gold_batch1 — báo cáo riêng từng bộ, không gộp.
```

### Prompt Phase 2 — bộ sinh corpus

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.2–§2.5, §3, §4 Phase 2, §5.
Đọc thêm: docs/synth-corpus-plan.md §2 (vì sao annotation-first) và §3.2
(phân bố văn bản thật) — hai mục đó của v1 vẫn đúng nguyên.

Nguyên tắc bất di bất dịch: GHI OFFSET LÚC CHÈN CHUỖI vào khung, không bao giờ
dùng txt.index(). Đây là lý do tồn tại của cả hướng annotation-first.

2a. Khung + bất biến — VIẾT TEST TRƯỚC.
    src/smart_medic/synth/{schema,render,export}.py
    Bốn bất biến, kiểm trên 100% tài liệu:
      1) text[start:end] == span.text
      2) span không chồng lấn
      3) candidates rỗng với TRIỆU_CHỨNG / TÊN_XN / KẾT_QUẢ_XN
      4) corpus chấm được bằng stages.scoring mà không sửa gì
    Dùng lại stages.solve.check_invariants — nó đã cài sẵn 1–3.
    Xuất đúng định dạng gold_real: text/NNN.txt + annotations/NNN.json.

2b. Bề mặt TẤT ĐỊNH — không gọi LLM.
    synth/surface/lab.py   ← nguồn chính, đọc lab_panels.v1.yaml của Phase 1
    synth/surface/drug.py  ← phụ, chỉ 10% tài liệu. Ba lớp bề mặt:
        - tên ATC tiếng Việt (data/knowledge_base/atc/ddd.csv, lọc `+` `*` `(`)
        - token bị che *** (độ dài trung vị 12 — đã đo trên data/test)
        - biệt dược Việt KHÔNG có mã → candidates rỗng LÀ đáp án đúng
    Xuất kèm: data/curated/drug_surface_atc.v1.jsonl, dose_forms_vi.v1.txt (71),
    drug_groups_vi.v1.txt (29). Hai file sau KHÔNG nạp vào KB.

2c. Bề mặt LLM — CHỈ CHẨN_ĐOÁN và TRIỆU_CHỨNG.
    Gọi MỘT LẦN, đóng băng ra data/curated/surface_forms.v1.jsonl + .sha256,
    commit vào git. Prompt phải đòi đích danh: cách nói dân dã, viết tắt, sai
    chính tả, vùng miền; CẤM trả về tên chuẩn trong KB.
    Hình dạng mong muốn cho K29.7 (Viêm dạ dày, không xác định):
      viêm bao tử · đau bao tử · viêm dạ dày · đau dạ dày · viêm bao tử mạn
    Dùng model KHÁC HỌ với model dùng ở pipeline (sai số không tương quan).

    HAI PHÉP ĐO bắt buộc ghi lại — cả hai đều KHÔNG làm dừng phase:
      (i)  hợp lý y khoa: duyệt tay 100 cặp (cách nói → mã) ngẫu nhiên, >= 80.
           Dưới ngưỡng → siết prompt, sinh lại ĐÚNG MỘT LẦN, lấy kết quả tốt hơn
           trong hai lần rồi đi tiếp.
      (ii) độ mới: >= 40% cách nói KHÔNG khớp term nào trong gazetteer KB.
           Đây là phép đo chống vòng lặp tự khen (v1 §3.1). Dưới 40% VẪN ĐI TIẾP,
           nhưng ghi vào phase2-corpus-stats.json — nó dự báo Phase 3 ít tác dụng,
           và Phase 5 cần con số này để diễn giải kết quả.

2d. Span âm + khuôn thật.
    synth/distractor.py — 6 lớp ở §2.5, chèn KHÔNG kèm nhãn.
      ⚠️ Lấy LỚP của bẫy (kiến thức chung về thể loại), KHÔNG copy thực thể cụ
      thể từ gold_real/README.md — đó là file cổng.
    synth/frames.py — khai thác 91 file data/test (loại 9 file của gold_real)
    làm khuôn: giữ khung câu, thay cụm y khoa bằng span sinh ra.
      Ràng buộc PRD §5: giữ 20 file làm holdout khung; KHÔNG copy nguyên câu có
      chứa khái niệm y tế; ghi rõ cách làm vào README nộp BTC.
      Nếu đánh giá là rủi ro → dùng gold_batch1 làm nguồn khung thay thế.

2e. Nhiễu + thống kê. Khớp §3.2 của v1 (đã kiểm lại, chính xác):
    NFD 20/100 · mask *** 30/100 · gạch đầu dòng 90/100 · mẫu NHÃN: 97/100 ·
    giọng hỏi–đáp 49/100 · độ dài trung vị 1838 ký tự.

CỔNG CHẶN — vi phạm = corpus hỏng, huấn luyện trên nó là học cái sai:
- 4 bất biến pass 100% tài liệu

Lưu ý KHÔNG phải cổng mà là MỘT BƯỚC trong render.py: khái niệm nào linking.py
không tra ra mã thì LỌC TỰ ĐỘNG khỏi corpus (đừng dạy model gán mã pipeline
không thể trả về — tự dựng trần điểm cho chính mình).

CỔNG ĐỊNH TUYẾN — không đạt thì ghi số vào phase2-corpus-stats.json và ĐI TIẾP:
- phân bố nhiễu khớp trong ±10 điểm phần trăm
- >= 15% span là span âm
- hai phép đo của 2c

Corpus không đạt cổng định tuyến VẪN đem huấn luyện ở Phase 3 — chỉ là kỳ vọng
thấp hơn, và Phase 5 biết điều đó khi đọc file thống kê.

Cấm: gọi LLM ở bất kỳ đâu ngoài 2c; dùng gold_real làm nguồn; báo cáo bất kỳ số
đo nào trên chính corpus sinh ra.
```

### Prompt Phase 3 — tagger

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.7 (hai dòng về offset), §4 Phase 3.

Việc: huấn luyện token classification BIO 5 nhãn trên corpus data/synth/v1.

- Base: xlm-roberta-base, GHIM REVISION cụ thể trong config (không dùng "main").
  Lý do chọn: ViMedNER cho thấy XLM-R nhìn chung vượt PhoBERT/ViHealthBERT trên
  NER y khoa tiếng Việt, và nó chạy syllable-level nên KHÔNG cần VnCoreNLP —
  bước mà làm sai là nguồn lỗi phổ biến.

- ƯU TIÊN SỐ MỘT LÀ OFFSET, không phải F1:
  * dùng offset_mapping của fast tokenizer để ánh xạ subword → ký tự;
  * giải mã BIO CÓ RÀNG BUỘC: cấm I-X sau O, cấm I-X sau B-Y (Y != X);
  * tests/unit/test_tagger_offsets.py phải có ca: đầu vào NFC, đầu vào NFD, và
    đầu vào TRỘN CẢ HAI trong cùng một cụm (đây là hiện tượng thật ở 100.txt:
    cùng chuỗi "tiền sản giật" chỗ dài 16 ký tự chỗ 13).

- Split: dev TỔNG HỢP từ data/synth/v1/splits.json cho early stopping.
  TUYỆT ĐỐI KHÔNG dùng gold_real để chọn epoch, ngưỡng, hay bất kỳ siêu tham số
  nào — nó là cổng (quy tắc 7).

- calibrate.py: chọn ngưỡng tin cậy trên dev tổng hợp, ghi ra file config.

- Tái lập: ghim seed; ghim revision base model; ghi sha256 của corpus vào
  metadata checkpoint; xuất ra data/artifacts/tagger/v1/.

- Phần cứng: M3 Pro / MPS, cỡ BERT-base ~187 mẫu/s → vài phút mỗi epoch.

- stages/tagger.py (inference): KHÔNG import torch ở top-level. Thiếu torch thì
  trả danh sách rỗng và pipeline chạy tiếp bằng proposer luật.

CỔNG CHẶN: 0 span lệch offset khi chạy trên toàn bộ 100 file data/test (gồm 20
file không NFC). Lệch offset là bug đi thẳng vào bài nộp — không thương lượng,
không nới.

CỔNG ĐỊNH TUYẾN: F1 span trên dev TỔNG HỢP >= 0.80 (đã nới từ 0.90) → tagger: true.
Dưới ngưỡng VẪN ĐI TIẾP Phase 4: arbiter sẽ tự cho model trọng số thấp, và
Phase 5 có thể đặt arbiter_model_weight: 0.0. Không dừng, không huấn luyện lại
quá 2 lần.

KHÔNG đo gold_real ở phase này. Không được nhìn vào nó.
```

### Prompt Phase 4 — arbiter + lai

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.1, §2.7, §4 Phase 4, §5 quy tắc 9.

Việc: thay chuỗi detector nối tiếp bằng kiến trúc proposer → arbiter → enricher.

1. src/smart_medic/stages/arbiter.py
   Bài toán: cho N span có thể chồng lấn, mỗi span có trọng số, chọn tập con
   KHÔNG chồng lấn có tổng trọng số lớn nhất.
   Đây đúng là WEIGHTED INTERVAL SCHEDULING (Kleinberg & Tardos §6.1):
     - sắp theo `end`;
     - p(j) = span cuối cùng kết thúc <= start(j), tìm bằng bisect;
     - OPT(j) = max(w_j + OPT(p(j)), OPT(j-1));
     - truy vết để lấy tập nghiệm.
   O(n log n), tất định. Tie-break bằng (start, end, tên proposer) để kết quả
   không phụ thuộc thứ tự đầu vào.

2. Bọc 4 proposer về cùng một giao diện, trả (span, type, conf, tên_proposer):
   P1 ner.Gazetteer · P2 labtest · P3 detect_masked_drugs · P4 tagger.

3. Trọng số khởi tạo theo NHÃN, dựa trên precision đã đo trên gold_real:
   - THUỐC: luật P 0.942 → luật thắng model
   - TRIỆU_CHỨNG: luật P 0.646 → model thắng luật
   - còn lại: hiệu chỉnh trên dev TỔNG HỢP, KHÔNG trên gold_real.

4. Giữ nguyên enricher: assertion.py; linking.py với rerank=True.
   ⚠️ `rerank` mặc định TẮT ở search_lexical. Quên bật = mất 45 điểm R@1 nhánh
   thuốc. Thêm test hồi quy khoá cứng điều này.

5. Sau arbiter, check_invariants bất biến 2 (không chồng lấn) trở thành đúng
   theo kiến tạo — giữ lại phép kiểm làm lưới an toàn, đừng bỏ.

CỔNG CHẶN: check_invariants pass; arbiter TẤT ĐỊNH (cùng đầu vào → cùng đầu ra,
không phụ thuộc thứ tự proposer); pytest xanh.

CỔNG ĐỊNH TUYẾN: Δfinal >= 0 so với cấu hình Phase 1. Không đạt →
arbiter_model_weight: 0.0, arbiter suy biến về đúng pipeline luật. AN TOÀN THEO
KIẾN TẠO: phase này không thể làm hỏng thứ đang có, nên không cần dừng.
```

### Prompt Phase 5 — chọn cấu hình nộp

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §4.0, §4 Phase 5, §5 toàn bộ
(đặc biệt quy tắc 11).

Phase này KHÔNG dừng gì cả — nó ĐỊNH TUYẾN: chọn một cấu hình đã xây để nộp.

BƯỚC 1 — đăng ký trước, TRƯỚC KHI nhìn gold_real. Tối đa 4 cấu hình, sàng sơ bộ
bằng dev tổng hợp và gold_batch1 (hai thứ KHÔNG phải cổng). Ghi danh sách vào
docs/reports/phase5-gate.json TRƯỚC khi chấm. Ví dụ:
   C0: labtest_extended=false, tagger=false, arbiter_model_weight=0.0  (baseline)
   C1: true,  false, 0.0
   C2: true,  true,  0.6
   C3: true,  true,  1.0

BƯỚC 2 — chấm cả 4 trên gold_real, MỘT LẦN, ghi hết. Dùng `smk eval solve` +
`smk eval compare` của Phase 0.

BƯỚC 3 — chọn theo luật cố định, không thương lượng:
   cấu hình nộp = argmax(final) trong các cấu hình có cận dưới CI 95% của
                  Δ(so với C0) > 0
   nếu tập đó rỗng → nộp C0

CỔNG CHẶN của cấu hình được chọn (kể cả khi đó là C0):
[ ] mọi cụm bẫy trong gold_real/README.md vẫn không có span nào phủ
[ ] smk solve chạy hết 100 file, 5 bất biến pass, 0 span lệch offset
[ ] gold (regression guard) không tụt quá 0.03
[ ] chạy lại được từ máy sạch, không gọi mạng

BÁO CÁO — luôn viết, dù kết quả thế nào: phase5-gate.json ghi CẢ 4 cấu hình,
mỗi cấu hình có final + CI + bảng theo nhánh, RIÊNG TỪNG BỘ GOLD.

Mục tiêu final >= 0.50 KHÔNG đạt cũng đi tiếp Phase 6 — cấu hình được chọn, kể
cả C0, vẫn phải đóng gói tái lập, vì đó mới là thứ quyết định bị loại hay không.

Cấm tuyệt đối: thêm cấu hình thứ 5 sau khi đã nhìn số trên gold_real (quy tắc 11
— đó là overfit bằng cách chọn); dò tham số cho tới khi qua cổng; báo cáo số
trên corpus sinh ra; gộp ba bộ gold.
```

### Prompt Phase 6 — đóng gói tái lập

```
Bối cảnh: đọc docs/synth-corpus-plan-v2.md §4 Phase 6, và PRD tab 01 mục 5
("Nếu BTC không cài đặt lại được source code của nhóm → nhóm thi sẽ bị loại").

Tình trạng hiện tại: pyproject.toml CỐ Ý tách torch (~1GB) khỏi dependency lõi;
image runtime chỉ mang nhánh từ vựng. Phase 3–4 phá ranh giới đó.

Việc:
1. Thêm optional-dependency group "train" (torch, transformers) — CHỈ image
   builder dùng. Không đưa vào dependency lõi.
2. stages/tagger.py: import torch bên trong hàm, không ở top-level. Thiếu torch
   → trả rỗng, pipeline chạy tiếp bằng proposer luật (degrade, không crash).
   Đây là fallback offline mà PRD §8 khuyến nghị.
3. Weights vào data/artifacts/tagger/v1/ kèm sha256, revision base model, seed.
   Đóng gói trong bài nộp. KHÔNG tải lúc chạy (quy tắc 3: không gọi mạng).
4. Chạy thử trong container sạch. Tiền lệ: chính việc này đã lộ 3 bug mà máy dev
   không bao giờ thấy.
5. README cài đặt từ máy sạch, có mục riêng "chạy khi không có torch".

CỔNG CHẶN — đây là phase duy nhất mà không đạt = BỊ LOẠI KHỎI CUỘC THI, nên
KHÔNG nới: container sạch, ngắt mạng, `smk solve` ra đủ 100 file đúng định dạng
— kiểm CẢ HAI trường hợp: có nhóm "train" và không có.

Ngưỡng này dễ đạt hơn nó nghe: nếu Phase 5 chọn C0 thì torch không nằm trên
đường chạy nào, và cổng thu về đúng trạng thái repo hiện tại.
```

---

## 9. Thứ tự làm

**Một đường thẳng, không nhánh rẽ.** Mọi phase đều được làm tới cùng; cổng định
tuyến chỉ quyết định giá trị mặc định của một cờ, không quyết định có làm tiếp
hay không.

```
 Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
  0,5đ        1,5đ        3đ          2đ          1,5đ         1đ          1đ
 hạ tầng     luật XN     corpus      tagger      arbiter     chọn CH     đóng gói
   đo
    │           │           │           │           │           │           │
    ▼           ▼           ▼           ▼           ▼           ▼           ▼
 CHẶN:      CHẶN:       CHẶN:       CHẶN:       CHẶN:       CHẶN:       CHẶN:
 tái tạo    bẫy sạch    4 bất       0 lệch      tất định    bẫy sạch    container
 0,4327     0 lệch      biến        offset      bất biến    100 file    sạch,
            offset                                          gold ≤−0,03 không mạng
    │           │           │           │           │           │
    │        ĐỊNH TUYẾN  ĐỊNH TUYẾN  ĐỊNH TUYẾN  ĐỊNH TUYẾN  ĐỊNH TUYẾN
    │        Δ>0, CI>0   nhiễu ±10pp F1 ≥ 0,80   Δ ≥ 0       argmax trong
    │           ↓        âm ≥ 15%       ↓           ↓        ≤4 CH đăng ký
    │      labtest_     duyệt ≥80    tagger:    weight:      trước
    │      extended     mới ≥40%     true/false 1.0/0.0         ↓
    │      true/false      ↓                                cấu hình NỘP
    │                 (chỉ ghi số,                          (có thể là C0)
    │                  luôn đi tiếp)
    └──────────────────────────────────────────────────────────────────────┘
                    không có mũi tên nào quay ra ngoài
```

**Cái được và cái mất khi nới cổng — nói thẳng:**

| được | mất |
|---|---|
| toàn bộ 7 phase hoàn thành trong mọi kịch bản | có thể mất ~6 ngày xây thứ cuối cùng ship với cờ `false` |
| không công sức nào bị vứt — thành phần tắt vẫn nằm sẵn cho vòng 2 | rủi ro **overfit bằng cách chọn** trên 9 file → phải trả bằng quy tắc 11 |
| tiêu chí `Δfinal + CI` đơn giản và đúng hơn ràng buộc precision riêng | không còn "điểm dừng sớm" để tiết kiệm thời gian nếu Phase 1 cho tín hiệu xấu |

**Một quan sát vẫn nên theo dõi dù không còn là điểm dừng:** kết quả Phase 1 là
tín hiệu sớm nhất về giả định trung tâm của cả kế hoạch ("span recall là đòn
bẩy lớn nhất"). Nếu nhánh luật rẻ nhất, nhắm thẳng trần lớn nhất (+0,154), mà
không nhúc nhích — thì đọc lại §0.2 trước khi bỏ 6 ngày tiếp theo. Đây là lời
khuyên, không phải cổng.
