# `scripts/` — build-time · nơi DUY NHẤT được gọi API

Ranh giới quan trọng nhất của repo này chạy qua đây: **`scripts/` là build-time,
`src/smart_medic/` là runtime.** [ADR 0003](../docs/decisions/0003-closed-api-for-data-generation.md)
cho phép dùng API closed-source để *sinh dữ liệu*; ràng buộc ≤9B tham số self-host chỉ áp
cho **pipeline suy luận**.

Rủi ro thật không phải "dùng API sai" mà là **rò rỉ API vào runtime** — và nó chỉ lộ ra ở
vòng chấm source code, tức khi đã quá muộn. Ba test thi hành ranh giới này (xem
[`tests/README.md`](../tests/README.md)).

⇒ **Mọi lời gọi API sống ở đây. Không bao giờ trong `src/smart_medic/`.**

## Bốn thư mục con

| Thư mục | Nội dung | Trạng thái |
|---|---|---|
| `data_gen/` | `gen_sample_data.py` — sinh bệnh án tổng hợp (543 bạc + 162 gold). **Gọi OpenAI.** | ✅ 2.014 dòng |
| `annotation_qa/` | kiểm tra chất lượng gold: `validate.py` · `consistency.py` · `diff_report.py` · `kb.py` · `make_packets.py` · `normalize.py` · `scd_index.py` · `scd_probe3.py` | ✅ |
| `analysis/` | `measure_data.py` — **tái lập mọi con số** trong `docs/reports/*.html` | ✅ 523 dòng |
| `submit/` | `package_submission.py` — đóng gói `output.zip` + `runs/<ts>/manifest.json` | ✅ P0 |

## Chạy

```bash
# Tái lập mọi số liệu đo đạc (chạy từ gốc repo)
python3 scripts/analysis/measure_data.py

# Kiểm tra chất lượng annotation
python3 scripts/annotation_qa/validate.py
```

`measure_data.py` dùng đường dẫn tương đối từ **gốc repo** — chạy nó từ chỗ khác sẽ không
tìm thấy `data/`.

## Bất biến

1. **Không file nào trong `scripts/` được import bởi `src/smart_medic/`.** Chiều phụ thuộc
   một hướng: `scripts/` đọc `src/`, không bao giờ ngược lại.
2. **Artifact sinh ra thì gitignore.** `kb_index.pkl`, `packets/`, `scd_changes.json` sinh
   lại được — đừng commit.
3. `gen_sample_data.py` sinh dữ liệu huấn luyện đã dùng để dựng gold. **Đừng đổi logic sinh
   khi corpus đã đóng băng** — làm vậy là làm mọi con số đo trên gold không tái lập được.
