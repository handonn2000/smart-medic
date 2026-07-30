# `src/smart_medic/` — bản đồ layer

Pipeline suy luận, chia thành **8 layer xếp chồng**. Mỗi layer là một thư mục, có
`README.md` riêng, và **chỉ được import từ layer thấp hơn nó**. Quy tắc này là thứ
cho phép nhiều agent làm song song mà không đụng nhau.

> Kế hoạch triển khai đầy đủ (ngân sách điểm, phase, tiêu chí nghiệm thu):
> [`docs/reports/plan-v4.html`](../../docs/reports/plan-v4.html)

## Thứ tự layer và quy tắc phụ thuộc

| # | Layer | Sở hữu | Được import từ | Trả về |
|---|---|---|---|---|
| L0 | [`configs/`](../../configs) · [`resources/`](../../resources) | tham số + tri thức người viết | — (dữ liệu, không phải code) | YAML |
| L1 | [`io/`](io) | **cổng sống còn** — chặn cả 70,00 điểm | — | `Document`, `Corpus` |
| L2 | [`layout/`](layout) | ~6,96 (ranh giới) + nuôi 8,18 | L1 | `Layout` |
| L3 | [`extract/`](extract) | **≈60,00 điểm** | L1, L2 | `list[Span]` (phân phối type) |
| L4a | [`assertion/`](assertion) | 8,18 điểm | L1–L3 | `dict[Span, dist8]` |
| L4b | [`linking/`](linking) | 10,00 điểm (biên thực 1,0–2,8) | L1–L3 | `dict[Span, list[Cand]]` |
| L5 | [`decision/`](decision) | **nơi DUY NHẤT áp ngưỡng** | L1–L4 | `list[Concept]` |
| L6 | [`validate/`](validate) | cổng cứng trước khi ghi file | L1, L5 | JSON trên đĩa |
| L7 | [`eval/`](eval) | phép đo — **ngoài** đường suy luận | chỉ đọc JSON trên đĩa | điểm + chẩn đoán |

```
data/test/N.txt  (byte thô — KHÔNG BAO GIỜ chạm)
        │
        ▼
   L1 io/  ──►  L2 layout/  ──►  L3 extract/  ──┬──►  L4a assertion/  ──┐
                                                └──►  L4b linking/    ──┤
                                                                        ▼
                                                             L5 decision/
                                                                        │
                                                                        ▼
                                                             L6 validate/
                                                                        │
                                                                        ▼
                                        runs/<ts>_<sha>/{output/, manifest.json}
                                                                        │
                                                                        ▼
                                                    L7 eval/ (đọc từ đĩa)
```

## Ba bất biến toàn cục

1. **`Document.raw` là nguồn chân lý duy nhất cho offset.** Chuẩn hoá Unicode chỉ để
   *so khớp*; mọi span xuất ra phải lấy từ `raw` qua `Document.slice()`. 20/100 file
   test không ở NFC — chuẩn hoá trước khi tính offset làm lệch tới 143 ký tự, **hoàn
   toàn im lặng**.
2. **Các layer trả về PHÂN PHỐI, chỉ `decision/` mới áp ngưỡng.** `extract/` trả
   `type_dist` + `score`, `assertion/` trả phân phối 8 chiều, `linking/` trả danh sách
   ứng viên có điểm. Không layer nào khác được chứa một con số ngưỡng.
3. **Không lời gọi API closed-source nào trong `src/`.** Mọi lời gọi API sống trong
   [`scripts/`](../../scripts) (build-time). Xem [ADR 0003](../../docs/decisions/0003-closed-api-for-data-generation.md).
   Có test cấu trúc thi hành điều này.

## Cách đọc một layer README

Mỗi README trả lời đúng năm câu:

- **Sở hữu bao nhiêu điểm** — đo bằng scorer, không suy từ trọng số đề bài.
- **Hợp đồng vào/ra** — dataclass và chữ ký hàm ổn định.
- **Bất biến** — thứ không được vi phạm dù có đánh đổi gì.
- **File dự kiến** — cái gì đã có, cái gì thuộc phase nào.
- **Chế độ hỏng** — hỏng thế nào, và phòng thủ bằng gì.

## Ngôn ngữ

README và tài liệu kế hoạch viết tiếng Việt (đội đọc, và agent đọc). Docstring,
comment và tên biến trong code viết tiếng Anh. `README.md` ở gốc repo viết tiếng Anh
vì ban tổ chức đọc file đó.
