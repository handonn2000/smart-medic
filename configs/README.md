# L0 · `configs/` — tham số, do NGƯỜI sở hữu

Ba file YAML. **Chỉ người ghi vào đây** — agent hay đặt magic number, và một magic number
trong code là một ngưỡng không ai review được.

| File | Nội dung | Ai đọc |
|---|---|---|
| `pipeline.yaml` | ngưỡng, cờ bật/tắt từng stage, `emit_threshold` (biểu theo mật độ), `q0`, `target_tty`, `harmonize_min_majority` | `decision/`, `linking/`, `extract/` |
| `models.yaml` | `hf_id` + **`revision_sha`** + `params` từng model | `extract/`, khởi động pipeline |
| `metric.yaml` | `alignment: [greedy_iou, overlap_type]` — **CẢ HAI** | `eval/` |

## Ba quy ước

1. **Không magic number trong code.** Mọi ngưỡng ở đây, và `sha256` của mọi file trong
   `configs/` đi vào `runs/<ts>/manifest.json`.
2. **`models.yaml` có trường `params` cho từng model + assert tổng < 9e9 lúc khởi động.**
   Ràng buộc quy chế (≤9B tham số) trở thành **lỗi build**, không phải thứ phải nhớ.
3. **Ghim `revision_sha`, không phải tag.** Tag di chuyển được; tokenizer đổi làm offset đổi.

## Khung `pipeline.yaml`

```yaml
extract:
  model_threshold: 0.15          # ngưỡng THÔ của làn M — decision/ mới quyết định thật
  harmonize:
    pairs: [[THUỐC, TÊN_XÉT_NGHIỆM]]     # KHÔNG hài hoà CHẨN_ĐOÁN↔TRIỆU_CHỨNG
    min_majority: 4
    min_ratio: 4

decision:
  emit_threshold:                # tra theo mật độ entity/file của chính lần chạy đó
    - {density_ratio: "<0.50",     p: 0.25}
    - {density_ratio: "0.50-0.80", p: 0.38}
    - {density_ratio: ">0.80",     p: 0.45}
  gold_density_per_file: 45.9    # mẫu số của density_ratio
  q0:
    CHẨN_ĐOÁN: 0.0521
    THUỐC:     0.0588
  diagnosis_always_single_code: true    # p_d = 0.0000 trên 1.456 mention

linking:
  target_tty: IN                 # ADR 0001 bản 3 — tạm chốt IN, chờ Probe B
  exclude_rel: [inactive_ingredient_of]
  exclude_sty: [T200]            # LOẠI theo T200, KHÔNG whitelist T109/T121

assertion:
  flags: [isNegated, isHistorical]      # isFamily = 0,26 điểm ⇒ không đầu tư
```

## Trạng thái

| File | Trạng thái | Phase |
|---|---|---|
| `pipeline.yaml` | ⬜ | P0 |
| `models.yaml` | ⬜ | P0 |
| `metric.yaml` | ⬜ | P0 |
