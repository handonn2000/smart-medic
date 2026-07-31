# Trình xem chú thích (annotation viewer)

Một trang HTML tĩnh, tự chứa, để xem văn bản y khoa cùng các nhãn dự đoán:
văn bản được tô màu theo loại khái niệm, di chuột lên nhãn để xem nhanh, bấm để
ghim toàn bộ JSON item của nhãn đó. Chọn thêm thư mục kết quả thứ hai để **so
sánh hai run cạnh nhau**.

## Cách dùng

Mở thẳng bằng trình duyệt — không cần server, không cần cài gì:

```bash
open webapp/index.html
```

Trong trang:

1. **Thư mục `.txt`** — thư mục chứa các file văn bản đầu vào.
2. **Kết quả A** — thư mục kết quả `.json`. Xem một mình là đủ.
3. **So sánh B** *(tuỳ chọn)* — thư mục kết quả thứ hai. Chọn xong màn hình tự
   chia đôi. Bấm dấu `×` trên nút để bỏ một thư mục.
4. Chọn một file ở cột trái.

Các thư mục có thể nằm **bất kỳ đâu trên máy** (không nhất thiết trong repo này),
nên A và B có thể là hai run khác nhau ở hai chỗ khác nhau. File được ghép cặp
theo tên gốc: `12.txt` ↔ `12.json`. File `.json` không có `.txt` tương ứng sẽ bị
bỏ qua; file `.txt` không có kết quả vẫn xem được (chỉ hiện văn bản thô).

Mọi thứ chạy trong trình duyệt — không có gì được tải lên bất kỳ máy chủ nào.

## Định dạng đầu vào

Mỗi file JSON là một mảng các item theo đúng contract của dự án (xem
[`README.md`](../README.md) ở gốc repo):

```json
[
  {
    "text": "bệnh trào ngược dạ dày - thực quản",
    "type": "CHẨN_ĐOÁN",
    "candidates": ["K21.0", "K21.9"],
    "assertions": [],
    "position": [106, 140]
  }
]
```

`position` là offset **ký tự** (code point) trên nội dung file `.txt`.

## Những gì trang này hiển thị

| | |
|---|---|
| Tô màu theo loại | 5 loại: `TRIỆU_CHỨNG` · `TÊN_XÉT_NGHIỆM` · `KẾT_QUẢ_XÉT_NGHIỆM` · `CHẨN_ĐOÁN` · `THUỐC` |
| Hover | tooltip: type, position, candidates, assertions |
| Click | ghim chi tiết ở khung dưới, kèm JSON thô + nút sao chép |
| Gạch ngang | nhãn có `isNegated` |
| Viền nét đứt cam | `position` **không khớp** `text` — kèm cảnh báo ở đầu tài liệu |
| Chip loại trên thanh công cụ | số lượng mỗi loại; bấm để ẩn/hiện |
| Ô tìm kiếm | lọc theo tên file **hoặc** theo nội dung nhãn bên trong file |

Vì trang này kiểm tra lại offset khi hiển thị, nó cũng dùng được như một công cụ
soát lỗi nhanh: nếu một run sinh sai `position`, nhãn đó hiện viền nét đứt và
được liệt kê trong khối cảnh báo.

## Chế độ so sánh A ↔ B

Khi đã chọn cả hai thư mục kết quả, mỗi nhãn được đối chiếu với nhãn tương ứng ở
bên kia và đánh dấu bằng **viền ngoài** (viền ngoài, nên không đè lên màu loại
khái niệm hay viền cảnh báo offset):

| Dấu hiệu | Ý nghĩa |
|---|---|
| *(không có viền)* | **giống hệt** — cùng vị trí, cùng type, cùng candidates, cùng assertions |
| viền chấm tím | **cùng vị trí, khác thuộc tính** — lệch type, mã, hoặc assertion |
| viền đứt tím | **lệch biên** — hai span chồng lấn nhau nhưng offset khác nhau |
| viền liền hồng | **chỉ có ở một bên** — bên kia không có nhãn nào chồng lấn |

Cách ghép cặp: ưu tiên khớp offset chính xác trước, sau đó mới đến span chồng lấn
bất kỳ — nên một nhãn bị dịch biên vẫn tìm được "người tương ứng" thay vì bị đếm
thành *thêm mới + mất đi*.

Hỗ trợ khi so sánh:

- **Thanh tổng kết** ngay dưới toolbar: số nhãn giống hệt / khác thuộc tính /
  lệch biên / chỉ có ở A / chỉ có ở B.
- **Cột trái** hiện `sốA/sốB` và huy hiệu số khác biệt của từng file; ô
  **"Chỉ file có khác biệt"** lọc ra đúng những file cần xem. File giống hệt hiện `=`.
- **Nút "Chỉ khác biệt"** (phím `D`) làm mờ các nhãn giống hệt để chỗ khác nhau nổi lên.
- **Di chuột** lên một nhãn sẽ tô sáng nhãn tương ứng ở cột kia.
- **Khung chi tiết** hiển thị A và B thành hai cột, tô nền những dòng thực sự
  khác nhau, kèm JSON thô của cả hai bên.
- Hai cột **cuộn đồng bộ**.

Phím tắt: `/` tìm kiếm · `↑`/`↓` chuyển file · `D` chỉ khác biệt · `Esc` bỏ ghim.

## Ghi chú kỹ thuật

- Thư mục được đọc qua `<input type="file" webkitdirectory>` (Chrome, Edge,
  Safari, Firefox).
- Offset trong JSON là code point (ngữ nghĩa Python); chỉ số chuỗi JS là UTF-16.
  Hai cái trùng nhau trừ khi văn bản có ký tự ngoài BMP — khi đó trang tự dựng
  bảng ánh xạ. Dữ liệu `data/test` hiện tại không có ký tự nào như vậy.
- Nhãn chồng lấn nhau không thể tô màu lồng nhau; nhãn bị bỏ qua sẽ được liệt kê
  trong khối cảnh báo chứ không biến mất im lặng.
- Dưới 1100px bề ngang, hai cột so sánh xếp chồng lên nhau (trên/dưới) thay vì
  cạnh nhau, để mỗi cột vẫn đủ rộng mà đọc.
- Huy hiệu khác biệt ở cột trái chỉ cần đọc JSON nên tính được cho toàn bộ file
  ngay khi nạp; phần đối chiếu chi tiết chỉ chạy khi mở từng file.
