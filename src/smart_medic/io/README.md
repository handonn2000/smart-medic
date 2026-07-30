# L1 · `io/` — cổng sống còn

**Sở hữu:** không sinh điểm nào, nhưng **chặn cả 70,00 điểm**. Sai layer này thì mọi
phép đo phía sau vô nghĩa, và sai **hoàn toàn im lặng** — không exception, không log,
chỉ là điểm 0.

## Hợp đồng

```python
@dataclass(frozen=True)
class Document:
    doc_id: str
    raw: str                                    # BẤT BIẾN. Nguồn chân lý duy nhất cho offset.
    def slice(self, s: int, e: int) -> str: ...  # → raw[s:e]
    def to_raw(self, norm_idx: int) -> int: ...  # ánh xạ ngược qua char_map

# corpus.py
load_test()   -> list[Document]   # data/test/            100 file, BẤT BIẾN
load_gold()   -> list[Document]   # restyled/annotations_gold/   162 file
load_silver() -> list[Document]   # 543 file, LỌC 165 vi phạm schema lúc nạp
```

## Bất biến — dung sai 0

1. `raw` đọc với `newline=""` để không bị Python dịch `\r\n` → `\n`. Một lần dịch là
   lệch mọi offset sau đó.
2. `raw` không bao giờ bị chuẩn hoá, strip, hay thay khoảng trắng.
3. `.normalized` + `.char_map` tồn tại **chỉ để so khớp** (gazetteer, tokenizer).
   Mọi index tính trên `.normalized` phải qua `to_raw()` trước khi ra khỏi pipeline.
4. Với mọi entity xuất ra: `raw[start:end] == text`, so sánh **byte-exact**.

## Chế độ hỏng đã biết

| Hỏng | Hậu quả | Phòng thủ |
|---|---|---|
| Chuẩn hoá NFC trước khi tính offset | lệch tới 143 ký tự, **im lặng**; 20/100 file test không NFC | `raw` immutable + assert byte-exact + `tests/test_offsets.py` dung sai 0 |
| Đọc file để Python dịch newline | mọi offset lệch theo số dòng | `newline=""` |
| Agent sửa `data/test/` | mọi phép đo vô nghĩa | hook `PreToolUse` chặn + `tests/data_test_manifest.json` (sha256) |
| Học từ silver kèm 165 vi phạm schema | model học cả lỗi | `load_silver()` lọc lúc nạp, **không** regenerate 543 file |

## File

| File | Trạng thái | Phase |
|---|---|---|
| `document.py` | ✅ | P0 |
| `corpus.py` | ✅ | P0 |

## Kiểm

```bash
python3 -m pytest tests/test_offsets.py -q
```

Phải **sạch** trước mọi phép chấm. `test_silver_offsets` fail với 165 vi phạm là lỗi
thật trong dữ liệu bạc — đừng "sửa" test.
