# `data/` — máy sinh hoặc tải về

Đối lập với [`resources/`](../resources) (người viết tay). Gitignore hầu hết, trừ `test/`.

```
data/
├── test/                            🔒 BẤT BIẾN — 100 file 1.txt…100.txt, ban tổ chức chấm
├── output/                          bài nộp hiện tại — 100 file JSON (baseline: 1.585 entity)
├── knowledge_base/                  ✅ tải về · CẤU TRÚC PHẲNG, không có thư mục con
│   ├── ICD10.csv                       ⭐ TIẾNG VIỆT · 13.189 mã · 36.689 tên · KHÔNG THAY THẾ ĐƯỢC
│   ├── icd10cm-codes-2027.txt          tiếng Anh, 74.879 mã — chỉ để LÀM GIÀU theo mã (5.460 khớp)
│   ├── RXNCONSO.RRF                    tên khái niệm — thay cho RXNORM.csv đã bỏ
│   ├── RXNREL.RRF                      quan hệ: tradename_of · consists_of · has_active_ingredient
│   ├── RXNSTY.RRF                      semantic type — dùng để LOẠI T200
│   ├── RXNATOMARCHIVE.RRF              MERGED_TO_RXCUI cho mã đã rút
│   └── brand_to_ingredient.json        cache brand→ingredient (~96k)
├── generated_medical_records/       ✅ máy sinh (xem scripts/data_gen/)
│   ├── synthetic/                      194 note — LLM viết quanh entity lấy mẫu từ mã
│   ├── translated/                     187 note — dịch từ mtsamples tiếng Anh
│   └── restyled/                       162 note — dịch rồi viết lại theo thể loại tập test
│       ├── text/                          văn bản
│       ├── annotations/                   nhãn bạc
│       └── annotations_gold/            ⭐ 162 file · 7.435 entity · 0 lỗi offset/schema
├── external/en_notes/               mtsamples_filtered.jsonl — 457 note tiếng Anh (nguồn dịch)
└── artifacts/                       ⬜ index đã build, cache — SINH LẠI ĐƯỢC, gitignore
```

## `data/test/` là BẤT BIẾN — hai lớp bảo vệ

1. Hook `PreToolUse` trong `.claude/settings.json` **chặn** mọi Write/Edit vào `data/test/`.
2. `tests/data_test_manifest.json` giữ sha256 của cả 100 file; `tests/test_offsets.py`
   khẳng định không file nào đổi.

Sửa một file ở đây làm **mọi offset và mọi phép đo** trong dự án vô nghĩa. Khôi phục:
`git checkout -- data/test/`

## Ba con số phải nhớ khi đọc bất kỳ điểm nào

| | Giá trị | Hệ quả |
|---|---|---|
| Mật độ gold | **45,9 entity/file** (7.435 / 162) | mẫu số của `density_ratio` trong `configs/pipeline.yaml` |
| Mật độ baseline `data/output/` | **15,8 entity/file** | ratio 0,34 ⇒ đang mất 39–44 điểm nếu test giống gold |
| 20/100 file test **không** ở NFC | | chuẩn hoá trước khi tính offset ⇒ lệch tới 143 ký tự, im lặng |

## ⚠ Gold là dữ liệu tổng hợp, tập test là văn bản thật

`annotations_gold/` gán trên `restyled/` — văn bản tổng hợp **hai thế hệ**
(`translated → restyled`), retention chuỗi bề mặt chỉ **63,5%**; mã chẩn đoán 158 → 136,
RxCUI 288 → 223. Đây là **co ngót đệ quy đã xảy ra thật**.

⇒ **Điểm trên gold KHÔNG phải dự báo bảng xếp hạng.** Probe A là cầu nối duy nhất:
`recall_span ≈ điểm_probe_A / 51,9` (hệ số 51,88 ± 0,18, đo trên 8 mức recall).

## 165 vi phạm lược đồ trong corpus bạc

`tests/test_offsets.py::test_silver_offsets` **đang FAIL** với 165 entity
`TÊN_XÉT_NGHIỆM`/`KẾT_QUẢ_XÉT_NGHIỆM` mang assertions (đề bài cấm). Đó là **lỗi thật
trong dữ liệu**, không phải test hỏng.

Chính sách: **lọc lúc nạp** trong `io/corpus.py` (5 dòng), **không** regenerate 543 file
(nửa ngày, và làm mọi số liệu đã đo không tái lập được). `annotations_gold/` đã sạch —
0 lỗi.
