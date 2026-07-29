# Handoff — hoàn thiện gold annotation cho `restyled/`

> Tài liệu tự chứa. Agent nhận việc **không cần** ngữ cảnh hội thoại trước đó.
> Đọc hết mục 1–6 trước khi chạy bất cứ thứ gì; mục 7 là prompt sẵn dùng.

---

## 1. Mục tiêu

Bộ `data/generated_medical_records/restyled/` gồm **162 ghi chép lâm sàng tiếng Việt**
kèm nhãn NER sinh tự động (`annotations/`). Nhiệm vụ: **thẩm định lại từng nhãn** và
xuất bản gold hoàn chỉnh sang `annotations_gold/`.

Đây là **hiệu đính**, không phải gán nhãn lại từ đầu. Nhãn có sẵn phần lớn đúng — giữ
nguyên khi đúng, chỉ sửa khi có lý do y khoa rõ ràng.

Bối cảnh bài toán: Viettel AI Race 2026 Vòng 1, xem `docs/PRD.html`. Điểm =
`0.3·text(1−WER) + 0.3·assertions(Jaccard) + 0.4·candidates(Jaccard)`.

---

## 2. Trạng thái hiện tại

| | |
|---|---|
| Đã hoàn tất | **100/162 file**, validator sạch (0 error, 0 warning) |
| Còn lại | **62 file** — danh sách sinh bằng lệnh ở mục 7.3 |
| Entity trong 100 file gold | 4.715 (từ ~3.470 nhãn gốc, +36%) |
| Pass chuẩn hoá toàn corpus | **CHƯA CHẠY** — bắt buộc, xem mục 4 |

100 file đã làm do 14 reviewer chạy song song, mỗi người chỉ thấy 11–12 file. Vì thế
tồn tại **những điểm không nhất quán giữa các batch** mà không reviewer nào tự thấy
được — mục 4 liệt kê và mục 7.1 xử lý.

⚠️ **Chưa file nào được kiểm tra chéo bởi người thứ hai.** Các reviewer tự báo cáo là
đã theo guideline; validator chỉ bảo đảm tính hợp lệ hình thức (offset, schema, mã tồn
tại), **không** bảo đảm đúng về y khoa.

---

## 3. Quy ước gán nhãn

### 3.1 Schema

List các dict, sắp theo `position[0]` tăng dần:

```json
[
  {
    "text": "chuỗi con CHÍNH XÁC của văn bản",
    "type": "CHẨN_ĐOÁN",
    "candidates": ["I25.1"],
    "assertions": ["isHistorical"],
    "position": [123, 145]
  }
]
```

Ghi UTF-8, `ensure_ascii=False`, `indent=2`.

**Bất biến tuyệt đối:** `text == raw_text[position[0]:position[1]]`.

⚠️ **Bẫy Unicode:** 41/162 file `.txt` lưu ở dạng **NFD (tổ hợp)**, 121 file ở NFC.
Chuỗi gõ tay trong code hầu như luôn là NFC ⇒ `txt.index("chuỗi tiếng Việt")` sẽ
**trượt** trên file NFD. Luôn lấy span từ chính chuỗi `txt` đã đọc:

```python
import unicodedata
txt = open(path, encoding='utf-8').read()
needle = unicodedata.normalize('NFD', "cụm cần tìm")   # hoặc NFC, thử cả hai
i = txt.find(needle, hint_start)                      # hint_start tránh bắt nhầm lần khác
span = txt[i:i+len(needle)]                           # DÙNG span NÀY làm "text"
```

### 3.2 Năm loại `type`

| type | Định nghĩa | Ví dụ |
|---|---|---|
| `TRIỆU_CHỨNG` | Triệu chứng / dấu hiệu khi khám | "ho đờm xanh", "tiếng thổi", "phù chân" |
| `TÊN_XÉT_NGHIỆM` | **Tên** xét nghiệm / chỉ số đo | "INR", "TSH", "CT scan", "Huyết áp" |
| `KẾT_QUẢ_XÉT_NGHIỆM` | **Giá trị** kết quả, kèm đơn vị | "12", "14,43 K/uL", "120/80", "âm tính" |
| `CHẨN_ĐOÁN` | Tên bệnh được chẩn đoán / tiền sử | "viêm phổi", "rung nhĩ", "hội chứng Down" |
| `THUỐC` | Thuốc bệnh nhân dùng / được kê | "Coumadin", "amlodipine 10 mg po daily" |

**Ranh giới hay nhầm:**

- **Triệu chứng vs chẩn đoán** — theo vị trí trong văn bản: dưới mục Chẩn đoán/Tiền sử
  → `CHẨN_ĐOÁN`; trong phần than phiền/khám → `TRIỆU_CHỨNG`.
- **Chất phân tích ≠ thuốc.** "triglycerides", "protein", "albumin", "kali", "glucose",
  "cholesterol", "creatinine" trong ngữ cảnh xét nghiệm là `TÊN_XÉT_NGHIỆM`. Chỉ là
  `THUỐC` khi rõ ràng dùng để điều trị ("bù kali đường tĩnh mạch").
- **Thủ thuật/phẫu thuật không thuộc 5 loại nào** → bỏ. "Cắt đại tràng", "xạ trị",
  "nội soi", "thận nhân tạo". Nếu văn bản nêu bệnh lý nền ("Sửa chữa **thoát vị**")
  thì gán `CHẨN_ĐOÁN` cho riêng cụm chỉ bệnh. Không gán cho bộ phận cơ thể đơn thuần.
- **Sinh hiệu** → gán cặp: "Huyết áp" (`TÊN_XÉT_NGHIỆM`) + "120/80"
  (`KẾT_QUẢ_XÉT_NGHIỆM`). Tương tự mạch, nhịp thở, nhiệt độ, SpO2, cân nặng.
- **Từ chung chung** ("xét nghiệm", "kiểm tra", "chỉ số", "kết quả" đứng trần) → bỏ.
  Giữ khi có bổ ngữ ("xét nghiệm máu").
- **Lối sống không phải chẩn đoán** — "hút thuốc", "uống rượu", "sử dụng ma túy"
  → **không gán**, dù ICD-10 có mã `Z72.x`. Chỉ gán khi nêu như bệnh lý thật
  ("nghiện rượu" → `F10.2`).
- **Lớp thuốc chung** ("thuốc lợi tiểu", "kháng sinh", "thuốc chống đông") → **không gán**.
- **Span bị che `*******`** (de-identification của mtsamples) → **xoá**.
- **Thuốc trong mục "Dị ứng"** vẫn gán `THUỐC`, `assertions` để `[]`.

### 3.3 Ranh giới span

Chấm bằng **WER trên `text`** ⇒ không thừa không thiếu từ nào.

- **Thuốc: lấy CẢ liều / dạng / đường dùng / tần suất** khi đi liền sau tên thuốc.
  Theo gold mẫu PRD: `"amlodipine 10 mg po daily"`. Liều ở câu khác thì chỉ lấy tên.
- **Bệnh: lấy trọn cụm danh từ**, gồm bổ ngữ làm rõ: "rung nhĩ **mãn tính**",
  "Rối loạn đông máu **do Coumadin**".
- **Không lấy từ dẫn**: "chẩn đoán", "tiền sử", "bị", "mắc".
  Sai `"Tiền sử vỡ đại tràng"` → đúng `"vỡ đại tràng"`.
- **Không lấy từ phủ định**: "không ho" → span `"ho"` + `isNegated`.
- **Không gộp nhiều khái niệm**: "đau lưng và đau khớp" → **2** span.
- **Mọi lần nhắc đều gán nhãn.** Bệnh xuất hiện 5 lần → 5 span. Đây là thiếu sót lớn
  nhất của nhãn gốc, đặc biệt ở thể `van_xuoi` / `pho_bien`.

### 3.4 `assertions`

Chỉ cho `CHẨN_ĐOÁN`, `THUỐC`, `TRIỆU_CHỨNG`. Loại khác **luôn `[]`** (validator chặn).

Jaccard quy ước `J=1` khi cả hai rỗng ⇒ **gán thừa bị phạt nặng. Chỉ gán khi văn bản
nói rõ.**

| Assertion | Gán khi |
|---|---|
| `isNegated` | Bị phủ định / loại trừ: "không ho", "chưa ghi nhận phù", "Doppler âm tính với DVT" |
| `isFamily` | Thuộc người nhà: "Bố bệnh nhân bị đái tháo đường" |
| `isHistorical` | Tiền sử / bệnh cũ / đã ngưng |

**Quy tắc phạm vi (ConText):**

- Phủ định lan hết mệnh đề liệt kê: "Không sốt, ho, khó thở" → cả ba `isNegated`.
- Bị chặn bởi từ đối lập: "không sốt **nhưng** có ho" → chỉ "sốt" negated.
- Cẩn thận **phủ định giả**: "bệnh lý **không** gian khí thùy trên" — chữ "không" ở đây
  thuộc từ "không gian", không phủ định gì. Tương tự "về nhà **không** lâu thì nôn".
- Câu điều kiện/cảnh báo không phải phủ định: "Gọi báo ngay nếu xuất hiện nôn, đau bụng"
  → `[]`, không phải `isNegated`.

---

## 4. Quyết định chuẩn hoá toàn corpus

Reviewer chạy song song đã **chọn khác nhau** ở các điểm sau. Chốt như dưới đây.

| # | Quyết định | Trạng thái trong 100 file |
|---|---|---|
| **D1** | Lối sống (`Z72.x`) → **xoá** | 17 span cần xoá (batch 1–5 có gán) |
| **D2** | Lớp thuốc chung → **xoá** | 10 span cần xoá |
| **D3** | Từ xét nghiệm chung chung → **xoá** | đa số đã xoá |
| **D4** | `ICD10.csv` là thẩm quyền, không phải WHO | 14 ca cần rà tay |
| **D5** | `isHistorical` cho danh sách thuốc | batch 3 lệch, cần sửa |
| **D6** | `isHistorical` theo từ dẫn hiển ngôn | nhất quán |
| **D7** | `isFamily` một mình | nhất quán |

**D4 — `ICD10.csv` (danh mục BYT) là thẩm quyền.** Bảng này **đặt lại nghĩa** nhiều mã
so với WHO: `K32` = "Xuất Huyết Tiêu Hóa" (WHO: rò dạ dày–tá tràng). 7.729/13.189 mã
không có bản đối chiếu ICD-10-CM. ⇒ Ưu tiên mã có **nhãn tiếng Việt khớp sát mention
nhất**. Hệ quả: `xuất huyết tiêu hóa cao` → `K32.0`; `hen suyễn` trần → `J45`
(nhãn "Hen [suyễn]"); `rung nhĩ` trần → `I48`.

⚠️ D4 **không được tự động hoá**. Khớp chữ đôi khi sai y khoa: "hẹp động mạch chủ" khớp
nhãn `Q25.3` (*hẹp bẩm sinh*) nhưng ở người lớn phải là `I35.0` (*hẹp van mắc phải*).
`normalize.py` chỉ **báo cáo** D4, không sửa.

**D5 — `isHistorical` cho thuốc.** Có tiêu đề mục ("Thuốc đang dùng", "Thuốc tại nhà",
"Thuốc trước nhập viện") → `isHistorical`, theo đúng gold mẫu PRD ("Danh sách thuốc
**trước nhập viện**"). Văn xuôi "hiện đang dùng…" và thuốc kê mới ở phần Kế hoạch → `[]`.

**D6.** Có "tiền sử …" hiển ngôn hoặc nằm dưới mục "Tiền sử bệnh"/"Tiền sử phẫu thuật"
→ `isHistorical`, kể cả bệnh mạn đang hoạt động. Mục "Tiền sử xã hội" → `[]`.

**D7.** `isFamily` một mình; chỉ thêm `isHistorical` khi văn bản nói rõ tình trạng người
nhà thuộc quá khứ (đã mất, đã khỏi). Không gán `isFamily` cho câu giả định trong bài
phổ biến kiến thức ("nếu gia đình bạn có tiền sử ung thư vú").

---

## 5. Mã chuẩn (`candidates`)

Chỉ `CHẨN_ĐOÁN` (ICD-10) và `THUỐC` (RxNorm). Loại khác **luôn `[]`**.

### 5.1 Nguyên tắc chung

- **Xuất đúng 1 mã, hoặc `[]`.** Ngoại lệ: thuốc phối hợp → liệt kê **tất cả** hoạt chất
  (`Vicodin` → `["5489","161"]`, `Advair` → `["36117","41126"]`). Đo trên gold: THUỐC có
  8,6% doublet, CHẨN_ĐOÁN có 0%.
- **Mã ICD phải tồn tại trong `data/knowledge_base/ICD10.csv`** — validator kiểm.
- **Mã RxNorm phải có atom `sab=RXNORM`.** Nếu chỉ có `sab=VANDF` thì **không hợp lệ**.
  Các mã đã biết là rác: `7986` penicillin, `433` albumin, `8859` protein,
  `10808` triglycerides, `704806` kali, `89905` multivitamins, `316981` syrup,
  `715068` pediasure, `215839` calcium+vitD, `1048113` acid folic (→ dùng `4511`).
- **ICD được phép tổng quát hoá lên mã 3 ký tự** khi văn bản không nêu chi tiết.

### 5.2 Lỗi mã ICD lặp lại nhiều lần trong dữ liệu gốc

| Mention | Mã sai | Mã đúng | Vì sao |
|---|---|---|---|
| bệnh động mạch vành | `I79` | `I25.1` / `I25.9` | `I79` là bệnh ĐM trong bệnh phân loại nơi khác |
| đái tháo đường | `O24.0` | `E14.9` / `E11.9` | `O24.0` là ĐTĐ **thai kỳ** |
| Ung thư bàng quang | `D30.3` | `C67` | `D30.3` là u **lành** |
| Phì đại tuyến tiền liệt | `D29.1` | `N40` | `D29.1` là u **lành**, BPH là tăng sản |
| Thiếu máu | `D46.4` | `D64.9` / `D62` | `D46.4` là thiếu máu kháng trị (MDS) |
| chậm phát triển (trẻ) | `P05.9` | `R62.0` | `P05.9` là thai chậm phát triển trong tử cung |
| đột quỵ (biến cố) | `I69.4` | `I64` | `I69.4` là **di chứng** |
| Đau đầu gối | `R51` | `M25.5` | `R51` là đau **đầu** |
| COPD | `[]` | `J44.9` | bỏ trống dù tra được |

### 5.3 ⚠️ RxNorm — vấn đề CHƯA CHỐT: `SCD` hay `IN`?

Xem `docs/decisions/0001-drug-tty.md`. Bằng chứng mới thu được (chưa có trong ADR):

**Ví dụ gold trong PRD có 11 span thuốc, không phải 4:**

| span | mã gold | tty |
|---|---|---|
| amlodipine 10 mg po daily | 308135 | `SCD` |
| aspirin 81 mg po daily | 243670 | `SCD` |
| metoprolol succinate xl 50 mg po daily | 866436 | `SCD` |
| guaifenesin ml po q6h:prn | 392085 | `SCD` |
| **nystatin oral suspension 5 ml po qid:prn** | **7597** | **`IN`** |
| acetaminophen 325-650 mg po q6h:prn | 313782 | `SCD` |
| pravastatin 40 mg po daily | 904475 | `SCD` |
| **docusate sodium 100 mg po bid** | **1099278** | **`SCDC`** |
| senna 8.6 mg po bid:prn | 312935 | `SCD` |
| clonazepam 0.5 mg po qam:prn | 197527 | `SCD` |
| clonazepam 1.5 mg po qhs | 197528 | `SCD` |

**9 `SCD` / 1 `SCDC` / 1 `IN`.** `nystatin` có cả dạng bào chế lẫn thể tích nhưng vẫn về
`IN`, vì "5 ml" là thể tích liều dùng chứ không phải hàm lượng ⇒ **gold thích ứng theo
mức chi tiết mà span cung cấp**, không phải "luôn SCD".

Luật đọc ra từ đó, tái tạo được **8/9** span gold (`scd_probe3.py`):

```
có hàm lượng   → SCD, mặc định "Oral Tablet", lấy hàm lượng thật gần nhất
                 (clonazepam 1.5 mg → viên 1 MG vì không có viên 1,5 mg)
không hàm lượng → IN
```

Ca trượt duy nhất: `docusate sodium` — gold chọn `SCDC` trong khi `amlodipine … po`
cùng cấu trúc lại chọn `SCD`. Mâu thuẫn nội tại của gold.

**Mức rủi ro thực tế — nhỏ hơn ADR 0001 ước lượng:**

ADR viết "chọn sai tầng ⇒ Jaccard = 0 cho **mọi** entity THUỐC". Điều đó **không đúng
với corpus này**:

| | span | % |
|---|---:|---:|
| THUỐC **không** có hàm lượng → cả hai quy ước đều cho `IN`, **không khác gì nhau** | 503 | 81,4% |
| THUỐC có hàm lượng → hai quy ước **khác nhau** | 115 | 18,6% |

115/1.640 entity mang mã = **7,0%**, tương đương tối đa **~1,1 điểm/100**. Tranh chấp
này đáng giải quyết nhưng **không phải rủi ro sống còn**, và không nên chặn các việc khác.

**Khuyến nghị:** giữ nguyên `IN` trong 100 file đã làm, **tham số hoá `target_tty`** ở
pipeline như ADR 0001 yêu cầu, và chỉ chuyển sang `SCD` khi có kết quả probe thực nghiệm.

Nếu quyết định chuyển: `scd_probe3.py` sinh 91 đề xuất, nhưng **11% sai hoạt chất** do
khớp token trên tên biệt dược (`Benadryl` → benazepril, `Protonix` → soy protein,
`Synthroid` → synthetic camphor). **Phải sửa: biệt dược → hoạt chất qua
`brand_to_ingredient.json` TRƯỚC, rồi mới tra sản phẩm theo hoạt chất + hàm lượng.**
Sau khi vá, hai nhóm có độ tin cậy khác nhau:
- **54 span generic** (`atenolol 25 mg`) — có tiền lệ gold trực tiếp.
- **37 span biệt dược** (`Lipitor 40 mg`) — **không có tiền lệ gold**, không rõ `SBD`
  hay `SCD` generic. Cần quyết định riêng.

---

## 6. Công cụ — `scripts/annotation_qa/`

Chạy `python3 scripts/annotation_qa/kb.py build` **một lần** trước tiên (~1 phút, tạo
`kb_index.pkl`). `scd_index.py` chỉ cần khi động tới nhánh SCD.

| Script | Việc |
|---|---|
| `kb.py` | Tra ICD/RxNorm. `icd CODE`, `icdfind "tên"`, `icden CODE`, `rx CUI`, `rxfind "tên"`, `ing CUI` |
| `validate.py` | **Bắt buộc.** Schema, offset chính xác, type/assertion hợp lệ, mã tồn tại, span trùng |
| `make_packets.py` | Sinh packet review/file: toàn văn + nhãn hiện tại **kèm nhãn KB của từng mã** + gợi ý tra cứu |
| `normalize.py` | Pass chuẩn hoá D1–D4. Mặc định dry-run, `--apply` để ghi |
| `diff_report.py` | So `annotations/` vs `annotations_gold/`. `--examples`, `--perfile` |
| `consistency.py` | Kiểm chéo: cùng cụm từ nhưng khác type/mã giữa các file |
| `scd_index.py`, `scd_probe3.py` | Chỉ dùng khi xử lý nhánh SCD ở mục 5.3 |

`kb.py icdfind` chỉ khớp chuỗi, mà `ICD10.csv` dùng thuật ngữ chính thức ("U ác của…")
chứ không dùng từ dân dã ("ung thư…"). Không ra kết quả thì thử từ chuyên môn, hoặc tra
ngược qua `icden`.

---

## 7. Ba nhiệm vụ, theo thứ tự

### 7.1 Chạy pass chuẩn hoá trên 100 file đã có

```bash
python3 scripts/annotation_qa/kb.py build
python3 scripts/annotation_qa/normalize.py            # dry-run, đọc kỹ output
python3 scripts/annotation_qa/normalize.py --apply
python3 scripts/annotation_qa/validate.py             # phải sạch
```

Sau đó **sửa tay** hai việc script không tự làm được:

- **14 ca D4** mà `normalize.py` báo cáo — rà từng ca theo mục 4, cảnh giác bẫy
  "hẹp động mạch chủ".
- **D5 ở batch 3**: `mtsamples_cardio_0006_dan_y` và `mtsamples_consult_0007_xuong_dong`
  để `[]` cho thuốc dưới mục có tiêu đề; phải đổi thành `isHistorical`.

Rồi chạy `consistency.py` và xử lý các bất nhất còn lại.

### 7.2 (Tuỳ chọn) Nhánh SCD

Chỉ làm khi đã quyết theo mục 5.3. Vá khâu biệt dược trước, đừng áp `scd_changes.json`
nguyên trạng.

### 7.3 Hoàn thiện 62 file còn lại

```bash
python3 - <<'EOF'
import os
R="data/generated_medical_records/restyled"
src={f[:-5] for f in os.listdir(f"{R}/annotations")}
done={f[:-5] for f in os.listdir(f"{R}/annotations_gold")}
rest=sorted(src-done)
open("remaining.txt","w").write("\n".join(rest))
print(len(rest), "file còn lại → remaining.txt")
EOF

python3 scripts/annotation_qa/make_packets.py   # sinh packet cho mọi file
```

**Prompt sẵn dùng cho reviewer** (chia batch 10–12 file, chạy song song được):

> Bạn là chuyên gia y khoa giàu kinh nghiệm, thành thạo ICD-10, RxNorm và
> ConText/Assertion, đang hiệu đính nhãn gold cho bộ dữ liệu NER y khoa tiếng Việt.
>
> **BẮT BUỘC đọc toàn bộ `docs/gold-annotation-handoff.md` trước tiên** — đó là quy tắc
> gán nhãn đầy đủ. Tuân thủ nghiêm ngặt, không tự chế convention riêng.
>
> **Batch của bạn:** `<liệt kê stem>`
>
> Với MỖI file: đọc packet `scripts/annotation_qa/packets/<stem>.md` (có sẵn toàn văn +
> bảng nhãn hiện tại kèm nhãn KB của từng mã + gợi ý tra cứu), đọc lại toàn văn như một
> bác sĩ đọc bệnh án để nắm bối cảnh (bệnh án? bài phổ biến kiến thức? hỏi–đáp?; ai là
> bệnh nhân; mục nào là tiền sử), rồi thẩm định từng nhãn (giữ / sửa / xoá) và **bổ sung
> khái niệm bị bỏ sót**. Ghi ra
> `data/generated_medical_records/restyled/annotations_gold/<stem>.json`.
>
> Cách làm việc bắt buộc:
> - Cứ xong 3–4 file thì chạy `python3 scripts/annotation_qa/validate.py <stem>...`,
>   đừng dồn tới cuối.
> - Luôn tính offset bằng Python, **tuyệt đối không đếm tay**. Đọc kỹ cảnh báo Unicode
>   NFD ở mục 3.1. Với cụm lặp lại nhiều lần phải truyền `hint_start`.
> - Cuối cùng validator phải 0 error trên toàn batch.
>
> CHỈ ghi vào `annotations_gold/`. Không sửa `annotations/`, `text/`, hay file nào khác.
>
> Báo cáo cuối: số entity trước→sau, bảng thống kê thao tác (giữ / sửa code / sửa type /
> sửa span / sửa assertion / xoá / thêm), 5–10 ví dụ sửa đáng chú ý nhất kèm lý do y
> khoa, và **mọi điểm bạn không chắc**. Báo cáo trung thực, không tô hồng.

Sau khi xong 62 file: chạy lại `normalize.py --apply`, `validate.py`, `consistency.py`
trên toàn bộ 162 file.

---

## 8. Tiêu chí nghiệm thu

- [ ] `validate.py` sạch trên cả 162 file
- [ ] `normalize.py` dry-run không còn auto-drop nào
- [ ] `consistency.py`: mọi bất nhất type/mã còn lại đều có lý do ghi rõ
- [ ] `diff_report.py --perfile` không có file nào giảm entity bất thường
- [ ] ADR 0001 được cập nhật với bằng chứng ở mục 5.3

---

## 9. Điểm chưa chốt — cần người quyết

1. **`SCD` vs `IN`** (mục 5.3) — ảnh hưởng 7,0% entity mang mã. Đề nghị giữ `IN` +
   tham số hoá.
2. **Biệt dược có liều** (`Lipitor 40 mg`) — `SBD`, `SCD` generic, hay `IN`? Không có
   tiền lệ gold.
3. **Cặp sinh hiệu** (~200 span `TÊN_XÉT_NGHIỆM` + `KẾT_QUẢ_XÉT_NGHIỆM`) — đã theo
   quyết định "gán cả hai". Nếu gold BTC chỉ gán trị số thì đây là false positive hàng
   loạt. Rủi ro đã biết, đã chấp nhận.
4. **Span 1 ký tự** (`M` mạch, `T` nhiệt độ) trong bệnh án viết tay — đúng quy tắc nhưng
   dễ lệch WER.
5. **`docusate sodium` → `SCDC`** — gold tự mâu thuẫn, chưa rõ khi nào dùng `SCDC`.
