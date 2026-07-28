# Lớp validate mã + tách holdout (2026-07-27)

Hai việc chặn còn lại sau khi chốt gold. Cả hai đều là **hạ tầng đo lường**:
chúng không làm điểm tăng, chúng làm cho các con số về sau đáng tin.

`156 test xanh (133 → +23)`, gold dựng lại byte-identical, không hồi quy.

## 1. Chuẩn hóa mã candidates — `src/smart_medic/kb/validate.py`

Trước đây `_clean_candidates()` chỉ ép kiểu string, **không kiểm mã có tồn tại**.
Đây là lớp lỗi im lặng đúng nghĩa: mã sai không làm gãy schema, nó chỉ lặng lẽ
cho Jaccard = 0 ở đúng thành phần **trọng số 0.4**.

Chạy lại hai lượt gold gốc qua tầng mới → bắt được **20 mã hỏng**:

| | opus-5 | sonnet-5 |
|---|---|---|
| cắt hậu tố ICD-10-CM → WHO | 5 | 13 |
| loại vì không cứu được | 2 | 0 |

Ví dụ: `I25.10 → I25.1`, `L03.90 → L03.9`, `G47.33 → G47.3`, `K05.9 → K05`,
`R56.9 → R56`, `I48.91 → I48.9`. Tất cả đều là mã **ICD-10-CM (Mỹ)** đặc hiệu
hơn một bậc so với danh mục WHO/Việt Nam trong KB.

Hai hướng đi **một chiều** và có chủ đích:

* Cắt hậu tố chỉ đi từ **đặc hiệu → tổng quát**. Nâng mã cha lên con `.9` là
  việc của tầng quyết định (`_prefer_unspecified_child`), nơi có bằng chứng
  riêng. Trộn hai việc vào một chỗ thì không còn đo được tầng nào gây ra gì.
* RxNorm đi theo bảng remap của **chính bản RxNorm trong repo**, không gọi mạng.

### Giới hạn đã đo, không phải giới hạn phỏng đoán

* **Bảng remap chỉ cứu được một phần: 13.528/22.330 (60,6%) mã đích của remap
  bản thân chúng cũng không có trong `rxnorm_concepts`** — đã obsolete hoặc bị
  lọc `SUPPRESS`. Chuỗi kế thừa cụt giữa chừng là phổ biến, nên nhánh "remap
  không dẫn tới đâu → loại bỏ" chạy thường xuyên chứ không phải nhánh chết.
* **Có mã hỏng mà bảng không hề biết.** `727` (nhôm hydroxid, retire 04/2005,
  mã đúng `612`) KHÔNG có trong `RXNCUI.RRF` bản này — báo cáo trước phát hiện
  nó nhờ tra **RxNav bên ngoài**. Tầng này chỉ **loại** được nó, không sửa được.
  Sửa thì phải gọi mạng, mà điều đó vi phạm NFR1 nên **cố ý không làm**. Có test
  khóa hành vi này lại để không ai "sửa" bằng một bảng tay chép từ RxNav rồi
  quên mất là đã chép.

### Hỏng thì hỏng to

`--ingest` nay **fail loud** khi không nạp được KB (exit 2) thay vì âm thầm bỏ
qua khâu kiểm mã. Muốn ingest không kiểm mã thì phải nói rõ `--no-kb`.

## 2. Tách holdout — `HOLDOUT_FILES = (12, 16, 25, 26, 31, 42)`

Vì sao cần: `data/test/`, `data/silver_prompts/` và `data/dev_gold/` là **cùng
một tập file**. Nhãn bạc là pseudo-label cho chính tập test, và không có chỗ nào
tách holdout. Nên "v4 > v3 trên gold" là phép so **không công bằng** — v4 đã
train trên đúng 20 file gold đó, v3 thì chưa; con số sẽ đẹp và phần đẹp lên có
thể chỉ là ghi nhớ.

Chọn 6 file để **phản chiếu phân tầng của tập dev**, không lấy bừa:

| | dev (20) | holdout (6) |
|---|---|---|
| ghi chú lâm sàng : hỏi đáp : giáo dục | 8 : 9 : 3 | 2 : 3 : 1 |
| NFD | 6 (30%) | 2 (33%) |
| có token bị che | 7 (35%) | 2 (33%) |

NFD và token che **phải** có mặt: đó là hai chỗ đã gây lỗi thật (position lệch
âm thầm; mất hoạt chất để map RxNorm). Holdout toàn file NFC sạch sẽ báo "ổn"
ngay cả khi hai lớp lỗi đó quay lại.

### Cái bẫy mà `--holdout` phải tránh

Lọc riêng thư mục gold là **không đủ**. Silver phủ file 1–100, nên một file gold
"giữ lại" vẫn lọt vào train qua đường nhãn bạc, và holdout mất tác dụng mà không
có triệu chứng nào. Vì vậy `load_dataset()` lọc theo tên file **sau khi đã gộp**
mọi thư mục. Có test riêng cho đúng ca này (`test_holdout_file_present_in_both_dirs_is_excluded_from_both`).

### Chấm trên holdout mà không nhân đôi gold

Thêm `--files` cho `smart_medic.score`. Nhân đôi gold ra một thư mục riêng thì
bản sao sẽ trôi khỏi bản gốc; lọc lúc chấm thì không có gì trôi được.

```bash
PYTHONPATH=src python3 -m smart_medic.score --pred data/output --gold data/dev_gold --files 12,16,25,26,31,42
```

## 3. Baseline v3 trên holdout — ghi TRƯỚC khi v4 tồn tại

Artifact `pipeline_version 3.3.0`, `git_sha e714e35`. Ghi lại đây để phép so về
sau không thể chọn lại thước đo cho vừa kết quả.

| tập | text | assert | cand | FINAL |
|---|---|---|---|---|
| **holdout (6 file)** | 0.4012 | 0.3876 | 0.4111 | **0.4011** |
| train (14 file) | 0.3600 | 0.3474 | 0.3351 | 0.3463 |
| cả 20 file | 0.3724 | 0.3594 | 0.3579 | 0.3627 |

**Holdout DỄ hơn tập train với v3** (0.4011 so với 0.3463). Nên khi v4 xong,
phải so với **0.4011**, không phải với 0.3627. Đây đúng là loại nhầm lẫn mà việc
ghi baseline trước ngăn được.

### Cảnh báo: 6 file là mẫu mỏng

| file | 12 | 16 | 25 | 26 | 31 | 42 |
|---|---|---|---|---|---|---|
| text | 0.136 | 0.825 | 0.265 | 0.336 | 0.307 | 0.539 |
| khớp | 6/35 | 18/21 | 12/44 | 19/55 | 16/41 | 34/49 |

Biên độ **0.136 → 0.825** trên 6 file. Trung bình của 6 quan sát trải rộng thế
này thì di chuyển ±0.05 chỉ vì đổi thành phần tập, chưa cần model đổi gì. Hệ quả
thực dụng: **đừng tin một khác biệt nhỏ hơn ~0.05 trên holdout**. Muốn kết luận
chắc thì cần một trong hai:

* nới holdout (nhưng gold chỉ có 20 file — đổi lấy dữ liệu train);
* hoặc annotate thêm file ngoài 20 file dev để có holdout thật sự riêng.

Cách thứ hai đắt hơn nhưng là cách duy nhất thoát khỏi việc train và đo trên
cùng một tập file.

## Việc tiếp theo

1. Silver §3–§5 của [kế hoạch](2026-07-27-silver-plan.md): fan-out 80 file × 3
   model. **Cần API key — chưa chạy được ở đây.** Prompt đã sẵn trong
   `data/silver_prompts/`; ingest nay tự chuẩn hóa mã, nên `--ingest` sạch hơn
   lượt gold trước.
2. Train với holdout mặc định, rồi chấm cả hai tập:
   ```bash
   .venv/bin/python scripts/train_ner.py --silver data/silver --gold data/dev_gold --export models
   PYTHONPATH=src python3 -m smart_medic.score --pred data/output --gold data/dev_gold --files 12,16,25,26,31,42
   ```
3. Xem lại quy mô gold: 979 mention → ~3.589 quy mô corpus, **vượt chặn 2.940**
   suy từ delta leaderboard ở v4.2. Chưa giải quyết, xem
   [báo cáo phân xử](2026-07-27-dev-gold-adjudication-ket-qua.md) §cảnh báo.
