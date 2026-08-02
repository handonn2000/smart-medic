# gold_real — gold trên văn bản THẬT

3 file lấy nguyên văn từ `data/test/`, gán nhãn tay theo guideline v6 §3 + PRD §3.

**Tách khỏi `data/probe/gold/` có chủ đích.** `gold/` là 20 bệnh án tổng hợp do
chính chúng ta viết ra rồi tự gán nhãn — chỉ dùng làm regression guard, không
dùng để công bố số đo. `gold_real/` là tín hiệu không thiên lệch duy nhất trong
hai tập. **Không gộp hai tập khi báo cáo metric.**

| File | Thể loại | Phủ điểm yếu PRD §7 | Span |
|---|---|---|---|
| `100.txt` | hỏi–đáp sản khoa | **§7.1 nhánh (b)** — thuốc bị che, tên lộ ở câu sau ⇒ co-reference khôi phục `1191` | 13 |
| `65.txt` | hỏi–đáp da liễu | **§7.1 nhánh (c)** — thuốc bị che, tên KHÔNG bao giờ lộ ⇒ `candidates` phải rỗng | 23 |
| `1.txt` | blog giáo dục | **§7.2** khoảng cách ngữ nghĩa ICD + **§7.3** ngữ cảnh giả định ⇒ assertion rỗng | 51 |

87 span. **Cả 87 span có `assertions: []`** — không phải bỏ sót mà là kết luận:
cả ba file đều không có mệnh đề lâm sàng trực tiếp về một bệnh nhân cụ thể.

## Bẫy — cụm PHẢI không có span nào phủ

Đây là phần đo dương tính giả. Script gán nhãn có assert riêng cho từng cụm.

| File | Cụm | Vì sao phải trống |
|---|---|---|
| `1.txt` | `Glucose-6-Phosphate Dehydrogenase` | giải thích viết tắt của **tên bệnh**, không phải THUỐC |
| `1.txt` | `Men G6PD` (×2) | tên enzyme, không thuộc 5 loại |
| `1.txt` | `từ bố và/hoặc mẹ` | cơ chế di truyền — **không phải** `isFamily` (PRD §7.3) |
| `1.txt` | `tổn thương thần kinh`, `ổn định` | cụm chung, không có khái niệm ICD tương ứng |
| `1.txt` | `đậu tằm` (×3), `long não` (×2) | thực phẩm / hoá chất, không phải THUỐC |
| `65.txt` | `thương tổn` (×2) | danh từ chung |
| `65.txt` | `Corticosteroid`, `corticoid mức độ mạnh` | lớp thuốc chung — guideline §3.2 |
| `65.txt` | `vùng rụng tóc` (×2) | chỉ vị trí giải phẫu, không phải chẩn đoán |

## Bẫy Unicode — có thật trong `100.txt`

`100.txt` **trộn NFC và NFD ngay bên trong một cụm từ**. Hệ quả đo được: cùng
chuỗi `"tiền sản giật"` mà span `[157,173]` dài 16 ký tự còn `[584,597]` dài 13.

⇒ Không được `txt.index("chuỗi gõ tay")`. Phải chuẩn hoá theo cluster (ký tự nền
+ dấu tổ hợp) rồi ánh xạ ngược về offset gốc; `text` luôn cắt từ chính `txt`.

## Điểm cần phân xử lại nếu có reviewer thứ hai

1. `rụng tóc toàn bộ` → `L63.0`, `rụng tóc toàn thể` → `L63.1` — chọn theo **nghĩa
   y khoa** (totalis ở đầu / universalis toàn thân), NGƯỢC với khớp mặt chữ của
   D4 (nhãn `L63.1` là "Rụng tóc toàn bộ"). D4 tự cảnh báo khớp chữ đôi khi sai
   y khoa nên tôi ưu tiên nghĩa.
2. `Kháng sinh nhóm ***********` (`1.txt`) — mask che **tên nhóm thuốc**, mà
   guideline loại lớp thuốc chung. Tôi vẫn gán THUỐC theo PRD §7.1(a) "token bị
   che là entity THUỐC riêng", `candidates` rỗng.
3. `thiếu máu do tan huyết` / `thiếu máu tan huyết` → `D58.9` (di truyền) thay vì
   `D59` (mắc phải), vì toàn văn nói về G6PD.
4. `xét nghiệm thiếu men G6PD` gán TÊN_XÉT_NGHIỆM trọn cụm, không tách tên bệnh
   ra thành CHẨN_ĐOÁN lồng bên trong.
