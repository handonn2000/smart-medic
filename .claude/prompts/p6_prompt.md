# P6 · LỚP QUYẾT ĐỊNH & HIỆU CHUẨN

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
Bạn làm PHASE P6 — LỚP QUYẾT ĐỊNH & HIỆU CHUẨN.
NHẮM: +2 đến +10 điểm. ~300 dòng, KHÔNG TRAIN GÌ, và cộng dồn với MỌI phase khác.
Đây là phase rẻ nhất trên mỗi điểm mua được trong cả dự án.

## KIỂM TIỀN ĐỀ — tiền đề của phase này là KIẾN TRÚC, không phải lịch
1. ⚠ P3 trả về type_dist + score (PHÂN PHỐI), không phải nhãn đã cắt ngưỡng.
   Nếu extract/ đã áp ngưỡng cứng ở trong nó thì phase này KHÔNG LÀM ĐƯỢC GÌ.
   Kiểm: `grep -rn "0\.[0-9]" src/smart_medic/extract/` không ra ngưỡng phát span nào.
   Nếu ra ⇒ BÁO CÁO, và đề xuất chuyển ngưỡng đó sang decision/ trước khi làm tiếp.
2. Ít nhất một trong P4/P5 trả về phân phối (dist8 hoặc list[Cand] có điểm).
3. Mật độ entity/file được in trên mọi lần chạy — nó là ĐẦU VÀO của emit_threshold.
4. ⚠ CỔNG VÀO: nếu recall đã ≥ 0,86 (bỏ sót < 14%) thì phần recall còn lại đáng dưới
   10,00 điểm ⇒ CHUYỂN GIỜ SANG CANDIDATES, không đẩy recall nữa. Đây là chỗ kết luận
   "recall đứng đầu" chính thức HẾT HIỆU LỰC. BÁO nếu cổng này kích hoạt.

## ĐỌC
- src/smart_medic/decision/README.md — TOÀN BỘ, ba tham số và ba nguồn bằng chứng
- configs/README.md — khung pipeline.yaml
- docs/reports/plan-v4.html tab 03 §D.2 (kiểm "recall bằng mọi giá") và tab 04 → P6

## VIỆC
1. decision/emit.py — THAY hằng số bằng BIỂU NGƯỠNG THEO MẬT ĐỘ.
   Tỷ giá biên c_fn/c_fp ≈ 1,13 cho ngưỡng Bayes p* = 0,469 — nhưng con số đó đo tại BIÊN
   GẦN TRẦN. Ở chế độ vận hành thật, một entity được cứu mang theo cả điểm assertions và
   candidates của nó, nên hoà vốn DỊCH:
       nền bỏ 10% → hoà vốn ≈ 0,44    nền bỏ 30% → ≈ 0,38    nền bỏ 60% → ≈ 0,23
   emit_threshold:
     - {density_ratio: "<0.50",     p: 0.25}
     - {density_ratio: "0.50-0.80", p: 0.38}
     - {density_ratio: ">0.80",     p: 0.45}
   density_ratio = (entity/file của CHÍNH lần chạy đó) / 45,9.
   ⚠ Đây KHÔNG phải "recall bằng mọi giá". Kiểm chứng trực tiếp:
       bỏ 30% thuần            = 49,00
       bỏ 30% + thêm 30% rác   = 42,57   ⇒ cổng ở 0 SAI ở MỌI chế độ
       bỏ 30% + thêm 20% rác   = 44,49
       bỏ 40% thuần            = 42,08   ⇒ nhưng 44,49 > 42,08: hạ ngưỡng để cứu 10%
                                            recall với giá 20% rác THẮNG +2,41
2. decision/select.py
   - assertions: argmax KỲ VỌNG JACCARD trên 8 tập con (64 phép/entity). Metric là
     Jaccard ⇒ tối đa hoá kỳ vọng Jaccard, không phải likelihood.
   - candidates: LUẬT, không ngưỡng học được.
     CHẨN_ĐOÁN: p_d = 0,0000 trên 1.456 mention ⇒ LUÔN đúng 1 mã, KHÔNG cần ngưỡng gap.
     THUỐC: đa mã KHI VÀ CHỈ KHI consists_of nói thuốc phối hợp.
     q0 = 0,0521 CĐ / 0,0588 THUỐC ⇒ GẦN NHƯ KHÔNG BAO GIỜ bỏ trống. Ngoại lệ duy nhất:
     thuốc ***** không suy được tên.
3. decision/calibrate.py — Platt trên [top1, gap top1−top2, entropy, type].
   Platt (2 tham số) > isotonic khi dưới ~300 mẫu, và ta có 162 tài liệu.
   Nếu hiệu chuẩn làm điểm TỤT ⇒ BỎ nó, dùng điểm thô. Một lớp giải mã mới là RỦI RO THUẦN.
4. extract/harmonize.py — GIỮ dù nội bộ đo thấy nó "miễn phí".
   CHỈ cặp THUỐC ↔ TÊN_XÉT_NGHIỆM, đa số ≥4 VÀ tỷ lệ ≥4.
   Với CHẨN_ĐOÁN ↔ TRIỆU_CHỨNG: KHÔNG HÀI HOÀ. 61/64 xung đột là cặp này, và trong gold
   đây là phân biệt HỢP LỆ THEO VỊ TRÍ ("đau ngực" ở mục lý do đến khám là TRIỆU_CHỨNG,
   ở mục chẩn đoán là CHẨN_ĐOÁN). Hài hoà cặp này là XOÁ THÔNG TIN THẬT.
   Thay vào đó: đưa section(offset) từ layout/ vào làm ĐẶC TRƯNG cho đầu type.
   Chi phí đo được của hài hoà: vô điều kiện −0,00 (greedy) / −1,13 (overlap_type);
   với ngưỡng ≥3 → −0,10; với ngưỡng ≥4 → 0,00 ở cả hai.
5. Tìm MODE LỆCH BIÊN CÓ HỆ THỐNG trong diagnostics()["boundary_errors"] (7 kiểu).
   Một mode `+2 right-extended` là MỘT DÒNG CODE và là điểm rẻ nhất còn lại trên bàn.
   Biên lấy TRUNG VỊ có trọng số, không phải trung bình (chi phí WER là L1).

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) HEDGING TYPE. Phát cả hai type khi mơ hồ tốn 1,29 điểm dưới CẢ HAI chế độ căn chỉnh —
    nó tự tạo span thừa, và cổng overlap_type không cứu được vì span thừa vẫn bị phạt.
    Type PHẢI là argmax, KHÔNG BAO GIỜ là tập. Viết test khẳng định 0 position trùng nhau.
(b) MAGIC NUMBER. Mọi ngưỡng ở configs/pipeline.yaml. Nếu bạn viết một số thập phân vào
    file .py trong decision/, đó là bug — kể cả khi nó đúng.
(c) DÙNG MỘT NGƯỠNG CỐ ĐỊNH CHO MỌI CHẾ ĐỘ. Hoà vốn dịch từ 0,23 tới 0,44. Chọn 0,44 khi
    đang mất 60% entity bỏ mất ~9,8 điểm.
(d) LÁCH METRIC. Cải thiện `matched` mà `penalised` không nhúc nhích = lách metric.
    Tái lập được: xoá 30% dự đoán của chính mình làm matched TĂNG nhẹ (70,00→69,96) còn
    penalised rơi 70,00→49,29. Nếu bạn thấy dấu hiệu này, NÓI THẲNG RA.
(e) ĐỪNG THÊM TÍNH NĂNG. P6 là nơi hội tụ, không phải nơi mở rộng.

## TIÊU CHÍ NGHIỆM THU
[ ] mọi delta vượt bar Δ > max(0,010 ; 1,96·SE_bootstrap), CI95 không chứa 0.
    Dưới bar: viết "DƯỚI SÀN NHIỄU", KHÔNG viết "cải thiện nhỏ"
[ ] grep -rn trong decision/ không ra ngưỡng số nào
[ ] mật độ entity/file được in, và ngưỡng dùng KHỚP nhánh biểu tương ứng
[ ] tỷ lệ trả rỗng ≤ 0,06 ngoài ca *****
[ ] 0 position trùng nhau (test khẳng định không hedging)
[ ] xung đột type sau hài hoà ≤ 0,31%; overlap_type KHÔNG giảm
[ ] báo CẢ BA cách đọc (matched/penalised/docbag) mỗi lần chạy

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
src/smart_medic/decision/ · extract/harmonize.py
⚠ configs/pipeline.yaml do NGƯỜI sở hữu. Cần đổi một ngưỡng thì ĐỀ XUẤT giá trị kèm số
đo được; ĐỪNG tự ghi vào file đó.

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Báo bảng delta của TỪNG thay đổi kèm SE và CI95, ba cột alignment, ba cách đọc, mật độ
entity/file và nhánh ngưỡng đã dùng. Nêu rõ thay đổi nào DƯỚI SÀN NHIỄU. DỪNG.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`span-eval`** — mọi delta ở phase này phải qua bar `Δ > max(0,010 ; 1,96·SE)`; để nó chạy bootstrap và nói thẳng cái nào **dưới sàn nhiễu**.

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
