# Sinh corpus huấn luyện từ ANNOTATION — phác thảo & kế hoạch triển khai

> **Đối tượng đọc:** agent thực thi, bắt đầu từ đầu, chưa biết bối cảnh dự án.
> **Nhiệm vụ:** dựng bộ sinh dữ liệu huấn luyện NER cho pipeline giải bài, theo
> hướng **annotation-first** (có nhãn trước → sinh văn bản sau), rồi huấn luyện
> một sequence labeler và đo trên bộ gold thật.
> **Trạng thái:** chưa triển khai. Mọi số trong tài liệu là **đã đo**, không ước.

---

## 1. Bối cảnh tối thiểu cần biết

### 1.1 Bài toán

Cuộc thi Viettel AI Race 2026. Input: 100 file `.txt` văn bản y khoa tiếng Việt
tự do (`data/test/`). Output: 100 file `.json`, mỗi khái niệm y tế là một mục:

```json
{"text": "viêm phổi", "type": "CHẨN_ĐOÁN", "candidates": ["J18.9"],
 "assertions": [], "position": [530, 539]}
```

Năm nhãn: `TRIỆU_CHỨNG`, `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`, `CHẨN_ĐOÁN`,
`THUỐC`. Ba assertion: `isNegated`, `isFamily`, `isHistorical`.

Chấm điểm:

```
final = 0,3·(1 − WER trên text) + 0,3·Jaccard(assertions) + 0,4·Jaccard(candidates)
```

Hai quy ước quyết định chiến lược:

- **Jaccard quy ước cả hai rỗng ⇒ 1,0.** Nên với nhãn không được gán mã, chỉ cần
  **phát hiện đúng span** là ăn trọn cả ba thành phần.
- **Jaccard phạt mã thừa ngang mã thiếu.** Đoán bừa mã là mất điểm chắc chắn.

Chi tiết đầy đủ: `docs/PRD.html` (mở bằng trình duyệt, tab 01 và 03).

### 1.2 Hệ thống hiện có

Pipeline chạy được đầu-cuối:

```bash
smk solve --input data/test --out data/output --zip data/submission/output.zip
```

Bốn module trong `src/smart_medic/stages/`:

| file | vai trò |
|---|---|
| `textio.py` | đọc file **không xê dịch offset** |
| `ner.py` | phát hiện + phân loại, bằng **từ điển dựng từ KB** |
| `labtest.py` | tên/kết quả xét nghiệm bằng **cấu trúc câu** |
| `linking.py` | gắn mã ICD/RxNorm |
| `assertion.py` | ConText/NegEx tiếng Việt |
| `scoring.py` | bộ chấm nội bộ (WER + Jaccard + P/R/F1) |
| `solve.py` | chạy đầu-cuối + 5 bất biến định dạng |

Knowledge base đã dựng xong (`data/artifacts/kb.sqlite`, 141.948 concept,
633.000 term). API đọc: `smart_medic.kb.query`.

### 1.3 Ba bộ gold — KHÔNG được gộp

| bộ | nội dung | dùng để |
|---|---|---|
| `data/probe/gold/` | 20 bệnh án **do chính dự án viết ra** rồi tự gán nhãn, 273 span | chỉ làm regression guard |
| `data/probe/gold_real/` | **9 file lấy nguyên văn từ `data/test/`**, gán tay, 333 span | ★ tín hiệu không thiên lệch **duy nhất** |
| `data/probe/gold_batch1/` | 21 file từ **MTSamples** (corpus ghi chú y khoa Mỹ) dịch/chuyển thể sang tiếng Việt, **858 span** | nội dung lâm sàng thật nhưng **không phải phân bố đích** |

⚠️ Khác cấu trúc: `gold_batch1` để nhãn trong thư mục con `annotations` (hai bộ
kia là `annotations_gold`), văn bản trong `text`.

Chất lượng `gold_batch1` đã đo: **0 lệch offset · 0 span chồng lấn** ·
5/21 file không NFC. Mật độ assertion `isNegated` 99, `isHistorical` 88,
`isFamily` 1 — **dày gấp 4–5 lần `gold_real`** (18/23/1), nên đây là bộ **duy
nhất đủ dày để đo module assertion**.

**Vì sao không gộp vào `gold_real`:** MTSamples là ghi chú y khoa Mỹ — văn phong
SOAP, đơn vị và biệt dược Mỹ. `data/test` thì 49/100 file là hỏi–đáp forum Việt
(§3.2). Gộp vào sẽ làm hỏng đúng thứ khiến `gold_real` có giá trị. Đây cũng
chính là lý do đã áp cho `gold/`.

Đọc `data/probe/gold_real/README.md` trước khi dùng — nó liệt kê cả các cụm
**phải không có span nào phủ** (đo dương tính giả).

### 1.4 Điểm hiện tại

```
gold          final 0,667   P 0,882  R 0,875  type 0,941
gold_real     final 0,433   P 0,700  R 0,715  type 0,878
gold_batch1   final 0,258   P 0,653  R 0,542  type 0,742
```

**Khoảng cách 0,23 giữa `gold` và `gold_real` là con số quan trọng nhất của tài
liệu này.** Nó là giá phải trả khi huấn luyện/hiệu chỉnh trên văn bản sạch tự
viết rồi đem chấm trên văn bản thật. Bộ sinh mới rất dễ tái tạo đúng khoảng cách
đó nếu làm ẩu.

`gold_batch1` thấp hơn nữa (0,258) vì nội dung lâm sàng dày và ngoài miền — nó
là bài kiểm tra khái quát hoá, **không phải** mục tiêu tối ưu (§6 quy tắc 1).

---

## 2. Vì sao annotation-first, không phải sinh-văn-bản-rồi-gán-nhãn

### 2.1 Bằng chứng lịch sử: cách cũ đã dự đoán SAI DẤU

`docs/gold-chan-doan-protocol.md` ghi lại một sự cố đã xảy ra: bộ gold cũ dựng
bằng **đồng thuận opus-5 × sonnet-5** nói mã chẩn đoán đáng `+5,11` điểm, còn
leaderboard nói `−1,77`. Trích nguyên văn phần chẩn đoán nguyên nhân:

> *"Hai nguồn đồng ý với nhau không mạnh hơn một nguồn, khi cả hai cùng đo 'gold
> có mã ở đây không' còn câu hỏi được chấm là 'mã của ta có đúng không'."*

Khi hai LLM cùng chọn một mã sai hợp lý, gold **đóng đinh cái sai đó**, hệ của ta
(cũng dùng LLM) khớp đúng cái sai ấy và ăn điểm nội bộ.

**Annotation-first cắt đúng nguồn nhiễu này:** mã được chọn từ KB *trước*, nên nó
đúng theo kiến tạo. Không bao giờ hỏi LLM câu khó nhất là *"cụm này là mã gì?"*.

### 2.2 Nó diệt luôn lớp bug offset

Sinh-sau-gán buộc phải căn span bằng `txt.index(...)`. Lớp lỗi đó đã gây hai sự
cố đo được trong dự án:

- `sample_output.json` của BTC lệch offset **19/19 mục** vì văn bản gốc dùng CRLF
- **20/100 file `data/test/` không ở dạng NFC**, và `100.txt` trộn NFC với NFD
  *ngay bên trong một cụm từ* — cùng chữ `"tiền sản giật"` mà một chỗ dài 13 ký
  tự, chỗ khác 16

Annotation-first ghi offset **lúc chèn chuỗi vào template**, nên sai số bằng 0
theo kiến tạo.

### 2.3 Nó sinh được thứ dữ liệu thật không có

`gold_real` chỉ có **1 span `isFamily`** trong toàn bộ 333 span — và `gold_batch1`
cũng đúng **1 span** trên 858. Khan hiếm ở cả hai bộ độc lập, nên đây là tính
chất của dữ liệu thật chứ không phải rủi ro lấy mẫu: không đủ để đo, càng không
đủ để học. Với template thì assertion do **khung câu** quyết định
(`"Bố bệnh nhân mắc {X}"` → `isFamily`), nhãn sạch tuyệt đối, sinh bao nhiêu
cũng được.

---

## 3. Cạm bẫy — đọc kỹ, đây là chỗ kế hoạch dễ chết nhất

### 3.1 Vòng lặp tự khen, phiên bản mới

Nếu **cụm từ bề mặt** cũng lấy từ tên chuẩn trong KB, model học xong chỉ biết
đúng những gì từ điển đã biết → **không cải thiện gì**.

Đây không phải lo xa. Đo trên `gold_real`:

```
95 span bỏ sót
   4  có trong từ điển   ← lỗi tra cứu
  91  KHÔNG có trong từ điển
```

Ví dụ thật: `Tim đập nhanh`, `cục máu đông`, `đi tiêu ra máu`, `viêm bao tử`
(`bao tử` = cách nói miền Nam của `dạ dày`), `ĐTD typ II`.

⇒ **Giá trị của cả kế hoạch nằm ở độ đa dạng CÁCH NÓI, không ở số lượng tài
liệu.** 10.000 tài liệu dùng lại vốn từ của KB thì vô ích; 500 tài liệu với cách
nói thật sự đa dạng thì có giá.

### 3.2 Lệch phân bố sang văn bản "sạch"

LLM sẽ viết bệnh án gọn gàng. Văn bản thật thì không. Đo trên 100 file
`data/test/`:

| đặc tính | tỉ lệ |
|---|---|
| độ dài (ký tự) | trung vị **1.838** · p10 1.426 · p90 2.957 |
| **không ở dạng NFC** | **20/100 file** |
| CRLF | 0/100 |
| có tên thuốc bị che `***` | **30/100 file** · 99 lần · độ dài mask trung vị **12** |
| có gạch đầu dòng | 90/100 |
| có mẫu `NHÃN: giá trị` | 98/100 |
| giọng hỏi–đáp / forum | **49/100** |

Ngoài ra `gold_real` cho thấy có rác OCR/splice thật (`"Tổ thương mô bệnh học"`,
`"Quảng cáo quảng cáo thiết bị thương mại miễn phí"`).

⇒ Bộ sinh phải **tái tạo phân bố này**, không phải bịa ra một phân bố đẹp.

### 3.3 Phần sạch nhất lại đáng giá ít nhất

Đo trần từng đòn bẩy trên **cả hai bộ thật** (thay dự đoán bằng đáp án cho từng
thành phần, giữ nguyên phần còn lại). Δ so với điểm hiện tại của chính bộ đó:

| đòn bẩy | gold_real | gold_batch1 |
|---|---|---|
| hiện tại | 0,433 | 0,258 |
| **thêm hết span bỏ sót** (recall) | **+0,219** | **+0,357** |
| **bỏ hết span thừa** (precision) | +0,120 | +0,077 |
| sửa hết candidates | +0,033 | +0,023 |
| sửa hết nhãn | +0,022 | +0,034 |
| sửa hết assertions | +0,021 | +0,019 |

Hai bộ độc lập, nội dung khác hẳn nhau, **cùng một kết luận**: phát hiện span ăn
đứt mọi thứ khác (+0,34 và +0,43 cho riêng recall + precision).

Điểm cần nhấn mạnh: `gold_batch1` có **188 assertion** (99+88+1) so với **42**
của `gold_real` — **dày gấp 4 lần** — vậy mà trần assertion **vẫn chỉ +0,019**.
Lý do: cả ba thành phần
điểm đều bị chặn bởi phát hiện span. **Không tìm ra span thì không có gì để gắn
mã hay gắn assertion.** Nên ưu tiên thiết kế phải đặt vào phát hiện, và chấp
nhận rằng đó đúng là chỗ rủi ro §3.1 rình.

---

## 4. Thiết kế

Cách gọn nhất để hình dung toàn bộ thiết kế: **dựng một đồ thị bệnh án, rồi kết
xuất đồ thị đó ra văn bản.**

| thành phần đồ thị | là gì | được gì |
|---|---|---|
| **nút** | khái niệm + mã lấy từ KB | mã **đúng theo kiến tạo** |
| **cạnh ngữ cảnh** | phủ định / người nhà / tiền sử | assertion là *thuộc tính của cạnh*, không phải phán đoán |
| **cạnh mạch lạc** | thuốc ↔ bệnh (qua nhóm ATC, §4.5) | giải vấn đề tuân thủ ở §3.1 |
| **kết xuất** | khung câu + cách nói | offset ghi **lúc chèn** |

### 4.1 Nguyên tắc: tách thứ KIỂM SOÁT khỏi thứ LẤY ĐA DẠNG

| kiểm soát bằng template — nhiễu = 0 | tra bảng **tất định** — nhiễu = 0 | còn lại phải hỏi LLM |
|---|---|---|
| mã ICD/RxNorm (chọn từ KB) | **cách nói bề mặt của THUỐC** (§4.4) | **cách nói bề mặt của CHẨN_ĐOÁN** |
| offset (ghi lúc chèn) | dạng bào chế, nhóm thuốc tiếng Việt | **cách nói bề mặt của TRIỆU_CHỨNG** |
| assertion (khung câu quyết định) | | |
| nhãn type (biết trước khi chèn) | | |
| khung câu, thể loại, nhiễu | | |

Chỉ hai cột phải thêm **thông tin mới**. Mọi thứ khác chỉ để làm dữ liệu trông
giống thật.

★ **Cột giữa trước đây nằm ở cột phải.** Nhánh THUỐC giờ có nguồn thẩm quyền,
miễn phí, tất định (§4.4) — bớt được một chỗ phải tin LLM, đúng tinh thần §2.1.

### 4.2 Luồng

```
1. LẤY MẪU KHÁI NIỆM
   từ kb.sqlite: chọn (code, type) phân tầng theo chương ICD / tầng TTY RxNorm

2a. CÁCH NÓI NHÁNH THUỐC          ← TẤT ĐỊNH, KHÔNG DÙNG LLM
    tra data/knowledge_base/atc/ddd.csv: tên tiếng Việt → mã ATC → RxCUI
    → 608 tên đơn chất nối thẳng được vào KB (§4.4)

2b. CÁCH NÓI NHÁNH CHẨN_ĐOÁN + TRIỆU_CHỨNG   ← CHỖ DUY NHẤT CÒN DÙNG LLM
    với mỗi khái niệm, xin N biến thể bề mặt tiếng Việt thật
    BẮT BUỘC: yêu cầu đích danh cách nói dân dã, viết tắt, sai chính tả,
              vùng miền; CẤM trùng tên chuẩn trong KB
    → đóng băng thành file, commit vào git

3. LẮP KHUNG
   chọn khung câu + thể loại + assertion, chèn cụm từ, GHI OFFSET lúc chèn

4. TIÊM NHIỄU
   theo đúng phân bố §3.2: NFD 20%, mask *** 30%, gạch đầu dòng, rác OCR

5. XUẤT
   .txt + .json cùng định dạng gold_real (để dùng chung bộ chấm)
```

### 4.3 Bước 2b là bước quyết định — làm cho đúng

> Chỉ áp cho **CHẨN_ĐOÁN** và **TRIỆU_CHỨNG**. Nhánh THUỐC đã có nguồn tất định
> ở §4.4 — **đừng hỏi LLM cách nói tên thuốc nữa.**

Prompt phải yêu cầu **cách nói mà bệnh nhân/bác sĩ Việt thật sự viết**, và
**cấm** trả về tên chuẩn. Ví dụ hình dạng đầu ra mong muốn cho `K29.7`
(*Viêm dạ dày, không xác định*):

```
viêm bao tử · đau bao tử · viêm dạ dày · đau dạ dày · viêm bao tử mạn
```

Kiểm chất lượng bắt buộc: **duyệt tay 100 cặp `(cách nói → mã)` ngẫu nhiên**;
≥ 90 phải hợp lý về y khoa. Dưới ngưỡng thì siết prompt, **không** đem đi sinh
tài liệu.

★ Dùng model **khác họ** với model sẽ dùng ở pipeline nếu có — `protocol §4`
quy tắc ③, để sai số không tương quan.

### 4.4 Bảng ATC/DDD — nguồn TẤT ĐỊNH cho cách nói tên thuốc

`data/knowledge_base/atc/ddd.csv` là bảng DDD của Bộ Y tế theo **ATC/DDD Index
2016**. Đã khảo sát:

| đại lượng | số đo |
|---|---|
| dòng dữ liệu | 2.019 |
| mã ATC phân biệt | 940 |
| tên thuốc tiếng Việt | 1.065 |
| **dạng bào chế** tiếng Việt | **71** |
| **nhóm thuốc** tiếng Việt | **29** |

Ánh xạ **tất định** `tên tiếng Việt → mã ATC cấp 5 → RxCUI`, join qua
`RXNCONSO.RRF` với `SAB=ATC`, `SUPPRESS=N`, mã dài **đúng 7 ký tự** (cấp 5).

- Lọc thuốc phối hợp (`+`) và ký hiệu danh mục (`*`, `(`) → **669 tên đơn chất**
- Trong đó **608 nối được thẳng vào KB**
- Ví dụ: `Acetazolamid`→`167` · `Acetylcystein`→`197` · `Adapalen`→`60223`

**Vì sao đây là cải thiện lớn.** Chính tả dược phẩm tiếng Việt lệch khỏi tiếng
Anh **một cách có hệ thống** (bỏ `-e` cuối, `-ine`→`-in`), và **766/1065 tên
(72%) chưa có trong từ điển KB**. Trước đây phải nhờ LLM đoán đúng những biến thể
này — đúng loại câu hỏi mà §2.1 nói là không nên tin LLM. Giờ có nguồn thẩm
quyền, miễn phí, tất định.

**License:** `ATC` có `SRL=0` trong `RXNSAB.RRF` — không hạn chế redistribute.
Quan trọng vì PRD §5 buộc nộp cả dữ liệu cho BTC.

⚠️ **Dạng bào chế và nhóm thuốc KHÔNG vào KB** — chúng không phục vụ 4 hàm API
của KB. Đóng băng vào `data/curated/` để riêng bộ sinh dùng.

### 4.5 Đã cân nhắc và LOẠI: SNOMED CT cho quan hệ thuốc↔bệnh

> Ghi lại để agent thực thi **không phải khảo sát lại**.

Câu hỏi: SNOMED CT International có cho được quan hệ mạch lạc thuốc↔bệnh không,
để §3.1 (bệnh án phải hợp lý) có nguồn? **Không.**

Đo trên `sct2_Relationship_Snapshot_INT_20260801.txt`: **102 loại quan hệ
active, không loại nào là chỉ định/điều trị.** Gần nhất chỉ có `Has intent`,
`Plays role`, `Has focus`.

Thứ SNOMED thực sự có, theo số cạnh active:

| quan hệ | số cạnh |
|---|---|
| `Finding site` | 109.781 |
| `Associated morphology` | 82.194 |
| `Interprets` | 41.441 |
| `Due to` | 20.143 |
| `Causative agent` | 18.801 |

Đều là **bệnh→giải phẫu/nguyên nhân**, không phải thuốc→bệnh.

Chi phí nếu vẫn dùng: Phase 3 đã chốt SNOMED là *nguồn cho*, **không tạo concept
trong KB** — nên không có `concept_id` để trỏ tới. Sẽ phải nạp **383.853
concept**, bắc cầu qua ExtendedMap, rồi dịch tên tiếng Anh sang tiếng Việt.

**Thay thế rẻ hơn, đã có sẵn:** chữ cái đầu của mã ATC chính là nhóm giải phẫu,
ánh xạ khá sạch sang chương ICD:

```
A→K/E   B→D   C→I   J→A/B   L→C/D   M→M   N→F/G   R→J
```

Đủ mạch lạc cho mục đích sinh dữ liệu. Bộ sinh **không cần chỉ định chính xác**
— chỉ cần đủ hợp lý để LLM không tự ý sửa danh sách khái niệm khi kết xuất.

### 4.6 Khung câu — nơi có tín hiệu học được

Đây là phần template kiểm soát được và dạy được nhiều nhất. Bằng chứng: xem ngữ
cảnh các span **bỏ sót** hiện tại —

```
không thấy  buồn nôn, ⟦nôn⟧, ⟦ớn lạnh⟧, ⟦thay đổi chức năng ruột⟧
                ↑ BẮT được       ↑ ba cái sau đều TRƯỢT

• Tim đập nhanh, khó thở
  ⟦TRƯỢT⟧          ↑ bắt được
```

**Ta bắt mục đầu của danh sách rồi trượt phần còn lại.** Đó là mẫu *liệt kê đồng
vị*, và một template sinh ra vô hạn biến thể độ dài danh sách sẽ dạy nó rất rẻ.

Các họ khung tối thiểu phải có:

| họ khung | ví dụ | dạy điều gì |
|---|---|---|
| liệt kê đồng vị | `sốt, ho, {X}, {Y}, {Z}` | ← ưu tiên cao nhất |
| gạch đầu dòng | `• {X}` | 90/100 file có |
| nhãn hai chấm | `Chẩn đoán: {X}` | 98/100 file có |
| phủ định trải dài | `không thấy {X}, {Y}` | `isNegated` |
| tiền sử | `Tiền sử {X}, {Y}` | `isHistorical` |
| người nhà | `Tiền sử gia đình: mẹ mắc {X}` | `isFamily` — thật chỉ có 1 span |
| hỏi–đáp | `Chào bác sĩ, em bị {X}…` | 49/100 file |
| giáo dục/blog | `{X} là bệnh gì?` | ngữ cảnh giả định |

---

## 5. Kế hoạch triển khai

### Bước 0 — chuẩn bị (nửa ngày)

```bash
pip install -e ".[dev]"
python -m pytest -q          # phải xanh trước khi bắt đầu
smk kb validate              # phải 20/20 rule
```

Đọc: `data/probe/gold_real/README.md`, `src/smart_medic/stages/textio.py`,
`src/smart_medic/stages/scoring.py`.

Chốt baseline để về sau so:

```bash
python -c "..."   # chấm gold_real, ghi docs/reports/synth-baseline.json
```

### Bước 1 — lấy mẫu khái niệm (`stages/synth/sample.py`)

Từ `kb.sqlite`, chọn ~800 khái niệm:

- **CHẨN_ĐOÁN**: phân tầng theo chương ICD, tỉ lệ theo phân bố chương trong
  `gold_real` (74 span). Loại chương V–Y (nguyên nhân ngoại sinh, không bao giờ
  là đáp án) và mã khoảng (`E10-E14`).
- **THUỐC**: tầng `IN`/`PIN` cho mention trần, `SCD`/`SBD` cho mention có hàm
  lượng. Quy tắc đã kiểm chứng: *mention có hàm lượng → SCD; không có → IN*.
  Cách nói tiếng Việt lấy từ bảng ATC/DDD (§4.4), **không hỏi LLM**.
  ⚠️ **Chỉ sinh biệt dược mà KB tra được** — xem §7.
- **TRIỆU_CHỨNG**: chương R + các cụm có đầu ngữ cảm giác
  (xem `SYMPTOM_HEADS` trong `ner.py`).
- **TÊN_XN / KẾT_QUẢ_XN**: không có trong KB (địa hạt LOINC). Lấy từ chính
  `gold_real` **chỉ để làm hạt giống cho LLM sinh biến thể**, không dùng nguyên.

### Bước 2 — sinh cách nói (`stages/synth/surface.py`)

**2a — nhánh THUỐC, tất định, không gọi LLM.** Trích từ
`data/knowledge_base/atc/ddd.csv` theo §4.4, kết xuất ra `data/curated/`:

| file | nội dung |
|---|---|
| `drug_surface_atc.v1.jsonl` | 608 cặp `tên tiếng Việt → RxCUI` |
| `dose_forms_vi.v1.txt` | 71 dạng bào chế |
| `drug_groups_vi.v1.txt` | 29 nhóm thuốc |

Hai file sau **không nạp vào KB** — chỉ bộ sinh dùng.

**2b — nhánh CHẨN_ĐOÁN + TRIỆU_CHỨNG.** Gọi LLM một lần, **đóng băng** kết quả
ra `data/curated/surface_forms.v1.jsonl`, commit vào git kèm `sha256`.

> Ràng buộc tái lập (PRD §8): **không được gọi API lúc build**. Tiền lệ đã có
> trong dự án: từ đồng nghĩa E5 của KB sinh một lần rồi đóng băng.

**Cổng:** duyệt tay 100 cặp, ≥ 90 hợp lý. Không đạt → sửa prompt, làm lại.
Cổng này chỉ áp cho 2b — 2a tất định nên không cần duyệt.

### Bước 3 — lắp khung + tiêm nhiễu (`stages/synth/render.py`)

Sinh ~500 tài liệu. Bất biến bắt buộc, kiểm bằng test:

1. `text[start:end] == span.text` với **mọi** span
2. span không chồng lấn
3. `candidates` rỗng với `TRIỆU_CHỨNG`/`TÊN_XN`/`KẾT_QUẢ_XN`
4. phân bố nhiễu khớp §3.2 trong sai số ±5 điểm phần trăm

Dùng lại `stages/solve.py::check_invariants` — nó đã cài sẵn 1–3.

### Bước 4 — huấn luyện (`stages/tagger.py`)

- Kiến trúc: token classification BIO, 5 nhãn.
- Base: **XLM-R** (`xlm-roberta-base`). Lý do: ViMedNER cho thấy XLM-R nhìn chung
  vượt PhoBERT/ViHealthBERT trên NER y khoa tiếng Việt, và nó chạy
  syllable-level nên **không cần tách từ VnCoreNLP** — bước mà làm sai là nguồn
  lỗi phổ biến.
- Phần cứng đã đo trên máy dev (M3 Pro, MPS, **không CUDA**): model cỡ BERT-base
  đạt ~187 mẫu/s → vài phút mỗi epoch. **Không phải rào cản.**
- Tái lập: ghim seed, ghim revision base model, ghi `sha256` của corpus vào
  metadata checkpoint.

### Bước 5 — lai với luật hiện có

Model cho **span + type**. Giữ nguyên phần luật đang mạnh:

- `linking.py` gắn mã — ⚠️ **bắt buộc `rerank=True`**; nó mặc định TẮT ở
  `search_lexical`, quên là mất 45 điểm R@1 ở nhánh thuốc
- `labtest.py` giá trị đo
- `ner.py::detect_masked_drugs` thuốc bị che

### Bước 6 — cổng hiệu quả

Chấm **chỉ trên `gold_real`**. Bắt buộc pass toàn bộ:

- [ ] `final` trên `gold_real` tăng ≥ **0,03** so với baseline 0,433
- [ ] `span_recall` tăng ≥ 0,05 (đây là mục tiêu chính, trần +0,219)
- [ ] `span_precision` **không giảm** quá 0,02
- [ ] Các cụm bẫy ở `gold_real/README.md` vẫn **không có span nào phủ**
- [ ] `smk solve` chạy hết 100 file, 5 bất biến pass, không có span lệch offset
- [ ] Toàn bộ chạy lại được từ máy sạch, không gọi mạng

**Không đạt → ghi kết quả âm vào `docs/reports/` và giữ pipeline luật.** Dự án
này đã bỏ 2/4 nguồn làm giàu KB và toàn bộ hướng dense vì đo thấy có hại; đây là
kỷ luật bắt buộc, không phải tuỳ chọn.

---

## 6. Quy tắc không được phá

1. **Không bao giờ báo cáo số đo trên chính tập sinh ra.** Chấm trên `gold_real`
   và chỉ `gold_real`. Trong phiên làm việc trước, hai bộ đo nhỏ đã nói dối theo
   hướng có lợi: bộ 3 file cho 0,530 còn bộ 9 file cho 0,407 trên cùng hệ thống.
2. **Không gộp ba bộ gold khi báo cáo.** `gold_real` là cổng quyết định;
   `gold_batch1` chỉ để đo khái quát hoá ngoài miền và đo module assertion;
   `gold` chỉ làm regression guard. Báo cáo riêng từng bộ.
3. **Không gọi LLM lúc build.** Sinh một lần, đóng băng, commit.
4. **Không `unicodedata.normalize` trên chuỗi dùng tính offset.** Chuẩn hoá chỉ
   trên bản sao dùng để so khớp.
5. **Không đọc file bằng `Path.read_text()`.** Dùng
   `stages.textio.read_document()` — nó đặt `newline=''`.
6. **Không chỉnh tham số để ép một ca cụ thể qua.** `gold_real` chỉ 9 file; fit
   vào n = 1 sẽ phá ca khác. Đã xảy ra một lần với luật TTY prior.

---

## 7. Rủi ro

| rủi ro | mức | cách chặn |
|---|---|---|
| Cách nói lấy từ KB → model không học được gì mới | **Cao** | §4.3 cấm trùng tên chuẩn; cổng duyệt tay 100 cặp |
| Văn bản sinh ra quá sạch → lệch phân bố | **Cao** | §3.2 tiêm nhiễu theo số đo thật; cổng ±5 điểm phần trăm |
| Overfit vào 9 file `gold_real` | **Cao** | Hạn chế số cấu hình thử; không tinh chỉnh theo từng ca |
| LLM gán sai mã cho cách nói nó sinh ra | Trung bình | Cổng duyệt tay; dùng model khác họ. Nhánh THUỐC đã hết rủi ro này (§4.4) |
| **Sinh biệt dược KB không tra được** | **Cao** | Xem ngay dưới đây |
| Model phá phần luật đang đúng | Trung bình | Cổng precision không giảm; cấu hình lai ở Bước 5 |
| Weights phá tái lập (PRD §8 — cài lại không được thì **bị loại**) | **Cao** | Ghim seed/revision, đóng gói weights, ghi sha256 |

### 7.1 Khoảng trống biệt dược — KB không tra được

`gold_batch1` có **13 mention thuốc (8 mã phân biệt)** mà KB không tra được. Đã
truy nguyên nhân: **gold đúng, KB thiếu.**

Cả 8 đều là RXCUI thật — `Rocephin` 9449, `Levothroid` 218001, `Lorcet` 491666,
`Tapazole` 224936, `Vicodin` 128793, `Micro-K` 218365, `Levsinex` 580253,
`penicillin` 7986 — và **không** có bản ghi remap trong `RXNCUI.RRF`. Nhưng atom
do RxNorm sở hữu bị `SUPPRESS=O`, mà luật Phase 2 đòi *"≥1 atom `SAB=RXNORM`
**và** `suppress=N`"*, nên **cả concept bị loại**.

Nới luật thành *"≥1 atom `suppress=N` từ bất kỳ nguồn nào"* sẽ thêm
**+146.691 concept** (124.708 → 271.399).

**CHƯA QUYẾT** — chờ tín hiệu leaderboard, **không tự quyết bằng số đo nội bộ**
(§6 quy tắc 1, và tiền lệ §2.1).

⚠️ **Hệ quả bắt buộc cho bộ sinh:** **đừng sinh biệt dược mà KB không tra
được.** Nếu sinh, ta tạo ra dữ liệu huấn luyện dạy model gán một mã mà pipeline
**không thể trả về** — tự tay dựng trần điểm cho chính mình.

---

## 8. Tài liệu tham khảo trong repo

| đường dẫn | nội dung |
|---|---|
| `docs/PRD.html` | đề bài, metric, phân tích chiến lược |
| `data/probe/gold_real/README.md` | thành phần bộ gold thật + danh sách cụm bẫy |
| `data/knowledge_base/atc/ddd.csv` | bảng DDD Bộ Y tế — nguồn tất định cho tên thuốc tiếng Việt (§4.4) |
| `docs/gold-chan-doan-protocol.md` | sự cố gold cũ dự đoán sai dấu, ngưỡng hoà vốn |
| `docs/s1-embedding-plan.md` | vì sao hướng embedding bị hoãn (cổng đóng hai lần) |
| `docs/kb-pipeline-plan.md` | KB đã dựng thế nào |
| `src/smart_medic/stages/scoring.py` | bộ chấm + giả định về cách ghép entity |
