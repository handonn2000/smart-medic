# Smart Medic

**Ontological Reasoning in Medical Knowledge Retrieval** — hệ thống AI đọc văn bản y khoa tiếng Việt tự do (ghi chú bác sĩ, giấy xuất viện, kết quả xét nghiệm, hồ sơ EHR) và:

1. **Phát hiện & chuẩn hóa khái niệm y tế** — ánh xạ cụm từ ngôn ngữ tự nhiên sang mã chuẩn (ICD-10 cho bệnh, RxNorm cho thuốc).
2. **Suy luận ontology** — xác định quan hệ ngữ cảnh giữa các khái niệm (phủ định, tiền sử, người nhà).

Làm cho **Viettel AI Race 2026 — Vòng 1**. Đề bài đầy đủ, phân tích dữ liệu, thiết kế hệ thống và lộ trình: [`docs/PRD.html`](docs/PRD.html) (6 tab).

---

## Cài đặt

**Yêu cầu: Python ≥ 3.10. Không có dependency ngoài** — v3 vẫn chỉ dùng thư viện chuẩn.

```bash
git clone <repo> && cd smart-medic
python3 --version          # ≥ 3.10
```

Không cần `pip install`, không cần virtualenv, không cần mạng. Đây là quyết định có chủ đích: yêu cầu reproducible của BTC là ràng buộc cứng nhất, và mỗi dependency là một cách để việc cài đặt thất bại trên máy khác.

## Chạy

```bash
# 1. Chạy v3.3 trên 100 file test (KB build artifact đã có trong repo)
PYTHONPATH=src python3 -m smart_medic.infer \
    --extractor v3 --input data/test --output data/output \
    --zip data/output.zip --explain

# 2. Kiểm tra schema + verify position (dùng chính pred làm gold)
PYTHONPATH=src python3 -m smart_medic.score \
    --pred data/output --gold data/output --src data/test
#   → phải ra FINAL_SCORE = 1.0000 và Schema OK

# 3. Mô phỏng ngưỡng khi chưa có gold (kết quả được ghi rõ là EXPECTED)
PYTHONPATH=src python3 -m smart_medic.metric_simulator \
    --explain data/output/explain.json

# Khi có gold dev set, cùng lệnh sẽ chấm metric thật
PYTHONPATH=src python3 -m smart_medic.metric_simulator \
    --explain data/output/explain.json --gold data/dev_gold

# 4. Test (v0 + v2 + accuracy/deployment v3)
#    TestEndToEnd xem data/output là thư mục submission; hãy để các report
#    metric_*.json ngoài thư mục này khi chạy test.
python3 -m unittest discover -s tests -v

# 5. Chứng minh bundle sạch chạy được khi không có nguồn ICD/RxNorm thô,
#    đồng thời chạy lặp 2 lần + metric simulator với curated gold
python3 scripts/clean_smoke.py

# 6. Dựng ba artifact thử nghiệm RxNorm current / legacy / both
python3 scripts/build_v3_3_variants.py
```

Baseline hồi quy v0 vẫn chạy bằng `--extractor gazetteer`. Dựng lại toàn bộ KB
từ nguồn thô bằng `python3 src/smart_medic/kb/build.py`. Nếu không có bản phát
hành RxNorm RRF cục bộ, dựng nhánh ICD vào một thư mục sạch bằng
`python3 src/smart_medic/kb/build.py --skip-rxnorm --out /tmp/smart-medic-kb`;
builder cố ý từ chối trộn artifact cũ vào một lần build thiếu nguồn.

Chấm điểm thật khi đã có thư mục `gold/`:

```bash
PYTHONPATH=src python3 -m smart_medic.score \
    --pred data/output --gold data/gold --src data/test --verbose
```

## Trạng thái hiện tại: **v3.3 precision + compatibility hardened**

Nhánh hiện tại là `feature/solution_v3`. Runtime vẫn **offline, deterministic,
không LLM và không model training**. Artifact `data/output.zip` hiện được dựng từ
v3.3: giữ toàn bộ v3.2, bổ sung batch mask resolver bảo thủ, medication parser có
cấu trúc, diagnosis context gate và bộ artifact RxNorm current/legacy/both.

| Vòng | Nội dung thực tế | Trạng thái / kết quả |
|---|---|---|
| **v0** | Hạ tầng, schema, NFC↔raw offset, gazetteer ICD, scorer và ZIP | ✅ baseline hồi quy |
| **v1** | Provider stack offline, phủ 5 type, hai nhánh ICD/RxNorm và assertion theo section | ✅ hoàn thành, không LLM |
| **v2** | Top-5 lexical rerank, ngưỡng precision, thuốc plaintext/mask, RxNorm SCD/SBD | ✅ Viettel **14.0595** |
| **v3.0** | Checksum KB, deterministic gzip/ZIP, run manifest và clean-bundle smoke | ✅ hardening; output ngữ nghĩa gần v2 |
| **v3.1** | Mention-first symptom/lab, ICD context, ConText và các rule từ corpus | ✅ Viettel **19.4812** |
| **v3.2** | Contract tests từ ví dụ BTC, regimen thuốc, type arbitration và precision gate chẩn đoán | ✅ triển khai; chờ điểm Viettel |
| **v3.3** | Cross-document mask template, structured brand regimen, context gate và RxNorm variants | ✅ artifact sẵn sàng; chờ điểm Viettel |
| **v4** | Pretrained multilingual encoder / hybrid retrieval nếu rule đạt trần | hoãn; chỉ làm khi chi phí đóng gói hợp lý |

### Điểm và phạm vi kiểm chứng

| Phép đo | v2 | v3.1 | v3.2 | v3.3 | Ý nghĩa |
|---|---:|---:|---:|---:|---|
| Viettel AI leaderboard | 14.0595 | **19.4812** | chưa nộp | chưa nộp | Điểm thật chỉ có đến v3.1 |
| Simulator expected proxy @ 0.80 | 0.8328 | 0.8705 | 0.8648 | 0.8638 | Không có gold; proxy phạt cả abstention đúng |
| Curated v3 regression | — | 1.0000 | 1.0000 | 1.0000 | 6 tình huống tự gán, không đại diện private gold |

`score --pred output --gold output = 1.0000` chỉ chứng minh schema, offset và
tính tự nhất quán; **không phải accuracy**. Proxy không biết mapping bị loại là
false positive, nên không được quy đổi thành điểm leaderboard. Nguồn accuracy
đáng tin nhất hiện tại vẫn là chênh lệch Viettel v2→v3.1.

V2 giữ nguyên baseline exact, bổ sung chẩn đoán dân dã qua retrieve-then-rerank,
phát hiện thuốc plaintext và token bị che, chỉ trả RxNorm SCD/SBD khi ngữ cảnh
có đủ hoạt chất, hàm lượng và dạng dùng. V3.0 sau đó làm cứng deployment nhưng
không chủ đích thay đổi prediction, vì vậy artifact ban đầu nhìn gần giống v2.

V3.1 bổ sung phát hiện mention trước khi linking: grammar triệu chứng dân dã,
cặp tên/kết quả xét nghiệm định lượng và định tính, rewrite ICD cho cách gọi
trong corpus, chọn parent/unspecified theo ngữ cảnh, nhận mask từ 3 ký tự và
phân biệt `Glucose` xét nghiệm với `Glucose 5% x 1000ml` truyền tĩnh mạch.
Phạm vi `isNegated` dùng ranh giới dòng/mệnh đề và pseudo-negation; phạm vi
`isHistorical` kết thúc đúng ở heading bệnh án/Q&A.

V3.2 chuyển các ví dụ chính thức thành contract tests rồi sửa theo từng contract:
span thuốc giữ trọn strength/route/frequency, liều chỉ được link trong regimen
cục bộ, section thuốc trước nhập viện chỉ đánh historical cho thuốc, indication
sau `điều trị` được phân xử về triệu chứng, và bổ sung các phrase family như
`tức ngực`, `đau thượng vị`, `ợ hơi`, `LYPH%`, `chọc dò dịch não tủy`. Precision
gate loại các mapping rộng như `tổn thương`, `tác dụng phụ`, `tránh thai`,
`cột sống` và `bàng quang`; thiếu bằng chứng RxNorm thì chủ động trả rỗng.

V3.3 thay blocklist đơn giản bằng context gate cho các alias ngắn/tổng quát và
rewrite span đầy đủ: `viêm tủy xương`→M86, `nhiễm khuẩn đường tiết niệu`→N39.0,
`phù gai thị`→H47.1 và `nhiễm khuẩn huyết`→A41. Medication parser hiểu brand +
strength + `x N viên` + route/frequency, bổ sung ba product exact Medrol, Zestril
và Coumadin. Batch resolver chỉ phục hồi mask khi template từ file khác khớp và
mọi support đồng thuận; corpus hiện tại không có ca đủ bằng chứng nên resolve 0.

So với v3.2, v3.3 thay đổi **41/100 file**. Full output có **1.585 mention**:
420 chẩn đoán, 520 triệu chứng, 251 tên xét nghiệm, 256 thuốc và 138 kết quả;
434 mention có candidates với tổng 475 mã. Diagnosis giảm ròng 31 vì 65 span
ngắn/tổng quát được bỏ hoặc thay bằng 34 span cụ thể; thuốc có thêm 3 mention
được link exact. Có 0 schema error. Artifact `data/output.zip` có SHA-256
`bd91d7a2d5ef7d26f7144b61cd65b7ce1b5987bdda6d216cc0966f5d2b7020da`.

Phần deployment xác minh SHA-256/kích thước KB; gzip và ZIP tái lập
byte-for-byte; `run_manifest.json` ghi fingerprint đầy đủ;
`scripts/clean_smoke.py` chạy v3 hai lần từ bundle không có Git metadata hay
nguồn ICD/RxNorm thô, sau đó chấm curated gold. Bộ v3.3 có **81 test**, gồm
contract batch-mask, diagnosis context, structured regimen và remap traceability.
Tất cả đều xanh khi `data/output/` chỉ chứa 100 JSON submission cùng
explain/manifest.

### Ba artifact RxNorm v3.3

| Mode | Số record thuốc đổi so với current | SHA-256 |
|---|---:|---|
| `current` | — | `bd91d7a2d5ef7d26f7144b61cd65b7ce1b5987bdda6d216cc0966f5d2b7020da` |
| `legacy` | 7 | `000f8a18668b44a938295224667dcc8df2a4a9b2301e397520bae06dc53a9978` |
| `both` | 7 | `cda377b9f109d687f5cec7cca8de0223ac342001f273a219cb5065536c0a13d6` |

Main artifact vẫn là `current`. Chỉ dùng `legacy`/`both` như thử nghiệm một biến
trên leaderboard; không thể chọn mode đúng khi BTC chưa xác nhận bản RxNorm gold.

### Khoảng trống còn lại sau v3.3

- **Thuốc vẫn là khoảng trống lớn nhất:** 242/256 mention thuốc chủ động không
  có candidate; 98/99 mask không có neo duy nhất. Cần alias/dose-form evidence
  thật hoặc gold dev trước khi mở rộng linking.
- **Precision gate chẩn đoán mới phủ nhóm lỗi quan sát được:** 420 mention còn
  lại đều có candidate; cần leaderboard/dev labels để tìm các false positive
  dài đuôi thay vì tiếp tục thêm blocklist mù.
- **Assertion historical thay đổi mạnh:** section thuốc chỉ còn đánh dấu thuốc,
  đúng contract BTC nhưng cần private-gold feedback để xác nhận cách annotate
  các indication đi kèm.
- **Chưa có gold dev thật:** simulator chỉ là guardrail. Bước kế tiếp nên là nộp
  artifact v3.3 current, phân tích delta điểm, rồi thử legacy/both từng biến.

Chi tiết: [`v3.1 enhanced solution`](docs/reports/2026-07-26-v3.1-enhanced-solution.md),
[`v3.2 rule hardening`](docs/reports/2026-07-26-v3.2-rule-hardening.md) và
[`v3.3 precision/compatibility`](docs/reports/2026-07-26-v3.3-precision-compatibility.md).

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
│   ├── retrieval.py       top-5 ICD lexical retrieval + deterministic rerank
│   ├── metric_simulator.py sweep ngưỡng; gold thật hoặc proxy có gắn nhãn
│   ├── kb/
│   │   ├── build.py       dựng KB từ ICD10.csv + RXNCONSO.RRF + RXNCUI.RRF
│   │   └── store.py       nạp KB + gazetteer longest-match
│   └── stages/
│       ├── extract.py     Extractor protocol + GazetteerExtractor (v0)
│       ├── clinical.py    grammar triệu chứng mention-first (v3)
│       ├── lab.py         cặp tên/kết quả xét nghiệm (v3)
│       ├── locate.py      định vị span trên chuỗi thô
│       └── assertion.py   SectionMap + luật negation/historical
├── tests/                 test hồi quy v0–v3 + deployment/simulator
├── scripts/
│   └── clean_smoke.py     deploy bundle sạch + chạy lặp + metric gold
├── data/
│   ├── knowledge_base/    nguồn build-time cục bộ (RxNorm RRF là tùy chọn)
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
