# ADR 0005 — Đóng gói `output.zip` bằng `zipfile`, không bằng lệnh `zip`

- **Trạng thái:** ĐÃ QUYẾT
- **Ngày:** 2026-07-30
- **Ảnh hưởng:** `scripts/submit/package_submission.py` (P0) · diễn tập tái lập (P7)

## Bối cảnh

`validate/README.md` và `runs/README.md` ghi lệnh đóng gói:

```bash
cd data && zip -r ../output.zip output -x '*/.*'
```

Hai vấn đề, cả hai chỉ lộ ra muộn:

1. **`data/output/` có 4 file phụ** — `run_manifest.json`, `explain.json`,
   `metric_curated_v3.json`, `metric_expected.json`. `-x '*/.*'` chỉ loại file bắt đầu bằng
   dấu chấm, nên cả bốn **sẽ vào archive**. `load_dir()` của ta bỏ qua chúng theo hình dạng
   (record là một JSON *list*); scorer của BTC có thể không.
2. **Lệnh `zip` không tất định.** Nó ghi mtime của từng file và đi theo thứ tự filesystem.
   Hai lần chạy trên **cùng** dự đoán cho ra hai archive **khác bytes**. Nhưng
   `runs/README.md` yêu cầu diễn tập tái lập kết thúc bằng:

   ```bash
   cmp /tmp/out.zip runs/<ts>_<sha>/output.zip && echo "✓ tái lập được"
   ```

   Phép so đó **không thể đúng** nếu bộ ghi archive không tất định. Nó sẽ luôn báo khác, và
   thứ duy nhất nó dạy ta là bỏ qua nó — đúng lúc nó là hàng rào cuối chống bị loại.

## Quyết định

`package_submission.py` **dàn (stage)** rồi **ghi bằng `zipfile`**:

1. Đọc record `N.json` từ `--pred`, ghi lại qua `validate.emit_json` vào
   `runs/<ts>_<sha>/output/` — thư mục sạch, chỉ có record, và đi qua cổng cứng thêm một lần.
2. Ghi archive bằng `zipfile.ZipFile`, member theo **thứ tự số** (`1, 2, … 100`, không phải
   `1, 10, 100`), timestamp cố định `1980-01-01`, quyền `0644`.
3. **Cấu trúc archive không đổi:** `output/` nằm *trong* archive, đúng như tài liệu.
4. Đọc lại 100 member **từ trong archive** và chạy 7 phép kiểm; fail là exit ≠ 0 và
   `output.zip` ở gốc repo **không** được ghi.

Đã đo: hai lần chạy độc lập cho archive **byte-identical** (`cmp` sạch).

## Hệ quả

1. Diễn tập tái lập ở P7 trở thành một phép so **có nghĩa**. Nếu `cmp` báo khác, đó là dự
   đoán khác chứ không phải nhiễu đóng gói.
2. `sha256(output.zip)` trở thành **danh tính của bài nộp**, ghi được vào manifest và so
   được giữa các lần chạy.
3. Lệnh `zip` trong tài liệu **không còn là đường chính thức**. Ai chạy nó bằng tay sẽ nộp 4
   file phụ. Đây là lý do `make submit` gọi script, không gọi `zip`.
4. Không cần `zip` cài trên máy/container — bớt một phụ thuộc hệ thống ở vòng chấm.

## Rủi ro cần canh

Timestamp cố định `1980-01-01` là giá trị nhỏ nhất mà định dạng ZIP biểu diễn được. Nếu
công cụ giải nén của BTC từ chối nó (chưa gặp; `unzip -l` đọc bình thường), đổi sang một mốc
cố định khác — **giữ nguyên tính cố định**, đừng quay về dùng thời gian thực.
