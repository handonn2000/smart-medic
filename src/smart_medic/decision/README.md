# L5 · `decision/` — nơi DUY NHẤT áp ngưỡng

~300 dòng, không train gì, và **cộng dồn với mọi layer khác**. Đây là layer rẻ nhất trên
mỗi điểm mua được, vì mọi tham số của nó là một dòng YAML chỉnh được mà không model nào
phải train lại.

Bất biến toàn cục *"các layer trả về PHÂN PHỐI, chỉ `decision/` mới áp ngưỡng"* tồn tại
để điều này khả thi.

## Hợp đồng

```python
decision.finalize(spans, dist8, cands) -> list[Concept]

@dataclass
class Concept:                       # thứ cuối cùng được tuần tự hoá
    text: str
    position: tuple[int, int]
    type: str
    assertions: list[str]
    candidates: list[str]
```

## Ba tham số, ba nguồn bằng chứng

### 1. `emit.py` — ngưỡng phát span là **BIỂU THEO MẬT ĐỘ**, không phải hằng số

Tỷ giá biên đo trực tiếp: `c_fn / c_fp = 1,14` ⇒ ngưỡng Bayes `p* = 0,468`. Nhưng con số
đó đo tại **biên gần trần**. Ở chế độ vận hành thật, một entity được cứu mang theo cả
điểm `assertions` và `candidates` của nó, nên hoà vốn dịch:

| nền bỏ sót `d` | mốc | hoà vốn |
|---|---|---|
| 10% | 63,02 | **≈ 0,44** |
| 30% | 49,45 | **≈ 0,38** |
| 60% | 28,01 | **≈ 0,23** |

```yaml
# configs/pipeline.yaml
emit_threshold:                          # tra theo mật độ entity/file của CHÍNH lần chạy đó
  - {density_ratio: "<0.50",    p: 0.25}   # đang mất >50% ⇒ mở cổng
  - {density_ratio: "0.50-0.80", p: 0.38}
  - {density_ratio: ">0.80",    p: 0.45}   # gần trần ⇒ siết về p* biên 0,468
```

`density_ratio` = (entity/file của lần chạy) / 45,9. Baseline 15,8/file ⇒ ratio 0,34 ⇒
`p = 0,25`. **Đây là lý do phải in mật độ entity/file trên mọi lần chạy** — nó là đầu
vào của một tham số quyết định, không phải số liệu trang trí.

Điều này **không** biến thành "recall bằng mọi giá": bỏ 30% + thêm 30% rác = 42,58 <
bỏ 30% thuần = 49,45 ⇒ cổng ở 0 sai ở **mọi** chế độ.

### 2. `select.py` — assertions

Argmax **kỳ vọng Jaccard** trên 8 tập con (64 phép/entity). Metric là Jaccard ⇒ tối đa
hoá kỳ vọng Jaccard, không phải likelihood.

### 3. `select.py` — candidates: LUẬT, không phải ngưỡng học được

| Đại lượng | CHẨN_ĐOÁN | THUỐC | Chính sách |
|---|---|---|---|
| `q₀` = P(gold rỗng) | 0,0521 | 0,0588 | **gần như không bao giờ bỏ trống** |
| `p_d` = P(≥2 mã \| có mã) | **0,0000** | 0,0915 | CĐ: **luôn đúng 1 mã**, không cần ngưỡng gap |
| Phân bố cỡ tập | 0:5,2% · 1:94,8% | 0:5,9% · 1:85,5% · 2:8,4% · 3:0,2% | 0/1.456 mention CĐ có 2 mã — **tuyệt đối** |

Doublet của THUỐC gần như luôn là **thuốc phối hợp** ⇒ quyết định bằng luật
`consists_of` từ KB, **không** bằng ngưỡng xác suất (gap 0,1007 chỉ là mốc kiểm).

Ngoại lệ duy nhất được bỏ trống: thuốc `*****` không suy được tên.

### 4. `calibrate.py`

Platt (2 tham số) trên `[top1, gap top1−top2, entropy, type]`. Platt > isotonic khi dưới
~300 mẫu — và ta có 162 tài liệu.

## Bất biến

- **Không magic number trong code.** Mọi ngưỡng ở `configs/pipeline.yaml`, và hash của
  config đi kèm mọi bản ghi kết quả.
- `type` **luôn** là argmax. Hedging (phát cả hai type khi mơ hồ) tốn 1,29 điểm dưới cả
  hai chế độ căn chỉnh, có test khẳng định không có `position` trùng.

## File

| File | Trạng thái | Phase |
|---|---|---|
| `emit.py` | ⬜ | P1 (bản hằng số) → P6 (biểu theo mật độ) |
| `select.py` | ⬜ | P6 |
| `calibrate.py` | ⬜ | P6 (chỉ nếu có model xác suất) |

## Nghiệm thu

- Mọi delta ≥ `max(0,010 ; 1,96·SE_bootstrap)` và CI95 không chứa 0.
- `grep -rn "0\.[0-9]" src/smart_medic/decision/` không ra ngưỡng nào — chúng ở YAML.
- Tỷ lệ trả rỗng ≤ 0,06 ngoài ca `*****`.
