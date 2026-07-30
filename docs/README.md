# `docs/` — đề bài, quyết định, báo cáo

## Đọc theo thứ tự này

| # | File | Nội dung |
|---|---|---|
| 1 | [`reports/plan-v4.html`](reports/plan-v4.html) | ⭐ **kế hoạch hiện hành** — 9 tab: ngân sách điểm, kiến trúc, 8 phase kèm tiền đề + tiêu chí nghiệm thu, probe, rủi ro, prompt thực thi |
| 2 | [`PRD.html`](PRD.html) | đề bài gốc |
| 3 | [`decisions/`](decisions) | 3 ADR — quyết định **không đảo**. Đọc trước khi đề xuất mở lại |
| 4 | [`reports/research-directions.html`](reports/research-directions.html) | căn cứ khoa học, ~90 tài liệu đã xác minh + danh sách kết luận **âm tính** |
| 5 | [`reports/graph-llm-annotation.html`](reports/graph-llm-annotation.html) | 5 nhánh graph/LLM, 79 tài liệu |

`plan.html` là bản **v3, đã bị thay thế** bởi `plan-v4.html`. Nó còn dùng trần 69,16 /
candidates 9,16 (đo trên 98 file). Số hiện tại là **70,00 / 10,00** (162 file). Giữ lại làm
bản ghi lịch sử; **đừng trích số từ nó**.

## Ba ADR

| ADR | Câu hỏi | Trạng thái |
|---|---|---|
| [0001](decisions/0001-drug-tty.md) | `tty` mã thuốc: `IN` hay `SCD`? | **tạm chốt `IN`** (bản 3) cho gold annotation; lựa chọn khi nộp chờ Probe B. Trần ảnh hưởng ~1,1 điểm |
| [0002](decisions/0002-metric-reading.md) | cách đọc metric nào là số chính thức? | `penalised / greedy_iou`. ⚠ **Cần bổ sung một điều khoản** — xem dưới |
| [0003](decisions/0003-closed-api-for-data-generation.md) | dùng API closed-source để sinh dữ liệu có hợp lệ? | **hợp lệ**, chỉ ở build-time. Ranh giới: `scripts/` vs `src/` |

### ADR 0002 cần bổ sung, không cần mở lại

ADR 0002 chốt `greedy_iou` làm mặc định và ghi "chạy kèm `overlap_type` làm kiểm độ nhạy".
Trên thực tế `overlap_type` **không** phải kiểm độ nhạy — nó là chế độ mà **mọi quyết định
về type đều đổi dấu**:

| Thao tác | `greedy_iou` | `overlap_type` |
|---|---|---|
| hài hoà type vô điều kiện | −0,00 | −1,13 |
| sai type 2% | −0,00 | −2,90 |
| sai type 10% | −0,00 | **−14,32** (sd ±6,31) |

Đề nghị: **giữ mặc định `greedy_iou`**, bổ sung điều khoản *"số chính thức là **cặp**
`(penalised/greedy_iou, penalised/overlap_type)`, và CI fail khi số thứ nhất tăng mà số thứ
hai giảm quá 0,010"*. Một test, và nó biến rủi ro bất đối xứng lớn nhất của dự án từ thứ
phải nhớ thành lỗi build.

ADR 0002 cũng còn ghi trần 69,16 / candidates 9,16 (98 file). Số hiện tại: **70,00 / 10,00**.

## Cấu trúc

```
docs/
├── PRD.html                    đề bài gốc
├── decisions/                  ADR — quyết định không đảo
├── guidelines/                 ⬜ hướng dẫn gán nhãn (nuôi CẢ người lẫn prompt)
├── references/                 tài liệu nền (neurosymbolic, ontology engineering)
├── gold-annotation-handoff.md  bàn giao gold
└── reports/
    ├── plan-v4.html            ⭐ kế hoạch hiện hành
    ├── plan.html               bản v3 — lịch sử
    ├── research-directions.html
    ├── graph-llm-annotation.html
    └── gold-annotation-qa.md
```

Script tái lập số liệu đã chuyển sang [`scripts/analysis/measure_data.py`](../scripts/analysis/measure_data.py)
(trước ở `docs/reports/`) — nó là code, không phải tài liệu.

## Quy ước

- **Quyết định không đảo được ⇒ ghi ADR.** Không có nó, agent thứ ba sẽ hỏi lại đúng câu
  bạn đã trả lời tuần trước.
- Mỗi ADR: bối cảnh → phương án → **bằng chứng số** → quyết định → điều kiện mở lại.
- Mọi con số "đo được" trong `reports/` sinh bằng `scripts/analysis/measure_data.py` hoặc
  `src/smart_medic/eval/scoring.py`. Nếu một con số không tái lập được bằng một trong hai,
  nó không phải của chúng ta.
