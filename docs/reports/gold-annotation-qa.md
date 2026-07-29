# Gold annotation QA ledger

- Ngày thực hiện: 2026-07-29
- Corpus: `data/generated_medical_records/restyled/`
- Convention RxNorm vận hành: ingredient-level (`IN`/`PIN`/`MIN`), xem ADR 0001

## Baseline và checkpoint

- Text/source annotations: 162/162, stem khớp 1:1.
- Gold trước chuẩn hoá: 100 file, 4.715 entity.
- Checkpoint trước mọi ghi đè:
  `/private/tmp/smart-medic-gold-baseline.cSEsq3/baseline.tar.gz`
- SHA-256 checkpoint:
  `8e64d6b503864aff5a43681cc1debb90badf9ec86dc1565e593497b1b2fb4c62`

## Pass chuẩn hoá 100 file

### D1–D3

- D1: xoá 17 span lối sống sau khi đọc lại đủ 17 ngữ cảnh; không ca nào mô tả nghiện
  hoặc lệ thuộc bệnh lý.
- D2: xoá 10 span lớp thuốc chung; không ca nào nêu hoạt chất hay biệt dược cụ thể.
- D3: không có auto-drop trong snapshot này. `xét nghiệm máu thường quy` đã được loại
  khỏi danh sách auto-drop vì guideline giữ cụm xét nghiệm có bổ ngữ.

### D4 — ICD theo danh mục BYT

Đã rà 14 occurrence: đổi 9, giữ 5.

| Mention | Thay đổi | Số occurrence | Disposition |
|---|---|---:|---|
| `suy tim` | `I50.9 → I50` | 3 | Không có subtype trong văn bản |
| `bệnh trào ngược dạ dày thực quản` | `K21.9 → K21` | 2 | Không có chi tiết viêm thực quản |
| `vảy nến` | `L40.9 → L40` | 1 | Không có subtype |
| `xuất huyết tiêu hóa` | `K92.2 → K32` | 1 | `ICD10.csv` BYT là thẩm quyền |
| `tắc mạch phổi` | `I26.9 → I26` | 1 | Mention bệnh chung, bị phủ định |
| `sỏi mật` | `K80.2 → K80` | 1 | Không xác định vị trí/biến chứng |
| `hẹp động mạch chủ` | giữ `I35.0` | 4 | Ngữ cảnh hẹp van mắc phải; không phải dị tật `Q25.3` |
| `chống đông máu` | giữ `Z92.1` | 1 | Dùng chống đông dài ngày; không phải ADR `Y44.2` |

### D5 — thuốc dưới tiêu đề danh sách

- `mtsamples_cardio_0006_dan_y`: thêm `isHistorical` cho 6 thuốc dưới “Thuốc đang dùng”;
  `lisinopril` ở kế hoạch giữ `[]`.
- `mtsamples_consult_0007_xuong_dong`: thêm `isHistorical` cho 5 thuốc dưới “Thuốc”;
  `ASPIRIN` dưới “Dị ứng” giữ `[]`.

### Gate sau chuẩn hoá

- Gold: 100 file, 4.688 entity.
- `validate.py`: 0 error, 0 warning.
- `normalize.py` dry-run: 0 auto-drop.
- Residual D4: 5 occurrence có disposition ở bảng trên.

## Consistency snapshot sau chuẩn hoá

- 36 surface form khác type.
- 27 surface form khác candidates.
- 2 surface form có candidates ở nơi này nhưng rỗng ở nơi khác.
- 166 surface form khác assertions. Assertion phụ thuộc phạm vi phủ định, tiền sử và gia
  đình nên không được auto-unify; chỉ các occurrence sai ngữ cảnh mới được sửa.

Đã sửa các outlier có convention được handoff hoặc ngữ cảnh bản sao xác định rõ:

- `viêm phổi`: 2 occurrence `J18.9 → J18`.
- `ung thư bàng quang`: 1 occurrence `C67.9 → C67`.
- `bệnh thận mạn`: 1 occurrence `N18.9 → N18`.
- `hen suyễn`: 3 occurrence `J45.9 → J45`.
- `rối loạn co giật` bị phủ định: `G40.9 → R56` vì văn bản không chẩn đoán động kinh.
- `bổ sung tuyến giáp`: điền RxCUI ingredient `10572` theo bốn occurrence tương đương.
- `nhiễm trùng`: điền mã tổng quát `B99` theo ba occurrence tương đương.

Tám file liên quan đã validate lại: 0 error, 0 warning.

Audit consistency trên 142 file đầu tiên phát hiện và đã sửa thêm 10 occurrence có ngữ
cảnh xác định rõ:

- `xuất huyết tiêu hóa trên/cao`: `K92.2 → K32.0`; `hen`: `J45.9 → J45`.
- Điền mã cho `oxy → 7806`, `bệnh tim → I51.9`, và hai mention dị vật mô mềm
  `→ M79.5`.
- `nhiễm trùng`: `A49.9 → B99` vì không có bằng chứng căn nguyên vi khuẩn.
- `lạm dụng chất kích thích`: `F19.1 → F15.10`; `liệt ruột cơ năng`:
  `K56.7 → K56.0`; `kali`: `8591 → 8588` vì không có cue chloride.

Tám file chứa 10 occurrence này đã validate lại: 0 error, 0 warning.

Sáu nhóm bất đồng đã được adjudicate:

- Chuẩn hoá 3 mention `rối loạn lipid máu` về `E78.5` và 2 mention `lạm dụng rượu`
  về `F10.1` vì văn bản không nêu subtype/biến chứng.
- Chuẩn hoá 6 mention `hội chứng PEHO` về `G31.8`; Orphanet ánh xạ trực tiếp PEHO
  syndrome (ORPHA:2836) sang mã này.
- Chuẩn hoá `viêm phổi do lupus` từ `J18 → M32.8` và hai mention thoát vị từ
  `K40.2 → K46.9` vì văn bản không có cue “bẹn”.
- Giữ khác biệt theo ngữ cảnh cho `ngã`: `W19` là biến cố ngã cấp; `R29.6` chỉ dùng
  cho “lịch sử/dễ ngã”.

Chín file chứa các adjudication đã validate lại: 0 error, 0 warning.

Ba file giảm entity đã được kiểm tra trực tiếp với silver:

- `mtsamples_cardio_0023_dan_y`: 30 → 26. Chênh lệch do thu gọn hai span triệu chứng,
  xoá ba mention thủ thuật `IVC filter`, một span masked và một lối sống; đồng thời thêm
  `sẩy thai`. Mức giảm hợp lệ.
- `mtsamples_consult_0031_hoi_dap`: 14 → 12. Xoá hai từ xét nghiệm chung chung và một
  span masked, thêm `mệt mỏi`. Mức giảm hợp lệ.
- `mtsamples_hemato_0011_dan_y`: 21 → 20. Xoá thủ thuật `Hóa trị liệu` và span masked;
  mở rộng đúng hai span CT, hai span thuốc và thêm `Vicodin`. Mức giảm hợp lệ.

## Review 62 file còn lại

Manifest tạm đã được xác nhận có đúng 62 stem, không trùng hoặc thiếu, rồi được xoá
sau khi hoàn tất phân batch để tránh giữ artefact điều phối một lần.

| Batch | Primary | Cross-review | Trạng thái |
|---|---|---|---|
| B1 | R1 | R3 | READY_QA — 316→514, validate 0/0 |
| B2 | R2 | R3 | QA_DONE — 298→393, cross-review 0/0 |
| B3 | R3 | R1 | QA_DONE — 309→436, cross-review 0/0 |
| B4 | R3 | R2 | READY_QA — 308→448, validate 0/0 |
| B5 | R1 | R2 | READY_QA — 308→453, validate 0/0 |
| B6 | R2 | R1 | READY_QA — 309→503, validate 0/0 |

Không chạy `normalize.py --apply` hoặc integration toàn corpus khi bất kỳ batch nào đang
ở trạng thái writer-locked.

### Hàng đợi adjudication cho cross-review

- B1: `podia_0001` tăng 28→87; Pneumovax để candidates rỗng; dòng tiểu cầu/monos/eos
  khuyết dữ liệu; `Levsinex → 153970`; `C70.0` cho u màng não ác và `Z73.6` cho khuyết
  tật nặng.
- B2: tethered cord `Q06.8` so với `G95.8`; “Ngực dạng tuyến sợi” để mã rỗng; FFP giữ
  type THUỐC nhưng mã rỗng; `suy chức năng gan` trong cảnh báo điều kiện vẫn được gán.
- B3: ba kết quả hình ảnh định tính âm tính; “Bệnh phế cầu khuẩn” `A49.1`; insulin chung
  kế thừa hai ingredient của Humulin 70/30; assertion lịch sử dưới tiêu đề điều trị;
  ranh giới span Keflex gồm chỉ dẫn dự phòng/thời hạn.
- B4: kết quả định tính (`khá hơn`, `cải thiện`, `ổn định`); “không dung nạp” là khái
  niệm dương tính; `nhiễm tr → A49.9`; `ung thư biểu mô → C34.9`; chẩn đoán phân biệt
  nhi khoa có mã tổng quát và “bất thường mạch máu” để rỗng.
- B5: `sốt nấm → B49` do cụm dịch mơ hồ; AIDS bị phủ định `→ B24` trong khi HIV xác
  nhận `→ Z21`; `Phì đại thất trái → I51.7`; NyQuil suy ra ba ingredient; boundary đa
  dòng “Tiền sản giật sau sinh …”; span song ngữ “Huyết áp blood pressure”.
- B6: insulin generic để mã rỗng; hội chứng chèn ép ổ cối-xương đùi để mã rỗng;
  glioma/GBM suy ra `C71.2` từ vị trí; tiêu cơ vân `M62.8`; bỏ cụm “tưới máu song phương
  thứ phát” vì không đủ nghĩa.
