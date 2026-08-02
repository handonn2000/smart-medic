# gold_real — gold trên văn bản THẬT

9 file lấy nguyên văn từ `data/test/` (bản sao kiểm bằng sha256), gán nhãn tay
theo guideline v6 §3 + PRD §3. **333 span.**

**Tách khỏi `data/probe/gold/` có chủ đích.** `gold/` là 20 bệnh án tổng hợp do
chính chúng ta viết ra rồi tự gán nhãn — chỉ dùng làm regression guard, không
dùng để công bố số đo. `gold_real/` là tín hiệu không thiên lệch duy nhất trong
hai tập. **Không gộp hai tập khi báo cáo metric.**

Mọi mã ICD/RxNorm đều tra từ KB đã dựng (`kb.query.search_lexical`, rerank bật),
không lấy từ trí nhớ. Validator kiểm 333/333 mã tồn tại và `is_active=1`.

## Thành phần

| File | Thể loại | Vì sao có mặt | Span | Assert |
|---|---|---|---|---|
| `1.txt` | blog giáo dục | §7.2 khoảng cách ngữ nghĩa ICD + §7.3 ngữ cảnh giả định | 51 | 0 |
| `7.txt` | hỏi–đáp sản/tiêu hoá | biệt dược **không có** trong RxNorm vs hoạt chất **có** | 33 | 2 |
| `18.txt` | tổng hợp cận lâm sàng | dày TÊN/KẾT_QUẢ_XN; danh sách phủ định 6 triệu chứng | 58 | 8 |
| `24.txt` | bệnh án truyền nhiễm | **ca `isFamily` duy nhất** của corpus; dày xét nghiệm | 58 | 6 |
| `30.txt` | bệnh án + hỏi–đáp | phủ định lan qua "hoặc"; D5 đúng mặt chữ | 26 | 3 |
| `45.txt` | bệnh án thần kinh | mục "Tiền sử bệnh" ⇒ `isHistorical` dày nhất | 30 | 11 |
| `53.txt` | bệnh án nội tiết | 4 thuốc "đã hết thuốc"/"đã ngừng" ⇒ `isHistorical` | 41 | 5 |
| `65.txt` | hỏi–đáp da liễu | §7.1(c) thuốc bị che **không bao giờ lộ** ⇒ `candidates` rỗng | 23 | 0 |
| `100.txt` | hỏi–đáp sản khoa | §7.1(b) thuốc bị che, lộ tên ở câu sau ⇒ co-reference | 13 | 0 |

Phân bố nhãn: CHẨN_ĐOÁN 74 · TRIỆU_CHỨNG 94 · THUỐC 74 · TÊN_XN 58 · KẾT_QUẢ_XN 33.
Assertion: `isHistorical` 23 · `isNegated` 18 · `isFamily` 1 —
tổ hợp `isNegated+isHistorical` ×6, `isNegated+isFamily` ×1.

⚠️ **`isFamily` chỉ có 1 span trong toàn corpus thật.** Không đủ để đo. Đã quét
cả 100 file: chỉ `24.txt` có mệnh đề tiền sử gia đình gắn được vào một khái niệm
cụ thể (`26.txt` là danh sách yếu tố nguy cơ giáo dục, `58.txt`/`90.txt` không có
khái niệm để gắn). Muốn đo `isFamily` thì phải dùng `gold/` — và biết rằng con số
đó thiên lệch.

## Bẫy — cụm PHẢI không có span nào phủ

Phần đo dương tính giả. Script gán nhãn assert riêng từng cụm; build fail nếu
có span chạm vào.

| File | Cụm | Vì sao phải trống |
|---|---|---|
| `1.txt` | `Glucose-6-Phosphate Dehydrogenase` | giải thích viết tắt của **tên bệnh**, không phải THUỐC |
| `1.txt` | `Men G6PD` ×2 | tên enzyme, không thuộc 5 loại |
| `1.txt` | `từ bố và/hoặc mẹ` | cơ chế di truyền — **không phải** `isFamily` (PRD §7.3) |
| `1.txt` | `tổn thương thần kinh`, `ổn định` | cụm chung, không có khái niệm ICD tương ứng |
| `1.txt` | `đậu tằm` ×3, `long não` ×2 | thực phẩm / hoá chất |
| `7.txt` | `tinh bột nghệ`, `Yakult` | thực phẩm chức năng |
| `18.txt` | `ổn định mảng xơ vữa`, `tổn thương nhiều nhánh` | ★ cùng chữ với bẫy `1.txt`, khác ngữ cảnh |
| `18.txt` | `Đặt stent`, `Nong bóng` | thủ thuật — không thuộc 5 loại |
| `24.txt` | `Trong đơn vị có 3 người mang virus viêm gan B` | ★ **đồng đội, không phải người nhà** ⇒ không `isFamily` |
| `30.txt` | `Tổ thương mô bệnh học`, `Quảng cáo quảng cáo` | rác OCR/splice |
| `45.txt` | `Hệ thống dẫn lưu`, `dẫn lưu shunt` | thiết bị/thủ thuật |
| `53.txt` | `không rõ thuốc gì`, `bị ngã gần đây` | không định danh được thuốc; sự kiện |
| `65.txt` | `thương tổn` ×2, `vùng rụng tóc` ×2 | danh từ chung / vị trí giải phẫu |
| `65.txt` | `Corticosteroid`, `corticoid mức độ mạnh` | lớp thuốc chung — guideline §3.2 |

★ Hai cặp đối chứng đắt nhất: `tổn thương`/`ổn định` là **bẫy** trong `1.txt`+`18.txt`
nhưng là **triệu chứng thật** trong `7.txt` ("tổn thương vùng âm hộ", "tổn thương
dạng bóng nước"); và "gia đình" trong `24.txt` là `isFamily` còn "đơn vị" ngay dòng
dưới thì không. Cả hai không giải được bằng từ điển.

## Bẫy Unicode — có thật trong `100.txt`

`100.txt` **trộn NFC và NFD ngay bên trong một cụm từ**. Hệ quả đo được: cùng
chuỗi `"tiền sản giật"` mà span `[157,173]` dài 16 ký tự còn `[584,597]` dài 13.

⇒ Không được `txt.index("chuỗi gõ tay")`, và **thử cả NFC lẫn NFD cũng không đủ**.
Phải chuẩn hoá theo cluster (ký tự nền + dấu tổ hợp) rồi ánh xạ ngược về offset
gốc; `text` luôn cắt từ chính `txt`. Guideline v6 §3.1 mới dừng ở mức "thử cả
hai dạng" — nên sửa.

## Điểm cần phân xử lại nếu có reviewer thứ hai

1. `rụng tóc toàn bộ`→`L63.0`, `rụng tóc toàn thể`→`L63.1` (`65.txt`) — theo
   **nghĩa y khoa** (totalis / universalis), NGƯỢC với khớp mặt chữ của D4.
2. Mask che **tên nhóm thuốc** (`Kháng sinh nhóm ***`, `1.txt`) vẫn gán THUỐC
   theo PRD §7.1(a), dù guideline loại lớp thuốc chung.
3. `thiếu máu do tan huyết`→`D58.9` (di truyền) thay vì `D59` (mắc phải), theo
   ngữ cảnh G6PD của `1.txt`.
4. `viêm gan B, C` (`24.txt`) — chỉ gán được `viêm gan B`; chữ `C` là tỉnh lược
   trong liệt kê, không tách thành span độc lập có nghĩa.
5. `tăng nhãn áp` (`45.txt`) dùng `Q15.0` cho **cả hai** lần nhắc, coi là cùng
   một bệnh bẩm sinh của bệnh nhân, dù lần thứ hai không nói "sơ sinh".
6. `torsemide` ở "đề nghị ngừng sử dụng" (`53.txt`) để `[]` vì mới là **đề nghị**;
   4 thuốc "đã hết thuốc"/"đã ngừng" thì `isHistorical`.
