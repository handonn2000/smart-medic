# L0 · `resources/` — tri thức NGƯỜI viết tay

`resources/` **≠** `data/`.

- `resources/` = thứ **người viết tay và review được**: từ điển cue phủ định, tiêu đề mục,
  thuật ngữ dân dã, mẫu dòng xét nghiệm. Chúng là **file dữ liệu, không phải code** —
  chỉnh được mà không train lại, và bác sĩ đọc được mà không cần đọc Python.
- `data/` = thứ máy sinh hoặc tải về. Gitignore hết trừ `test/` và gold.

## Vì sao YAML chứ không phải Python

Từ điển cue tiếng Việt sẽ được **chỉnh hàng chục lần** trong dự án này. Nếu nó nằm trong
code thì mỗi lần chỉnh là một diff phải review bởi người đọc code; nếu nó là YAML thì một
bác sĩ đọc được và một agent sửa được mà không chạm vào logic.

## Bốn file

| File | Nội dung | Ai đọc | Phase |
|---|---|---|---|
| `cues_vi.yaml` | phủ định · người nhà · tiền sử · **GIẢ ĐỊNH** · điểm kết thúc phạm vi | `assertion/lexicon.py` | P4 |
| `sections_vi.yaml` | `"Tiền sử bệnh nội khoa:"` → `SECTION_SCOPE` | `assertion/scope.py` | P4 |
| `lay_terms_vi.yaml` | dân dã → chuẩn (`"đi tiêu ra máu"` → xuất huyết tiêu hoá dưới) | `linking/retrieve.py` | P5 |
| `lab_patterns.yaml` | mẫu `TÊN: giá trị`, đơn vị, dấu phẩy thập phân | `extract/labvalues.py` | P1 |

## Khung `cues_vi.yaml`

Năm nhóm, và nhóm thứ tư là nhóm hay bị bỏ sót nhất:

```yaml
negation:            # → cạnh NEGATION_SCOPE
  - {cue: "không", direction: forward, window: 30}
  - {cue: "chưa", direction: forward, window: 30}
  - {cue: "loại trừ", direction: forward, window: 20}

family:              # isFamily — tần suất gold 1,1% ⇒ 3 dòng, không đầu tư thêm
  - {cue: "mẹ", direction: forward, window: 15}

historical:          # → đặc trưng, KHÔNG phải luật (55,2% span trong mục vẫn không mang cờ)
  - {cue: "tiền sử", direction: forward, window: 40}

hypothetical:        # ⚠ KHÔNG phải một trong ba nhãn ⇒ assertions phải RỖNG
  - {cue: "có thể", direction: forward, window: 20}    # cue giả định ở 75/100 file
  - {cue: "nếu", direction: forward, window: 25}
  - {cue: "nghi ngờ", direction: forward, window: 20}

terminators:         # điểm kết thúc phạm vi
  - "nhưng"
  - ";"
  - "\n"
```

Nhóm `hypothetical` là **bộ XOÁ cạnh** (`assertion/veto.py`), không phải bộ sinh cạnh:
"có thể viêm phổi" **không** là `isNegated`, và cũng không là nhãn nào — `assertions`
phải rỗng.

## Bất biến

- Mọi cue có `window` và `direction` tường minh. Không có cue nào "phủ cả câu" mặc định.
- Mỗi lần thêm cue phải kèm đo lại **P (độ chính xác) của bộ sinh cạnh đó**. Điểm hoà vốn
  là **P ≈ 0,50**; dưới đó, thêm cue là **âm điểm** (xem `assertion/README.md`).
