# P3 · RECALL SPAN — đòn bẩy lớn nhất dự án

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
Bạn làm PHASE P3 — RECALL SPAN. Đây là workstream có đòn bẩy LỚN NHẤT của dự án.
NHẮM: +20 đến +30 điểm. Đưa recall từ ~0,39 lên 0,70 ⇒ +21,7 điểm; lên 0,80 ⇒ +28,7.

## KIỂM TIỀN ĐỀ — phase này có một cổng cứng, kiểm nó trước
1. P0 và P1 xanh: điểm gold ≥ 14,5, zip hợp lệ, làn R chạy được.
2. ⚠ CỔNG: Probe A từ P2 ≥ 25.
   Nếu Probe A < 25 thì mật độ entity trên test KHÁC GOLD CĂN BẢN, toàn bộ định giá
   "recall = ~46 điểm" SAI, và phase này KHÔNG ĐƯỢC bắt đầu theo hình dạng hiện tại.
   BÁO CÁO và DỪNG.
3. Kết quả Probe A′: nếu A′ ≈ 0 thì type đáng 12,35 điểm ⇒ đầu type PHẢI nhận
   section(offset) làm đặc trưng NGAY TỪ LẦN TRAIN ĐẦU, không phải sửa sau.
4. GPU khả dụng cho MỘT lần fine-tune.
Không có kết quả Probe A ⇒ BÁO, DỪNG. Đừng đoán thay nó.

## ĐỌC
- src/smart_medic/extract/README.md — toàn bộ
- docs/reports/plan-v4.html tab 04 → P3, tab 02 §A (hover khối extract/)
- docs/reports/research-directions.html — mục hợp nhất trên đồ thị chồng lấn span
- src/smart_medic/eval/scoring.py — hiểu align() và score_document() TRƯỚC khi viết gì

## KHOẢNG TRỐNG BẠN ĐANG LẤP
data/output/ trích 1.585 entity = 15,8/file. Gold có 45,9/file. Thiếu 2,9×.
Đường cong mất điểm: bỏ 30% −20,72 · 50% −34,96 · 60% −41,92 · 65% −45,53 · 70% −48,95.
Ở vùng recall 0,35–0,40, mỗi ĐIỂM PHẦN TRĂM recall đáng 0,72 điểm leaderboard
(đọc từ đường cong: (45,53 − 41,92) / 5). Lưu ý hệ số 0,5155 của Probe A là thứ KHÁC —
nó chỉ đo số hạng `text`, không đo phần assertions/candidates mà entity đó mang theo.
Không hạng mục nào khác trong dự án ở cùng bậc độ lớn.

## HÌNH DẠNG DỮ LIỆU ĐỂ KHAI THÁC
96% file là danh sách · 97/100 có dòng header "Nhãn:" · span dài trung bình 2,42 từ,
37,8% dài ĐÚNG 1 TỪ, 64,8% ≤2 từ · 0/7.435 gold span lồng nhau.

## VIỆC
1. extract/globalpointer.py — XLM-R-base + Efficient GlobalPointer cho
   TRIỆU_CHỨNG/CHẨN_ĐOÁN/THUỐC (3.337 entity gold).
   - MỨC ÂM TIẾT. return_offsets_mapping=True. W=30.
   - KHÔNG dùng model tokenizer mức -word — nó PHÁ OFFSET.
   - Train trên 162 gold + 543 silver (đã lọc 165 vi phạm ở P0).
   - MỘT model, MỘT lần train, KHÔNG sweep siêu tham số. Ngân sách: một cửa sổ GPU.
   - Ngưỡng đầu ra THÔ 0,15 — chỉ cắt đuôi phân phối. Trả type_dist + score, KHÔNG áp
     ngưỡng thật. Quyết định phát-hay-bỏ là việc của decision/emit.py.
2. extract/overlap_graph.py — hợp nhất làn R và làn M.
   ⚠ BỎ ngưỡng IoU ≥ 0,5. Đo được: nó loại 54,2% biến thể ranh giới, 85,7% với span 1 từ,
     mà 37,8% gold span dài đúng 1 từ.
   - nút = span ứng viên · cạnh khi CHỒNG LẤN KÝ TỰ > 0
   - cụm: Leiden (KHÔNG Louvain). Bản rút gọn nếu hết giờ: union-find (thành phần liên
     thông) — giữ được cái chính, mất phần xử lý cụm chồng chéo nhiều lớp.
   - phiếu token có TRỌNG SỐ trong cụm
   - ràng buộc KHÔNG LỒNG NHAU (hợp lệ: 0/7.435 gold span lồng)
3. extract/boundary.py — biên lấy TRUNG VỊ có trọng số, KHÔNG phải trung bình.
   Chi phí WER là khoảng cách L1 ⇒ ước lượng tối ưu là trung vị. Một dòng code, và là
   loại lỗi không ai phát hiện bằng mắt.
4. boundary_priors từ layout/ nối vào CẢ HAI làn — nó chặn VỀ MẶT CẤU TRÚC việc `- ` hay
   `Chẩn đoán: ` lọt vào span, tức 6,95 điểm rẻ nhất trong bài.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) SINH THỪA. Đường cong đo được: +10% span thừa −6,10 · +20% −11,25 · +30% −15,61.
    Tỷ giá c_fn/c_fp ≈ 1,13 ⇒ KHÔNG phải "recall bằng mọi giá": bỏ 30% + thêm 30% rác
    = 42,57, THẤP HƠN bỏ 30% thuần (49,00) tới 6,43 điểm.
    Nhưng cũng đừng kiềm chế quá: bỏ 30% + thêm 20% rác = 44,49 > bỏ 40% thuần = 42,08.
(b) RANH GIỚI. Cắt 1 từ cuối mọi span mất 6,95 dưới greedy_iou nhưng 54,69 dưới `exact`.
    Nếu cột exact sụt về gần 0 mà hai cột kia bình thường ⇒ BUG OFFSET, DỪNG LẠI,
    đừng coi là khoảng trống mô hình.
(c) TYPE. greedy_iou không so type, nên số chính thức sẽ KHÔNG phạt bạn khi gán sai type.
    Dưới overlap_type, sai 10% mất 12,35 (sd ±0,82). Đo bằng CỘT CHẶN, đừng tin số chính.
(d) NFC. 41/162 gold và 20/100 test không ở NFC. Một lần normalize sai chỗ là mất cả phase.
(e) ĐỪNG dùng LLM sinh làm bộ trích xuất span chính — đã loại, encoder 209M thắng nó và
    cho offset chính xác theo cấu tạo.
(f) ĐỪNG làm semi-CRF hay boundary smoothing ở phase này. Chúng nhắm vào 6,95 điểm ranh
    giới trong khi khoảng trống là ~46 điểm recall. HOÃN có ghi chép.

## TIÊU CHÍ NGHIỆM THU — báo từng dòng kèm số thực tế
[ ] pytest tests/test_offsets.py -q SẠCH; text == raw[start:end] byte-exact 100/100 file
[ ] recall span trên gold ≥ 0,70 (đo bằng scoring.py, KHÔNG bằng cảm nhận)
[ ] recall 2 loại xét nghiệm ≥ 0,70 — KHÔNG ĐƯỢC TỤT so với P1
[ ] penalised/greedy_iou tăng ≥ +15,00 so với baseline data/output/
[ ] overlap_type KHÔNG giảm quá 0,010 so với baseline (test_alignment_parity thi hành)
[ ] span thừa ≤ 20%; báo tỷ lệ spurious và missing RIÊNG BIỆT
[ ] bảng lát cắt thể loại × type KÈM n; không lát nào (n ≥ 30 tài liệu) tụt
[ ] cột exact không sụt về gần 0
[ ] mọi delta vượt bar: Δ > max(0,010 ; 1,96·SE), CI95 không chứa 0
[ ] số cụm sau merge KHÔNG lớn hơn số span thật (dấu hiệu phân mảnh ⇒ hạ về union-find)

## CỔNG DỰ PHÒNG — kích hoạt thì BÁO, đừng tự quyết
- recall < 0,45 ⇒ BỎ HẲN nhánh model span. Giữ làn R; dồn giờ sang P4/P5.
  Mô phỏng: r0,50 sp0,20 → 21,6; kèm assertions + mã → ~35.
- span thừa > 30% ⇒ nâng ngưỡng lên 0,60, bỏ ensemble. KIỂM TỶ LỆ TRƯỚC: cắt thừa chỉ
  hoàn vốn nếu đổi được ≥1,2% thừa cho mỗi 1% recall mất.
- Model không hội tụ trong MỘT lần train ⇒ KHÔNG train lần hai. Báo cáo.

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
extract/{globalpointer,gliner,overlap_graph,boundary}.py · scripts/train_span.py
KHÔNG đụng: io/ · layout/ · validate/ · extract/{aho,labvalues,kvspan}.py (P1 sở hữu) ·
configs/*.yaml (NGƯỜI sở hữu — cần đổi ngưỡng thì BÁO)

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau khi bộ trích xuất chạy hết 100 file test: báo recall đo được, ba cột alignment, bảng
lát cắt, đường cong sinh thừa của chính bạn, và mật độ entity/file.
DỪNG, chờ xác nhận TRƯỚC khi tinh chỉnh ngưỡng — ngưỡng là việc của P6.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`span-eval`** — sau mỗi lần chạy: recall, ba cột alignment, bảng lát cắt kèm `n`, đường cong sinh thừa. Nó read-only nên chạy song song với lúc bạn đang sửa code.

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
