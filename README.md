# Smart Medic

**Ontological Reasoning in Medical Knowledge Retrieval** — hệ thống AI đọc văn bản y khoa tiếng Việt tự do (ghi chú bác sĩ, giấy xuất viện, kết quả xét nghiệm, hồ sơ EHR) và:

1. **Phát hiện & chuẩn hóa khái niệm y tế** — ánh xạ cụm từ ngôn ngữ tự nhiên sang mã chuẩn (ICD-10 cho bệnh, RxNorm cho thuốc).
2. **Suy luận ontology** — xác định quan hệ ngữ cảnh giữa các khái niệm (phủ định, tiền sử, người nhà).

Làm cho **Viettel AI Race 2026 — Vòng 1**. Đề bài đầy đủ, phân tích dữ liệu, thiết kế hệ thống và lộ trình: [`docs/PRD.html`](docs/PRD.html) (6 tab).

---

## Cài đặt

**Yêu cầu: Python ≥ 3.10. Không có dependency ngoài** — v0 chỉ dùng thư viện chuẩn.

```bash
git clone <repo> && cd smart-medic
python3 --version          # ≥ 3.10
```

Không cần `pip install`, không cần virtualenv, không cần mạng. Đây là quyết định có chủ đích: yêu cầu reproducible của BTC là ràng buộc cứng nhất, và mỗi dependency là một cách để việc cài đặt thất bại trên máy khác.

## Chạy

```bash
# 1. Dựng Knowledge Base từ nguồn thô (~12 giây, chạy một lần)
python3 src/smart_medic/kb/build.py

# 2. Chạy inference trên 100 file test (~0,7 giây)
PYTHONPATH=src python3 -m smart_medic.infer \
    --input data/test --output data/output --zip data/output.zip

# 3. Kiểm tra schema + verify position (dùng chính pred làm gold)
PYTHONPATH=src python3 -m smart_medic.score \
    --pred data/output --gold data/output --src data/test
#   → phải ra FINAL_SCORE = 1.0000 và Schema OK

# 4. Test
python3 -m unittest discover -s tests -v
```

Chấm điểm thật khi đã có thư mục `gold/`:

```bash
PYTHONPATH=src python3 -m smart_medic.score \
    --pred data/output --gold data/gold --src data/test --verbose
```

## Trạng thái: **v0** hoàn thành

| Vòng | Nội dung | Trạng thái |
|---|---|---|
| **v0** | Hạ tầng + gazetteer ICD tất định, không LLM | ✅ xong |
| v1 | LLM trích xuất + hai nhánh mapping (ICD + RxNorm) | chưa |
| v2 | Rerank, ngưỡng precision, co-reference token bị che | chưa |
| v3 | Distill sang encoder offline (chỉ khi vào top-15) | chưa |

Kết quả v0 trên 100 file test: **717 mention** (524 `CHẨN_ĐOÁN` có mã ICD, 193 `TRIỆU_CHỨNG`), 0 lỗi schema, 0 span vi phạm bất biến vị trí, chạy 0,7 giây, hoàn toàn tất định và offline.

## Cấu trúc

```
smart-medic/
├── src/smart_medic/
│   ├── normalize.py       chuẩn hóa — MỘT nguồn sự thật duy nhất
│   ├── textref.py         TextRef + offset map NFC↔raw   ← tầng nền
│   ├── schema.py          ConceptType, Span, Mention, type gate, validate
│   ├── pipeline.py        DAG các stage, chính sách suy giảm an toàn
│   ├── infer.py           entrypoint + đóng gói output.zip
│   ├── score.py           WER + Jaccard + validate schema
│   ├── kb/
│   │   ├── build.py       dựng KB từ ICD10.csv + RXNCONSO.RRF + RXNCUI.RRF
│   │   └── store.py       nạp KB + gazetteer longest-match
│   └── stages/
│       ├── extract.py     Extractor protocol + GazetteerExtractor (v0)
│       ├── locate.py      định vị span trên chuỗi thô
│       └── assertion.py   SectionMap + luật negation/historical
├── tests/test_v0.py       35 test, chỉ dùng unittest
├── data/
│   ├── knowledge_base/    nguồn thô: ICD10.csv, RxNorm_full_07062026/
│   ├── kb/                KB đã build (CSV.gz + MANIFEST.json)
│   ├── test/              100 file input
│   └── output/            kết quả + run_manifest.json
└── docs/
    ├── PRD.html           đề bài + phân tích + thiết kế + kế hoạch
    └── reports/           báo cáo phân tích dữ liệu, system design, kế hoạch
```

## Bốn quyết định thiết kế đáng biết trước khi sửa code

**1. `textref.py` là tầng nền, không phải utility.** 20/100 file lưu ở dạng NFD — dấu thanh là ký tự tổ hợp riêng. `str.find()` thất bại dù mắt thường thấy chuỗi có trong văn bản. Lỗi này **không ném exception**, nó chỉ âm thầm làm sai `position`. Mọi so khớp làm trên `.norm`, mọi `position` tính trên `.raw`, `to_raw()` là cây cầu duy nhất.

**2. Type gate cưỡng chế bằng hệ thống kiểu.** Đo được: **27%** mention khớp gazetteer ICD nguyên văn rơi vào chương R — là triệu chứng, không phải chẩn đoán (`khó thở`→R06.0, `đau đầu`→R51). Schema bắt `candidates` của `TRIỆU_CHỨNG` phải rỗng, nên `Mention.__post_init__` **ném lỗi** nếu gán mã sai type. Không trông cậy vào việc lập trình viên nhớ.

**3. Một hàm normalize duy nhất, cưỡng chế bằng test.** `build_textref(s).norm == norm_text(s)` được khẳng định trên toàn bộ 100 file corpus. Nếu hai đường đi lệch nhau, alias trong KB và mention lúc chạy sẽ không bao giờ khớp — và không có exception nào được ném. `MANIFEST.json` ghi `normalizer_version`; pipeline **từ chối chạy** nếu KB build bằng version khác.

**4. Mặc định an toàn = mặc định điểm cao.** Metric quy ước `J = 1` khi cả gold lẫn pred đều rỗng, và `candidates` rỗng an toàn hơn đoán bừa. Nên mọi stage suy giảm về giá trị rỗng thay vì ném lỗi: một file hỏng chỉ mất mention của nó, không làm hỏng 99 file còn lại. Trường hợp xấu nhất là `[]` — vẫn đúng schema, vẫn nộp được.

## Hai câu hỏi còn chặn, phải hỏi BTC

**1. Công thức `candidates_score` chính xác là gì?** Công thức trong đề được trích từ ảnh và tự mâu thuẫn — chấm bộ dự đoán hoàn hảo chỉ được 0,336 thay vì 1,0. Chênh tới 0,27 điểm giữa hai cách hiểu, đủ để đảo thứ hạng. `score.py` hiện thực cách hiểu hợp lý nhất và để các biến thể sau cờ dòng lệnh (`--match`, `--wer`, `--unmatched`).

**2. Gold label dùng bản RxNorm nào?** Mã `360047` trong chính ví dụ của đề đã hết hiệu lực từ 07/2019 → remap sang `2178097`; và `2178097` nay cũng đã `SUPPRESS=O` trong bản 2026 của repo. **Cả chuỗi kế thừa đã chết** — không mã nào trong repo tái tạo được đáp án mẫu của đề. `RXNCUI.RRF` có 22.330 mã đã remap. Pipeline có sẵn cờ `--rxnorm-output-mode current|legacy|both` để đảo chiều mà không phải build lại index.

## Giấy phép

Code: [MIT](LICENSE). Dữ liệu tham chiếu của bên thứ ba (ICD-10, RxNorm) giữ nguyên điều khoản gốc, đưa vào đây cho mục đích nghiên cứu/thi đấu.
