# P1 · ĐƯỜNG LÙI TỐI THIỂU — sàn recall không model

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
Bạn làm PHASE P1 — ĐƯỜNG LÙI TỐI THIỂU. Sau bạn, LUÔN tồn tại một bài nộp hợp lệ.
NHẮM: 14,9–23,6 điểm. Không model, không GPU, không checkpoint. ~400 dòng Python.

## KIỂM TIỀN ĐỀ
1. `python3 -c "import sys; sys.path.insert(0,'src'); from smart_medic.io.document import Document"`
   chạy được, và Document.slice() hoạt động.
2. `python3 scripts/submit/package_submission.py --help` chạy được (P0 đã xong).
3. `ls data/knowledge_base/` có ICD10.csv và RXNCONSO.RRF (thư mục PHẲNG).
   Đọc KB qua `scripts/kb_sources.py`, KHÔNG hard-code đường dẫn.
Thiếu (1) hoặc (2) ⇒ P0 chưa xong ⇒ BÁO, DỪNG. Đo được recall mà không nộp được là vô ích.

## ĐỌC
- src/smart_medic/extract/README.md — đặc biệt phần "Hai làn, thứ tự cứng"
- resources/README.md — khung lab_patterns.yaml
- docs/reports/plan-v4.html tab 04 → P1

## VÌ SAO PHASE NÀY ĐỨNG TRƯỚC MODEL
Đây là thứ DUY NHẤT trong dự án có recall KHÔNG phụ thuộc checkpoint. Nếu hết thời gian,
đây LÀ bài nộp. Mô phỏng ở recall 0,35–0,55 với 20% span thừa: 14,9–23,6 điểm — thấp,
nhưng là một bài nộp hợp lệ không bao giờ hỏng.

## VIỆC
1. extract/aho.py — Aho–Corasick trên 14.678 tên ICD + ~22k tên IN/PIN/MIN.
   Xây chỉ mục gazetteer dùng lại được: linking/ sẽ cần đúng chỉ mục này ở P5.
   Build một lần, ghi vào data/artifacts/, hai chỗ đọc.
2. extract/labvalues.py + resources/lab_patterns.yaml — luật dòng xét nghiệm.
   41,7% entity (3.098/7.435) là 2 loại xét nghiệm, và 94/100 file có dòng `TÊN: giá trị`.
   Đây là recall RẺ NHẤT tồn tại trong bài này. Bỏ hẳn 2 loại này tốn 56,42 và 60,41 điểm.
   Mẫu phải ở YAML, không hard-code — chúng sẽ chỉnh nhiều lần.
3. extract/kvspan.py — mẫu `TÊN: giá trị` tổng quát, dùng unit(offset) từ layout/.
4. decision/emit.py bản HẰNG SỐ p = 0,25 (nhánh density_ratio < 0,50 của biểu).
   Biểu đầy đủ ba bậc để ở P6 — ĐỪNG cài biểu ở đây.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) Aho–Corasick khớp chuỗi con sẽ bắt "viêm" trong "viêm phổi" và sinh span lồng nhau.
    Gold có 0/7.435 span lồng nhau ⇒ phải chọn khớp DÀI NHẤT tại mỗi vị trí.
(b) Gazetteer khớp trên .normalized nhưng offset phải trả về trên .raw. Luôn to_raw().
(c) Dấu phẩy thập phân: `Chol: 4,7 mmol/l` — nếu tách theo `,` thì `4` và `7 mmol/l`
    thành hai entity rác.
(d) ĐỪNG cố nâng precision ở phase này bằng cách bỏ span. Nhiệm vụ của bạn là SÀN recall;
    lọc là việc của decision/ ở P6.

## TIÊU CHÍ NGHIỆM THU — báo từng dòng kèm số thực tế
[ ] recall 2 loại xét nghiệm ≥ 0,70 và precision ≥ 0,80 (đo bằng eval/scoring.py)
[ ] recall span một mình của aho.py ≥ 0,30
[ ] điểm gold penalised/greedy_iou ≥ 14,5
[ ] chạy hết 100 file test dưới 1 PHÚT, KHÔNG GPU, không tải checkpoint nào
[ ] zip qua 4 kiểm tra ĐƯỜNG LÙI: (i) đúng 100 file; (ii) mọi position thoả
    raw[s:e] == text trên chuỗi GỐC; (iii) ràng buộc lược đồ; (iv) NFC/NFD round-trip
[ ] IN mật độ entity/file — nó là đầu vào của emit_threshold ở P6
[ ] 0 span lồng nhau trong output

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
extract/{aho,labvalues,kvspan}.py · resources/lab_patterns.yaml · decision/emit.py ·
data/artifacts/ (gazetteer)
KHÔNG đụng: io/ · layout/ · validate/ (P0 sở hữu)

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Báo 7 ô nghiệm thu kèm số, ba cột alignment, mật độ entity/file, và tỷ lệ
spurious/missing RIÊNG BIỆT. DỪNG, chờ xác nhận.
⚠ Nếu điểm gold < 14,5: ĐỪNG bắt đầu P2 hay P3. Báo cáo và chờ — cổng này cứng.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`kb-linker`** — cho `extract/aho.py` và chỉ mục gazetteer (nó sở hữu hai nhánh chuẩn hoá VN→ICD-10 và EN→RxNorm, và sẽ dùng lại đúng chỉ mục đó ở P5).
- **`span-eval`** — đo recall 2 loại xét nghiệm và mật độ entity/file. Read-only, không đụng vào pipeline của bạn.

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
