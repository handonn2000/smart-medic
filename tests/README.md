# `tests/` — thi hành ràng buộc, không phải chứng minh code chạy

Ba trong số các test ở đây không kiểm tra logic — chúng biến **ràng buộc quy chế** thành
**lỗi build**. Đó là mục đích chính của thư mục này.

## Chạy

```bash
python3 -m pytest tests/ -q
```

`test_silver_offsets` **FAIL là bình thường**: 165 entity `TÊN_XÉT_NGHIỆM` /
`KẾT_QUẢ_XÉT_NGHIỆM` trong corpus bạc đang mang assertions. Đó là **lỗi thật trong dữ
liệu**, không phải test hỏng. **Đừng "sửa" test.** Chính sách: lọc lúc nạp trong
`io/corpus.py`.

## File

| File | Kiểm | Trạng thái |
|---|---|---|
| `test_offsets.py` | `text == raw[start:end]` byte-exact · NFC/NFD round-trip · `data/test/` không bị sửa · lược đồ output | ✅ 322 dòng |
| `test_scoring.py` | self-test scorer; quan trọng nhất: `test_matched_aggregation_is_degenerate_*` **chứng minh trên dữ liệu thật** rằng cách đọc `matched` thưởng cho việc xoá dự đoán của chính mình | ✅ 143 dòng |
| `data_test_manifest.json` | sha256 của 100 file test — lớp bảo vệ thứ hai sau hook | ✅ |
| `test_alignment_parity.py` | **fail** khi `greedy_iou` tăng mà `overlap_type` giảm > 0,010 | ⬜ P2 |
| `test_no_api_in_runtime.py` | 3 test chống rò rỉ API — xem dưới | ⬜ P0 |
| `test_layer_boundaries.py` | không layer nào import từ layer cao hơn nó | ⬜ P0 |
| `fixtures/` | ca khó viết tay, dùng làm regression | ⬜ P4 |

## Ba test chống rò rỉ API vào runtime

Chế độ hỏng thực tế nhất theo [ADR 0003](../docs/decisions/0003-closed-api-for-data-generation.md),
và nó **chỉ lộ ra ở vòng chấm source code** — tức khi đã quá muộn.

1. **`test_no_vendor_http_in_runtime`** — import `smart_medic.pipeline`, đi hết `sys.modules`
   sau import, khẳng định **không** có `openai`, `anthropic`, `google.genai`, `httpx`,
   `requests`, `aiohttp`. Test **cấu trúc**, không phải grep — bắt cả import gián tiếp.
2. **`test_no_network_at_inference`** — chạy pipeline trên 3 file test với `socket.socket`
   bị monkeypatch thành ném lỗi. Lớp này bắt được cả HTTP client tự viết.
3. **`test_param_budget`** — nạp `configs/models.yaml`, tổng trường `params`, khẳng định
   **< 9e9**.

## Hook tự động

`.claude/settings.json` chạy `pytest tests/test_offsets.py -q -k "not silver"` sau **mọi**
sửa đổi vào `src/**.py` hoặc `tests/**.py`, và **block** nếu fail. Nghĩa là không thể merge
một thay đổi làm lệch offset — kể cả khi quên chạy test.

## Ba việc không được bỏ dù hết thời gian

- `pytest tests/test_offsets.py` sạch
- ba test chống rò rỉ API xanh
- `unzip -l output.zip` đúng 100 file trong thư mục `output/`

Ba việc đó **không cho thêm điểm nào**, nhưng bỏ một trong ba là mất toàn bộ 70,00.
