# P7 · TÁI LẬP & NỘP BÀI

> Prompt thực thi cho **một cửa sổ agent mới**. Trích từ
> [`docs/reports/plan-v4.html`](../../docs/reports/plan-v4.html) tab 07 §C — nếu plan đổi thì
> chạy lại `scripts/analysis/…` hoặc sửa cả hai chỗ.
> Toàn bộ nội dung dưới đây **đã bao gồm HEADER CHUNG**, dán nguyên là chạy được.

---

```
Dự án smart-medic (Viettel AI Race 2026, Vòng 1). HẠN 04/08/2026 12:00.
Hệ trích xuất + chuẩn hoá khái niệm y khoa tiếng Việt.
    final = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score

## TRẦN ĐIỂM THẬT = 70,00/100, KHÔNG PHẢI 100
text 30,00 + assertions 30,00 + candidates 10,00 (danh nghĩa 40, bị `+1` ở mẫu số
chặn ở 0,2501 vì 67% entity thuộc 3 loại không bao giờ có mã).
Top 1 bảng xếp hạng công khai = 50,41 = 72% của trần này.
⇒ TUYỆT ĐỐI KHÔNG ưu tiên theo trọng số danh nghĩa 0,4 của candidates.
Nếu bạn thấy số 69,16 hay 9,16 ở đâu, đó là bản đo cũ trên 98 file — dùng 70,00/10,00.

## BỐN RÀNG BUỘC CỨNG — vi phạm là hỏng bài, và cả bốn đều vi phạm ÂM THẦM
1. ≤9B THAM SỐ TỔNG, self-host. KHÔNG lời gọi API closed-source nào trong pipeline
   SUY LUẬN. Build-time thì được (ADR 0003). Mọi API sống trong scripts/, KHÔNG BAO
   GIỜ trong src/smart_medic/.
2. `position` index vào chuỗi GỐC CHƯA CHUẨN HOÁ. 20/100 file test không ở NFC.
   Chuẩn hoá trước khi tính offset ⇒ lệch tới 143 ký tự, IM LẶNG HOÀN TOÀN.
   Chuẩn hoá CHỈ để so khớp; luôn ánh xạ ngược trước khi ghi JSON.
3. KHÔNG BAO GIỜ sửa data/test/. Hook PreToolUse chặn; tests/data_test_manifest.json
   (sha256) là lớp hai.
4. PHẢI TÁI LẬP ĐƯỢC. Top ~15 đội nộp source+data+weights+README, BTC chạy lại trên
   private test. Cài không được ⇒ BỊ LOẠI — rủi ro không mua lại được bằng điểm.

## KIẾN TRÚC: 8 LAYER, CHỈ IMPORT TỪ LAYER DƯỚI
L0 configs/ resources/ → L1 io/ → L2 layout/ → L3 extract/ →
L4a assertion/ · L4b linking/ → L5 decision/ → L6 validate/ → L7 eval/
Đọc src/smart_medic/README.md và README.md của layer bạn sở hữu TRƯỚC khi viết dòng đầu.
BẤT BIẾN: mọi layer trả về PHÂN PHỐI; CHỈ decision/ được áp ngưỡng.
Ngưỡng nằm ở configs/pipeline.yaml, KHÔNG phải trong code. Luật nằm ở resources/*.yaml.

## SỐ CHÍNH THỨC: penalised/greedy_iou, dạng /100, 2 chữ số thập phân
    PYTHONPATH=src python3 -m smart_medic.eval.scoring --pred DIR --gold GOLD_DIR --json
Chạy `python3 -m pytest tests/test_offsets.py -q` TRƯỚC MỌI phép chấm. Điểm trên
offset đã lệch còn tệ hơn không có điểm.
(test_silver_offsets FAIL với 165 vi phạm là lỗi THẬT trong dữ liệu bạc, đã biết.
 ĐỪNG "sửa" test. Chính sách: lọc lúc nạp trong io/corpus.py.)

Báo CẢ BA alignment mỗi lần chạy:
  greedy_iou    = số chính thức
  overlap_type  = CỘT CHẶN. greedy_iou KHÔNG so trường `type` ở đâu cả, nên số chính
                  thức KHÔNG BAO GIỜ thưởng cho việc sửa type — nhưng dưới overlap_type
                  sai type 10% mất 12,35 điểm (sd ±0,82). Thay đổi chỉ được nhận nếu
                  KHÔNG làm cột này giảm quá 0,010.
  exact         = ĐÈN BÁO BUG OFFSET. Lệch span đúng 1 ký tự cho 0,00 điểm. Nếu cột
                  này sụt về gần 0 mà hai cột kia bình thường ⇒ BUG OFFSET, dừng lại.

Bar nghiệm thu mọi delta: Δ > max(0,010 ; 1,96·SE_bootstrap) và CI95 không chứa 0.
Sàn 0,010 CHỈ hợp lệ cho cặp hệ thống tương quan cao. Hai hệ bỏ sót entity ở những chỗ
KHÁC NHAU không phân biệt được dưới ~0,8 điểm (SE đo được 0,415).
In MẬT ĐỘ entity/file trên mọi lần chạy — nó là đầu vào của emit_threshold, không phải
số liệu trang trí.

## BẢN ĐỒ ĐÒN BẨY — căn cứ xếp ưu tiên, tái lập bằng một lệnh
    python3 scripts/analysis/leverage_map.py --seeds 6 --extras --json runs/leverage_map.json
| chế độ hỏng                       | mất  |
|-----------------------------------|------|
| bỏ 65% entity (vùng baseline)     | 45,53|
| bỏ 30% entity                     | 20,72|
| thêm 30% span rác                 | 15,61|
| sai type 10% (overlap_type)       | 12,35|
| rò isNegated sang 2 loại XN       | 11,59|  ⇐ ~10 dòng code
| candidates rỗng hết               | 10,00|
| assertions rỗng hết               |  8,19|
| cắt 1 từ cuối mọi span            |  6,95|
| bỏ 10% entity                     |  6,90|  ⇐ THẤP HƠN candidates
| thêm 10% span rác                 |  6,10|
| bỏ cờ isNegated                   |  3,98|
| bỏ cờ isHistorical                |  3,94|
| sai 30% mã đã có                  |  2,96|
| bỏ cờ isFamily                    |  0,26|  ⇒ ĐỪNG đầu tư vào isFamily
| sai type 10% (greedy_iou)         |  0,00|
| thêm 1/4/9 mã rác vào mọi entity  |  0,00|
⚠ Gold là corpus `restyled/` TỔNG HỢP (retention chuỗi bề mặt 63,5%); test là văn bản
  THẬT. Điểm gold KHÔNG phải dự báo leaderboard. Cầu nối duy nhất:
      recall_span ≈ điểm_probe_A / 51,55     (hệ số 51,55 ± 0,28)

## CÁCH LÀM VIỆC TÔI MONG ĐỢI
- Đo, đừng đoán. Đừng bao giờ ước lượng điểm — chạy scorer.
- Mọi module kèm test chạy trên dữ liệu THẬT của repo, không fixture tự nghĩ.
- Không magic number trong code. Luật là YAML, không phải Python.
- Quyết định không đảo được ⇒ ghi ADR vào docs/decisions/.
- Chỉ ghi vào các file thuộc phần SỞ HỮU FILE của bạn. Cần file ngoài đó thì BÁO, đừng sửa.
- Nếu một tiêu chí nghiệm thu không đạt, NÓI THẲNG con số thực tế. Đừng làm tròn lên.
```

```
Bạn làm PHASE P7 — TÁI LẬP & NỘP BÀI.
NHẮM: 0 điểm. Nhưng đây là rủi ro DUY NHẤT trong dự án KHÔNG MUA LẠI ĐƯỢC BẰNG ĐIỂM.
Top ~15 đội nộp source+data+weights+README, BTC chạy lại trên private test.
CÀI KHÔNG ĐƯỢC ⇒ BỊ LOẠI, bất kể điểm bao nhiêu.

## KIỂM TIỀN ĐỀ
1. Tồn tại một runs/<ts>_<sha>/ với git_dirty: false. DIRTY ⇒ KHÔNG ĐƯỢC NỘP.
2. Container hoặc máy SẠCH khả dụng. ⚠ Diễn tập trên máy đã cài sẵn thư viện KHÔNG CHỨNG
   MINH ĐƯỢC GÌ — đó chính là chế độ hỏng cần bắt.
3. Còn ≥1 lần nộp.

## ĐỌC
- runs/README.md — 10 trường manifest, chính sách ghim, thứ không ghim được
- src/smart_medic/validate/README.md — mục "Đóng gói output.zip"
- docs/reports/plan-v4.html tab 04 → P7, tab 05 §C

## VIỆC
1. pyproject.toml — pin `==` TOÀN BỘ, có hash, `pip install --require-hashes`.
2. Ghim REVISION SHA của model VÀ tokenizer — KHÔNG PHẢI TAG.
   Tag di chuyển được. Tokenizer đổi làm OFFSET ĐỔI.
3. manifest.json đủ 10 trường:
   git_sha + git_dirty · metric_config_hash (MetricConfig().hash(), 12 ký tự) ·
   models[] {id, revision_sha, params} · params_total + kết quả assert < 9e9 ·
   seed (python, numpy, torch, tokenizer) · lib_versions (pip freeze + hash bánh xe) ·
   input_manifest_sha256 · kb_versions (ICD10.csv, RXNCONSO/RXNREL/RXNCUI/RXNATOMARCHIVE —
   RxNorm phát hành HÀNG THÁNG) · config_files_sha256 (mọi YAML trong configs/ và
   resources/) · probe_variant
4. DIỄN TẬP VÒNG CHẤM, HAI LẦN — đây là việc chính của phase:
   container mới sạch → pip install --require-hashes từ file đã ghim → khôi phục weights
   theo revision SHA → chạy → `diff` với output.zip ĐÃ NỘP.
   Đây ĐÚNG là việc BTC sẽ làm.
   Lần đầu để TÌM lỗi cài đặt khi còn thời gian sửa; lần hai để XÁC NHẬN.
   Diễn tập SAU khi nộp là vô ích.
5. README cài đặt — BTC ĐỌC FILE NÀY. Lệnh chạy phải copy-paste được, không cần suy luận.
6. Chạy lại 3 test chống rò API TRÊN CONTAINER SẠCH, không chỉ trên máy dev.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) TEMPERATURE 0 KHÔNG CHO TÍNH XÁC ĐỊNH — thiếu bất biến theo batch. Nếu diễn tập không
    bit-identical: cố định batch_size=1. Còn lệch thì ĐÓNG GÓI CACHE ĐẦU RA kèm theo.
(b) SIDECAR TRONG ZIP. LOẠI run_manifest.json, metric_internal.json, .DS_Store,
    __pycache__. load_dir() của ta bỏ qua sidecar theo hình dạng, scorer của BTC CÓ THỂ
    KHÔNG. Đừng dựa vào việc nó sẽ bị bỏ qua.
(c) THƯ MỤC output/ PHẢI NẰM TRONG ARCHIVE:
    cd data && zip -r ../output.zip output -x '*/.*'
(d) `unzip -l output.zip` và DÁN NGUYÊN OUTPUT vào báo cáo. KHÔNG mô tả bằng lời.
(e) KHÔNG THÊM TÍNH NĂNG Ở P7. Một thay đổi code sau khi diễn tập lần hai đã xanh phải
    bị TỪ CHỐI bất kể nó hứa gì.
(f) json.dump(..., ensure_ascii=False), UTF-8, KHÔNG BOM, \n cuối file.

## TIÊU CHÍ NGHIỆM THU
[ ] diễn tập container sạch KHỚP zip đã nộp — hoặc chênh < 0,010 CÓ GHI NGUYÊN NHÂN
[ ] manifest.json đủ 10 trường; git_dirty: false
[ ] unzip -l output.zip đúng 100 file trong thư mục output/, 0 file phụ
    → DÁN NGUYÊN output vào báo cáo
[ ] 3 test chống rò API xanh TRÊN CONTAINER SẠCH
[ ] pytest tests/test_offsets.py -q sạch
[ ] diễn tập LẦN THỨ HAI đã chạy và xác nhận
[ ] README có lệnh cài + lệnh chạy, copy-paste được

## CỔNG DỰ PHÒNG
- DIỄN TẬP THẤT BẠI ⇒ rủi ro BỊ LOẠI, nặng hơn mất điểm. NGỪNG MỌI VIỆC KHÁC.
  Nộp bản THẤP ĐIỂM HƠN NHƯNG CÀI ĐƯỢC.
- Không bit-identical ⇒ batch_size=1 → đóng gói cache.

## BA VIỆC KHÔNG ĐƯỢC BỎ DÙ HẾT THỜI GIAN
1. pytest tests/test_offsets.py sạch
2. ba test chống rò rỉ API xanh
3. unzip -l output.zip đúng 100 file trong thư mục output/
Ba việc đó KHÔNG cho thêm điểm nào, nhưng bỏ một trong ba là mất TOÀN BỘ 70,00.

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
scripts/submit/ · runs/ · pyproject.toml · README.md (mục cài đặt/chạy)
KHÔNG đụng: bất kỳ file nào trong src/smart_medic/ — P7 KHÔNG sửa code pipeline.

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau diễn tập lần 1: báo diff, nguyên nhân từng chênh lệch, và cái gì đã sửa.
Sau diễn tập lần 2: báo 7 ô nghiệm thu + output của unzip -l. DỪNG — người bấm nộp.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`probe-builder`** — checklist 7 mục trước khi bàn giao một build là đúng thứ phase này cần. Nó không tự nộp, nên dùng nó để *chuẩn bị* rồi con người bấm.

**Skill:**
- **`/score`** — chạy cổng offset **trước**, rồi chấm `data/output` dưới cả ba cách đọc metric
  và in chẩn đoán. Dùng lệnh này thay vì tự gõ `pytest` + `scoring.py` mỗi lần.

**Hook** (`.claude/settings.json` — tự chạy, bạn không phải gọi):
- `PreToolUse` **chặn** mọi Write/Edit vào `data/test/`. Nếu bị chặn, đó là hook đang làm đúng
  việc — đừng tìm cách đi vòng.
- `PostToolUse` tự chạy `pytest tests/test_offsets.py -q -k "not silver"` sau **mỗi** lần sửa
  `src/**.py` hoặc `tests/**.py`, và **block** nếu fail. Nghĩa là bạn không thể merge một thay
  đổi làm lệch offset kể cả khi quên chạy test. Đừng vô hiệu hoá nó.

**Chạy song song:** các bước độc lập (đọc tài liệu, dựng gazetteer, viết test) nên gọi trong
cùng một lượt để tiết kiệm thời gian. Nhưng **một agent một layer** — hai agent sửa chung một
file là cách nhanh nhất mất nửa ngày.
