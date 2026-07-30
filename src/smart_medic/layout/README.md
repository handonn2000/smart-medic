# L2 · `layout/` — cấu trúc tài liệu, xác định, không model

**Sở hữu:** chặn ~6,96 điểm ranh giới span và **nuôi** 8,18 điểm assertions. Toàn bộ
layer là regex + ngăn xếp thụt lề — không checkpoint, không GPU, tái lập tuyệt đối.

Hình dạng dữ liệu biện minh cho layer này: **96% file là danh sách**, 97/100 file có
dòng header dạng `Nhãn:`, 94/100 file có dòng `TÊN: giá trị`.

## Hợp đồng

```python
layout.parse(doc: Document) -> Layout

# Layout xuất ra đúng ba thứ, dùng ở khắp nơi phía dưới:
#   ① boundary_priors : set[int]        vị trí hợp lệ để bắt đầu/kết thúc span
#   ② section(offset) : SectionNode     mục chứa offset → phạm vi assertion
#   ③ unit(offset)    : LayoutUnit      đơn vị layout → neo offset, ghép cặp XN
```

## Ba quyết định đã đo

1. **Ngăn xếp thụt lề {0, 4, 8}** — ba tầng là đủ cho corpus này; tầng thứ tư không
   xuất hiện.
2. **Tách `;` vô điều kiện; tách `,` có điều kiện.** `4,7` là dấu phẩy thập phân
   (`Chol: 4,7 mmol/l`). Chỉ tách `,` khi phần theo sau khớp mẫu tên xét nghiệm.
3. **Cổng thể loại theo đơn vị layout, không theo tài liệu.** `42.txt` chèn một câu
   hỏi forum vào giữa dàn ý lâm sàng — một cờ thể loại cho cả file sẽ sai ở nửa file.

## Bất biến

- Mọi offset trong `Layout` là offset trên `Document.raw`, không phải trên `.normalized`.
- `boundary_priors` là **gợi ý cho `decision/`**, không phải bộ lọc cứng ở `extract/`.
  Nó chặn `- ` và `Chẩn đoán: ` lọt vào span — đó là 6,96 điểm rẻ nhất trong bài.

## File

| File | Vai trò | Trạng thái | Phase |
|---|---|---|---|
| `lines.py` | phân loại dòng: `NUM_HEADER` · `COLON_HEADER` · `KV` · `BULLET` · `PROSE` | ✅ | P0 |
| `outline.py` | ngăn xếp thụt lề → cây mục + đường tổ tiên | ✅ | P0 |
| `kv.py` | tách chuỗi `TÊN: giá trị` trong dòng, xử lý dấu phẩy thập phân | ✅ | P0 |
| `rules.py` | biên dịch khối `layout:` của `configs/pipeline.yaml` | ✅ | P0 |

## Nghiệm thu

- ≥97/100 file test nhận diện được dòng header.
- 0 ca `4,7` bị tách thành hai token.
- `boundary_priors` không loại bỏ bất kỳ biên gold nào trên 162 file (đo, không giả định).
