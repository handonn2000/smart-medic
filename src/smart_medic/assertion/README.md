# L4a · `assertion/` — cờ ngữ cảnh · 8,18 ĐIỂM

**Sở hữu 8,18 điểm, KHÔNG phải 13,3.** Bản kế hoạch đầu lấy baseline 0,507 (đo trên 3
loại *mang* assertion) rồi nhân toàn bộ trọng số 0,3. Nhưng 2 loại xét nghiệm luôn rỗng
nên được Jaccard = 1 miễn phí, kéo `assertions_score` toàn cục lên 0,7271.

Phân rã đo được: **`isNegated` 3,98 · `isHistorical` 3,94 · `isFamily` 0,26.**

⇒ **Nhắm 7,92 điểm. KHÔNG đầu tư vào `isFamily`** (tần suất gold 1,1%).

8,18 điểm này là **có điều kiện** — chỉ tính trên entity đã được `extract/` khớp.

## Hợp đồng

```python
assertion.build_graph(spans, doc, layout) -> ScopeGraph
assertion.infer(spans, graph)             -> dict[Span, dist8]   # PHÂN PHỐI 8 chiều

@dataclass
class ScopeGraph:
    nodes: list[Node]    # concept | cue | section
    edges: list[Edge]    # (src, dst, kind, weight)
    #  kind ∈ {SECTION_SCOPE, NEGATION_SCOPE, HEDGE_BLOCK, COREF, SAME_MASK}
    def features(self, span: Span) -> dict[str, float]:   # TRỌNG SỐ, không phải nhãn
        ...
```

## Vì sao là đồ thị, không phải bộ phân loại từng entity

Quan hệ cần biểu diễn là **1 → n**: một cue phủ n concept. 46/100 file test có dạng liệt
kê ngay sau "không"; **45,4% entity `isNegated` chia sẻ cue** với entity khác. Một bộ
phân loại chạy độc lập trên từng entity có trần thấp theo cấu tạo.

`ScopeGraph` là **cấu trúc dữ liệu**; ba file dưới là bộ sinh/xoá cạnh ghi vào nó:

| File | Vai trò |
|---|---|
| `context.py` | **bộ SINH cạnh** — ConText: cue → cửa sổ token → điểm kết thúc phạm vi |
| `scope.py` | **bộ SINH cạnh** — mục → mọi concept trong mục |
| `veto.py` | **bộ XOÁ cạnh** — ngữ cảnh giả định · vai NGUỒN · thể loại |

`decode.py` không đọc cue nữa; nó đọc **vector đặc trưng trên nút** do đồ thị sinh ra.

## Bất biến quan trọng nhất của layer

**Cạnh là đặc trưng có TRỌNG SỐ, không phải luật quyết định.**

Bằng chứng số: span trong mục tiền sử/gia đình có `isHistorical` ở 42,1% so với 21,2%
nơi khác (nâng 1,99×) — nhưng **55,2% span trong mục đó vẫn KHÔNG mang cờ**. Biến thành
luật cứng thì P = 0,448, dưới điểm hoà vốn P ≈ 0,50 ⇒ **âm 0,21 điểm** so với bỏ hẳn
`isHistorical`.

Đường hoà vốn đo được (mốc: bỏ hẳn `isHistorical` = 66,06):

| Luật cứng theo mục | leaderboard | so với bỏ hẳn |
|---|---|---|
| R = 0,421 · P = 0,448 (đúng như đo) | 65,86 | **−0,21** |
| R = 0,421 · P = 0,55 | 66,48 | +0,41 |
| R = 0,90 · P = 0,70 | 68,08 | +2,01 |

Điểm hoà vốn ở **P ≈ 0,50 bất kể R**. Đồ thị chỉ đúng khi kết hợp với cue tuyến tính và
đầu ra encoder để đẩy P vượt 0,50.

## Hai quyết định giải mã

1. **Softmax 8 chiều trên tập con, không phải 3 sigmoid độc lập.** 3 sigmoid không biểu
   diễn được tương quan `{isNegated, isHistorical}` (1,2% gold mang cả hai).
2. **Giải mã bằng argmax kỳ vọng Jaccard** trên 8 tập con (64 phép/entity) — metric là
   Jaccard, nên tối đa hoá kỳ vọng Jaccard, không phải likelihood.

## File

| File | Trạng thái | Phase |
|---|---|---|
| `scope_graph.py` | ⬜ | P4 |
| `lexicon.py` (nạp `resources/cues_vi.yaml`) | ⬜ | P4 |
| `context.py` · `scope.py` · `veto.py` | ⬜ | P4 |
| `decode.py` | ⬜ | P4 |

## Cái bẫy của layer này

| Bẫy | Vì sao | Phòng thủ |
|---|---|---|
| Biến đặc trưng mục thành luật | 55,2% span trong mục vẫn không mang cờ | đặc trưng có trọng số; đo P của mọi bộ sinh cạnh **trước** khi bật |
| Bật cờ ở ngữ cảnh giả định | cue giả định (`có thể`, `nếu`, `nghi ngờ`) ở 75/100 file, và **không** phải một trong ba nhãn ⇒ assertions phải RỖNG | `veto.py` xoá cạnh + contrast set trong regression |
| Học từ silver | 165 vi phạm schema đúng chỗ này | lọc lúc nạp ở `io/corpus.py` |
| Phạm vi chung cho mọi cờ | phạm vi theo cấu trúc giúp `isNegated` (+0,07 F1) nhưng **hại** `isHistorical` (−0,08) | chính sách **RIÊNG từng cờ** |
| Ép nhất quán assertions theo tài liệu | 3,98% xung đột là thật | chỉ ép nhất quán `type` và mã, không ép assertions |

## Nghiệm thu

- `assertions_score` ≥ 0,90 toàn cục (rỗng hết = 0,7271; hoàn hảo = 1,0000).
- F1 `isNegated` và `isHistorical` báo **riêng**, kèm tp/fp/fn từ `diagnostics()`.
- 0 vi phạm schema: không entity `TÊN_XÉT_NGHIỆM`/`KẾT_QUẢ_XÉT_NGHIỆM` nào mang assertions.
- Contrast set ~80 cặp lật assertion bằng sửa tối thiểu; nhất quán < 0,95 là **BUG**,
  không phải khoảng trống mô hình.
- `fp` ≫ `fn` nghĩa là luật đang cháy trên ngữ cảnh giả định — siết `veto.py`, đừng chỉnh model.
