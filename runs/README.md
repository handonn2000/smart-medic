# `runs/` — bản ghi bất biến, một thư mục một lần chạy

**Không bao giờ ghi đè.** Thư mục này biến câu hỏi *"bài nộp này từ commit nào"* từ khảo
cổ học thành một lệnh `cat`.

Vòng chấm source code là rủi ro **bị loại** — rủi ro duy nhất trong dự án không mua lại
được bằng điểm. `runs/` là thứ làm nó trả lời được.

```
runs/
└── 2026-07-30T14-02_a1b2c3d/
    ├── manifest.json      10 trường, xem dưới
    ├── output/            100 file JSON đúng như đã nộp
    ├── output.zip         archive đúng như đã nộp
    └── score.json         cả 3 cách đọc × 3 chế độ căn chỉnh
```

Tên thư mục: `<ISO8601>_<git-sha7>`.

## `manifest.json` — 10 trường bắt buộc

| # | Trường | Ghi chú |
|---|---|---|
| 1 | `git_sha` + `git_dirty: bool` | **dirty ⇒ KHÔNG được nộp** |
| 2 | `metric_config_hash` | `MetricConfig().hash()`, 12 ký tự — danh tính của phép đo |
| 3 | `models[]` | mỗi phần tử `{id, revision_sha, params}` — **revision SHA, không phải tag** |
| 4 | `params_total` | kèm kết quả `assert params_total < 9e9` |
| 5 | `seed` | mọi nguồn ngẫu nhiên: python, numpy, torch, tokenizer |
| 6 | `lib_versions` | `pip freeze` đầy đủ, kèm hash bánh xe |
| 7 | `input_manifest_sha256` | sha256 của `tests/data_test_manifest.json` |
| 8 | `kb_versions` | ICD10.csv · RXNCONSO · RXNREL · RXNCUI · RXNATOMARCHIVE (RxNorm phát hành **hàng tháng**) |
| 9 | `config_files_sha256` | mọi YAML trong `configs/` và `resources/` |
| 10 | `probe_variant` | probe nào, hoặc `full` |

Kèm theo mỗi lần **nộp**: câu hỏi mà lần nộp đó trả lời, và delta kỳ vọng — ghi **trước
khi** nộp, không phải sau.

## Thứ không ghim được

**Tính xác định theo batch.** Temperature 0 **không** cho tính xác định — thiếu bất biến
theo batch. Nếu diễn tập không cho kết quả bit-identical: cố định `batch_size=1`; còn lệch
thì đóng gói cache đầu ra kèm theo.

## Diễn tập vòng chấm — làm trước ban tổ chức

Container mới, sạch → `pip install --require-hashes` từ file đã ghim → khôi phục weights
theo revision SHA → chạy → **`diff` với `output.zip` đã nộp**. Đây đúng là việc ban tổ
chức sẽ làm.

Lịch: **hai lần**. Lần đầu để tìm lỗi cài đặt khi còn thời gian sửa; lần hai để xác nhận.
Diễn tập *sau* khi nộp là vô ích.

## Gitignore

Nội dung `runs/` sinh lại được từ code + config đã ghim ⇒ gitignore, giữ `.gitkeep`.
Nhưng **`manifest.json` của lần nộp cuối phải được commit** — nó là bằng chứng tái lập.
