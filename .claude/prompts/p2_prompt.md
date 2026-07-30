# P2 · HIỆU CHUẨN HỘP ĐEN — 3 probe + hạ tầng đo

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
Bạn làm PHASE P2 — HIỆU CHUẨN HỘP ĐEN.
NHẮM: 0 điểm trực tiếp. Nhưng phase này quyết định ~46 điểm được đầu tư vào đâu.
Đây là phase có tỷ lệ giá-trị / công-sức cao nhất trong dự án.

## KIỂM TIỀN ĐỀ
1. `python3 scripts/submit/package_submission.py` sinh được output.zip hợp lệ (P0 xong).
2. Tồn tại MỘT tập dự đoán bất kỳ. data/output/ (100 file, offset sạch 100/100) LÀ ĐỦ.
   ⚠ KHÔNG cần P3. KHÔNG cần extractor tốt. Đừng đợi.
3. Còn ≥3 lần nộp leaderboard trong ngày (3 probe dùng 3/5, để lại 2 cho sự cố định dạng).
Thiếu (1) ⇒ BÁO, DỪNG. Thiếu (3) ⇒ dựng probe hôm nay, nộp mai.

## ĐỌC
- src/smart_medic/eval/README.md — API thật của scoring.py
- docs/reports/plan-v4.html tab 05 (toàn bộ) — đặc biệt §D bảng câu hỏi → probe → delta
- docs/decisions/0001-drug-tty.md (BẢN 3 — tạm chốt IN) và 0002-metric-reading.md

## VÌ SAO PHASE NÀY ĐỨNG TRƯỚC P3
Toàn bộ định giá "recall = ~46 điểm" đo trên gold `restyled/` — corpus TỔNG HỢP hai thế hệ,
retention chuỗi bề mặt 63,5%. Tập test là văn bản THẬT. Nếu mật độ entity trên test khác
gold căn bản thì thứ tự ưu tiên của cả dự án sai, và cách duy nhất để biết là NỘP.
Chạy sớm thì Probe A là CỔNG cho P3. Chạy muộn thì nó chỉ là báo cáo về một quyết định
đã lỡ thực hiện.

## VIỆC
1. eval/probe.py — sinh biến thể probe từ MỘT tập dự đoán:
   A  = span + type, assertions=[] và candidates=[] TOÀN BỘ
   A′ = A nhưng ĐẢO type toàn bộ, span Y NGUYÊN
   B  = A + mã mức IN cho THUỐC (khớp chuỗi chính xác)
   C  = A + assertions từ luật (chỉ nếu P4 đã có luật)
2. eval/slices.py — bảng lát cắt KÈM n VÀ MDE:
   thể loại × loại entity × NFC/không × có *****/không.
   Số tài liệu: dan_y 94 · van_xuoi 27 · xuong_dong 17 · pho_bien 12 · hoi_dap 12.
   NFC 121 / không-NFC 41. Sạch 109 / có ***** 53.
   ⚠ pho_bien và hoi_dap chỉ 12 tài liệu. Ở n=30, MDE đã là 0,238 điểm ⇒ các lát này
     KHÔNG phân giải được sàn 0,010. In n cạnh mỗi lát; lát nào MDE > delta thì gạch chân.
3. eval/bootstrap.py — paired bootstrap B=10.000, resample THEO TÀI LIỆU, ghép cặp trên
   cùng tập tài liệu. Trả Δ, SE, CI95, MDE=1,96·SE.
4. tests/test_alignment_parity.py — FAIL khi greedy_iou tăng mà overlap_type giảm > 0,010.
   Kiểm nó THỰC SỰ CHẶN bằng một thay đổi giả biết trước là xấu.
5. NỘP theo đúng thứ tự A → A′ → B. Mỗi lần MỘT biến. Ghi câu hỏi và delta KỲ VỌNG vào
   runs/ TRƯỚC KHI nộp.
6. Cập nhật ADR (đây là việc của phase này, đừng để trôi):
   - 0002-metric-reading.md: thêm mục "Cập nhật 30/07/2026" — trần 70,00/candidates 10,00
     (162 file) thay 69,16/9,16 (98 file); và điều khoản SỐ CHÍNH THỨC LÀ MỘT CẶP
     (penalised/greedy_iou, penalised/overlap_type) + CI fail khi cột hai giảm > 0,010.
     KHÔNG sửa tại chỗ phần thân ADR — ADR là bản ghi lịch sử.
   - 0001-drug-tty.md: ghi kết quả ΔB, chốt hoặc giữ treo.

## CÁCH ĐỌC BA DELTA — đây là toàn bộ giá trị của phase
Probe A  → recall thật trên test = A / 51,55
           A≈20 ⇒ recall 0,39 ⇒ đang mất ~43 điểm.  A≈36 ⇒ recall 0,70.
           ⚠ A < 25 ⇒ MẬT ĐỘ TEST KHÁC GOLD CĂN BẢN. Dừng đầu tư recall. Đo lại toàn bộ
             bản đồ đòn bẩy trên output test. BÁO NGAY — đây là rẽ nhánh của cả dự án.
Probe A′ → A′ ≈ A  ⇒ BTC dùng greedy_iou, type MIỄN PHÍ
           A′ ≈ 0  ⇒ overlap_type/exact, type đáng 12,35 điểm ở mức sai 10%
           Không có mức giữa. Nội bộ: A′−A = 0,00 (greedy) vs −20,19…−51,81 (overlap_type)
Probe B  → ΔB ≈ +3,9 ⇒ IN đúng, chốt ADR 0001
           ΔB ≈ 0 hoặc âm ⇒ BTC chấm ở SCD, bật target_tty=SCD
           ΔB mơ hồ (< 0,3) ⇒ GIỮ IN VÀ ĐI TIẾP. ĐỪNG nộp probe thứ hai cho câu này —
           trần ảnh hưởng chỉ ~1,1 điểm (18,6% span thuốc có hàm lượng)
           Đồng thời đọc c_i: ΔC_thật = (B − A) / recall_est. ≈10,0 ⇒ đếm mọi entity đã
           ghép (như scorer nội bộ). Cao hơn rõ ⇒ mở lại ADR 0002.

## BA LUẬT CHI TIÊU LẦN NỘP
1. KHÔNG BAO GIỜ nộp hai probe khác nhau ở HAI biến — delta sẽ không đọc được.
2. KHÔNG nộp để xác nhận điều nội bộ đã cho thấy chắc chắn. Nộp để giải cái nội bộ
   KHÔNG ĐO ĐƯỢC: ba hộp đen căn chỉnh, c_i, mật độ entity thật.
3. Nộp bài LUÔN là quyết định của CON NGƯỜI. Bạn chuẩn bị zip và bảng delta kỳ vọng;
   BẠN KHÔNG BẤM NỘP.

## TIÊU CHÍ NGHIỆM THU
[ ] Ba zip probe hợp lệ (A, A′, B), mỗi cái qua 4 kiểm tra đóng gói
[ ] Bảng "câu hỏi → delta kỳ vọng → cách đọc" cho cả ba, ghi vào runs/ TRƯỚC khi nộp
[ ] test_alignment_parity.py xanh VÀ đã chứng minh nó chặn được một thay đổi xấu giả
[ ] Bảng lát cắt in n và MDE; lát nào MDE > 0,010 được gạch chân
[ ] bootstrap tái lập được 4 ca hiệu chuẩn: isFamily Δ=−0,261 SE=0,052 · sai 30% mã
    Δ=−2,856 SE=0,123 · bỏ 10% entity Δ=−7,043 SE=0,287 · seedA vs seedB SE=0,415
[ ] Hai ADR đã cập nhật

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
eval/{probe,slices,bootstrap}.py · tests/test_alignment_parity.py · runs/ ·
docs/decisions/000{1,2}-*.md (chỉ THÊM mục cập nhật, không sửa thân)
KHÔNG đụng: eval/scoring.py (đã xong, 8 self-test) · bất kỳ layer nào của pipeline

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau khi ba zip sẵn sàng: báo bảng delta kỳ vọng và DỪNG — chờ người bấm nộp.
Sau khi có kết quả: báo ba delta thật, recall suy ra, và khuyến nghị P3 có khởi động
được hay không. DỪNG, chờ xác nhận.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`probe-builder`** — dựng và kiểm ba biến thể A / A′ / B. Nó có sẵn checklist 7 mục trước khi bàn giao một build, và **không bao giờ tự nộp** — đúng kỷ luật "con người bấm nộp" của phase này.
- **`span-eval`** — bảng lát cắt, paired bootstrap, đọc delta. Read-only.

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
