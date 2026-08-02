# Prompt khắc phục — sau bài nộp 18,6610

Ba bước sửa, suy ra từ [`docs/reports/leaderboard-gap-analysis.md`](../../../docs/reports/leaderboard-gap-analysis.md).
**Làm đúng thứ tự** — rủi ro tăng dần, và F3 phải đứng một mình để một lần nộp
phân xử đúng một giả thuyết.

| # | file | rủi ro | cần nộp thử |
|---|---|---|---|
| F1 | [`F1-chan-cum-rac-loc-ma.md`](F1-chan-cum-rac-loc-ma.md) | Thấp | Không bắt buộc |
| F2 | [`F2-mo-rong-trieu-chung.md`](F2-mo-rong-trieu-chung.md) | Trung bình | Nên |
| F3 | [`F3-gan-ma-trieu-chung.md`](F3-gan-ma-trieu-chung.md) | CAO, đối xứng | BẮT BUỘC |

## Kiểm tra lại

```bash
.venv/bin/python -m pip install rapidfuzz pandas
```

```bash
mkdir -p /tmp/chk && for f in data/output/*.json; do b=$(basename "$f" .json); case $b in explain|run_manifest) continue;; esac; cp "$f" "/tmp/chk/$b.json"; cp "data/test/$b.txt" "/tmp/chk/$b.txt"; done
```

```bash
.venv/bin/python scripts/validate_annotation.py --dir /tmp/chk --icd data/ICD10_VN.csv --rxnorm data/knowledge_base/rxnorm/RXNORM.csv
```

⚠️ **Bắt buộc `--icd data/ICD10_VN.csv`.** Trỏ nhầm sang
`data/knowledge_base/icd/ICD10.csv` thì từ điển nạp RỖNG và mọi mã bị báo sai —
xem §8 của báo cáo.
