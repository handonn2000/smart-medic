# L6 · `validate/` — cổng cứng

**Không qua thì KHÔNG ghi file.** Layer này không sinh điểm; nó ngăn việc *mất* điểm đã có.

Hạng mục rẻ nhất cả dự án nằm ở đây: ràng buộc lược đồ **11,59 điểm với ~10 dòng code**.
Rò rỉ `isNegated` sang 2 loại xét nghiệm làm 70,00 → 58,41. Corpus bạc có **165 vi phạm
đúng chỗ này** — nếu học từ silver mà không lọc, model sẽ học cả lỗi.

## Bảy kiểm tra, dung sai 0

| # | Kiểm | Chi phí nếu bỏ |
|---|---|---|
| 1 | `assert raw[start:end] == text` — chuỗi **GỐC**, byte-exact | toàn bộ 70,00, im lặng |
| 2 | `type` ∈ 5 nhãn | entity bị loại |
| 3 | `assertions` ⊆ 3 nhãn **và RỖNG** với `TÊN_XÉT_NGHIỆM` / `KẾT_QUẢ_XÉT_NGHIỆM` | **11,59** (10% nhiễu = 1,30) |
| 4 | `candidates` rỗng trừ `CHẨN_ĐOÁN` / `THUỐC` | 0,00 dưới `official`, 2,36 dưới `plain` ⇒ vẫn chặn |
| 5 | mọi mã tồn tại trong KB đóng gói kèm | mã không tra được = mã sai |
| 6 | 0 span lồng nhau | hợp lệ: 0/7.435 gold span lồng nhau |
| 7 | **không** import HTTP client của nhà cung cấp LLM | rủi ro **bị loại** (ADR 0003) |

## Bất biến

- Ép ở **tầng tuần tự hoá**, không bao giờ tin model tự nhớ. Đây là điểm khác biệt giữa
  "ràng buộc" và "kỳ vọng".
- Kiểm tra #1 so trên `Document.raw`, không phải trên `.normalized`. 41/162 gold và
  20/100 test không ở NFC.

## Đóng gói `output.zip`

Đúng **100** file `1.json` … `100.json`, không lỗ, không file phụ.

- Mỗi file là JSON **list**. List rỗng hợp lệ; file thiếu thì không.
- `json.dump(..., ensure_ascii=False)`, UTF-8, **không BOM**, `\n` cuối file.
- Thư mục `output/` **nằm trong** archive:
  `cd data && zip -r ../output.zip output -x '*/.*'`
- **Loại** `run_manifest.json`, `metric_internal.json`, `.DS_Store`, `__pycache__` —
  `load_dir()` của ta bỏ qua sidecar theo hình dạng, scorer của ban tổ chức có thể không.
- `unzip -l output.zip` và **dán nguyên output** vào báo cáo. Không mô tả bằng lời.

## File

| File | Trạng thái | Phase |
|---|---|---|
| `schema.py` — 7 kiểm tra lược đồ | ✅ | P0 |
| `offsets.py` — assert byte-exact | ✅ | P0 |
| `emit_json.py` — tuần tự hoá + ràng buộc ở đúng chỗ này | ✅ | P0 |

Bộ đóng gói nằm ở [`scripts/submit/`](../../../scripts) vì nó là build-time, không phải
đường suy luận.

## Nghiệm thu

- 0 entity xét nghiệm mang assertion; 0 entity không mã có candidates — **tuyệt đối 0**.
- NFC/NFD round-trip dung sai 0.
- `unzip -l output.zip` đúng 100 file trong thư mục `output/`, 0 file phụ.
