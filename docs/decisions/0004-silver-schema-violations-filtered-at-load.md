# ADR 0004 — 165 vi phạm lược đồ trong corpus bạc: **xoá cờ, giữ span, lúc nạp**

- **Trạng thái:** ĐÃ QUYẾT
- **Ngày:** 2026-07-30
- **Ảnh hưởng:** `io/corpus.py` (P0) · mọi phase huấn luyện trên bạc (P1, P3, P4)

## Bối cảnh

`tests/test_offsets.py::test_silver_offsets` FAIL với **165 vi phạm**: 165 entity
`TÊN_XÉT_NGHIỆM` / `KẾT_QUẢ_XÉT_NGHIỆM` trong 543 file bạc đang mang `assertions`, điều
đề bài cấm. Đây là **lỗi thật trong dữ liệu**, không phải test hỏng — `annotations_gold/`
(162 file) sạch hoàn toàn, 0 lỗi.

Rò cờ `isNegated` sang hai loại xét nghiệm là hạng mục **11,59 điểm** trên bản đồ đòn bẩy
(70,00 → 58,41). Nếu train trên bạc mà không lọc, model học đúng cái lỗi đó.

Ba lựa chọn:

| | Cách | Chi phí | Hệ quả |
|---|---|---|---|
| A | Regenerate 543 file | ~nửa ngày | **Mọi số liệu đã đo trên corpus này không tái lập được** |
| B | Bỏ cả 165 entity lúc nạp | ~5 dòng | Mất 165 span hợp lệ khỏi tín hiệu recall |
| C | **Xoá `assertions`, giữ span, lúc nạp** | ~5 dòng | Giữ span; dạy đúng luật lược đồ |

## Quyết định

**C.** `io.corpus.load_silver()` xoá `assertions` của entity thuộc hai loại xét nghiệm ngay
khi nạp, và **đếm** số lần đã xoá vào `LoadReport.assertions_cleared`.

Lý do chọn C thay vì B: **cái vi phạm lược đồ là cái cờ, không phải cái span.** Vị trí và
loại của 165 entity đó đều đúng; chỉ trường `assertions` sai. Bỏ cả entity là ném đi 165 span
huấn luyện hợp lệ trong khi recall span là đòn bẩy lớn nhất của dự án (bỏ 30% entity = −20,72
điểm). Xoá cờ giữ được span **và** dạy model đúng điều lược đồ nói: hai loại xét nghiệm
không bao giờ mang assertion.

Lý do không chọn A: `runs/leverage_map.json`, mọi bảng trong `docs/reports/*.html` và mọi
ngưỡng trong `configs/pipeline.yaml` đều đo trên corpus hiện tại. Sinh lại corpus làm chúng
trở thành số không kiểm chứng được — đắt hơn nhiều so với giá trị của việc "dữ liệu sạch từ
gốc".

## Hệ quả

1. **KHÔNG sửa `test_silver_offsets`.** Nó phải tiếp tục FAIL với đúng 165 vi phạm. Nó là
   thước đo trạng thái *file trên đĩa*; `load_silver()` là thước đo trạng thái *dữ liệu vào
   model*. Hai thứ khác nhau, và cả hai đều cần.
2. **Số 165 được ghim thành test.** `tests/test_document.py::test_silver_schema_violations_are_filtered_at_load`
   assert đúng 165. Nếu con số đổi, generator đã trôi — dừng và xem, đừng cập nhật hằng số.
3. `load_gold()` chạy qua **cùng** bộ lọc. Trên gold nó phải là no-op; nếu
   `assertions_cleared > 0` trên gold thì thước đo đã hỏng và mọi điểm đo được đều đáng ngờ.
4. Bộ lọc cũng **bỏ** entity có `raw[start:end] != text`. Hôm nay là 0 entity. Đây là bảo
   hiểm chống generator trôi offset, không phải sửa lỗi đang có.
5. `validate/schema.py` ép **cùng** ràng buộc ở tầng ghi file. Hai lớp, hai chỗ: một chỗ lọc
   dữ liệu *vào*, một chỗ lọc dự đoán *ra*. Model không được tin ở cả hai đầu.

## Cái không quyết ở đây

Hai loại xét nghiệm có nên mang cờ `isHistorical` hay không **về mặt y khoa** — không liên
quan. Đề bài cấm, và đề bài là thứ được chấm.
