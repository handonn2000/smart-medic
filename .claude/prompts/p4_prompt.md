# P4 · ASSERTIONS — đồ thị phạm vi

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
Bạn làm PHASE P4 — ASSERTIONS.
NHẮM: 7,92 điểm (isNegated 3,98 + isHistorical 3,94) trong 8,19 của cả nhánh.

## KIỂM TIỀN ĐỀ — tiền đề của phase này là ĐỊNH LƯỢNG
1. ⚠ P3 với recall span ≥ 0,65. Đây KHÔNG phải hình thức: 8,19 điểm assertions chỉ được
   tính trên entity ĐÃ KHỚP. Chạy phase này trên nền recall 0,40 thì trần thật của nó chỉ
   còn ~3,3 điểm — và mọi F1 bạn đo được sẽ KHÔNG dự báo được điểm.
   recall < 0,65 ⇒ BÁO CÁO và DỪNG.
2. layout/outline.py trả được section(offset). Đồ thị phạm vi ĐỌC nó, không tự phân tích
   lại cấu trúc tài liệu.
3. Nếu P2 đã nộp Probe C: ΔC ≥ +4. ΔC < +4 ⇒ cắt phạm vi phức tạp, làm bản luật tối
   giản rồi dồn giờ sang recall. BÁO.

## ĐỌC
- src/smart_medic/assertion/README.md — TOÀN BỘ, đặc biệt "Bất biến quan trọng nhất"
- resources/README.md — khung cues_vi.yaml, 5 nhóm
- docs/reports/graph-llm-annotation.html — mục Document Scope Graph
- docs/reports/plan-v4.html tab 04 → P4

## NGÂN SÁCH ĐIỂM — plan v3 ước lượng SAI, đọc kỹ
assertions rỗng hết mất 8,19 điểm, KHÔNG phải 13,3. Plan v3 lấy baseline 0,507 (đo trên
3 type MANG assertion) rồi nhân toàn bộ trọng số 0,3. Nhưng 2 loại xét nghiệm LUÔN rỗng
nên được Jaccard = 1 MIỄN PHÍ, kéo assertions_score toàn cục lên 0,7271.
Phân rã đo được: isNegated 3,98 · isHistorical 3,94 · isFamily 0,26.
⇒ NHẮM 7,92. ĐỪNG ĐẦU TƯ VÀO isFamily — 0,26 điểm ở tần suất gold 1,1%.

## PHÂN BỐ GOLD (4.337 entity thuộc 3 type mang assertion)
rỗng 50,7% · isNegated 24,1% · isHistorical 22,5% · cả hai 1,2% · isFamily 1,1%.

## VIỆC
1. resources/cues_vi.yaml + sections_vi.yaml — luật cue dạng YAML, KHÔNG Python.
   Chúng sẽ chỉnh HÀNG CHỤC LẦN và cần review được bởi người không đọc code.
   Năm nhóm: negation · family · historical · HYPOTHETICAL · terminators.
   Mọi cue có `window` và `direction` TƯỜNG MINH. Không cue nào "phủ cả câu" mặc định.
2. assertion/scope_graph.py — CẤU TRÚC DỮ LIỆU giữ đồ thị.
   Cạnh SECTION_SCOPE và NEGATION_SCOPE dạng 1→n: MỘT cue phủ n concept.
   46/100 file test có liệt kê ngay sau "không"; 45,4% entity isNegated CHIA SẺ CUE.
   Đây là lý do một bộ phân loại chạy độc lập trên từng entity có trần thấp THEO CẤU TẠO.
   features(span) trả VECTOR TRỌNG SỐ, không phải nhãn.
3. assertion/{context,scope}.py — bộ SINH cạnh (cue→cửa sổ→kết thúc; mục→concept trong mục).
4. assertion/veto.py — bộ XOÁ cạnh. Ngữ cảnh giả định (`có thể`, `nếu`, `nghi ngờ`) ở
   75/100 FILE, và nó KHÔNG phải một trong ba nhãn ⇒ assertions phải RỖNG.
   Cổng thể loại theo ĐƠN VỊ LAYOUT, không theo tài liệu (42.txt chèn câu hỏi forum vào
   giữa dàn ý lâm sàng — một cờ thể loại cho cả file sẽ sai ở nửa file).
5. PHẠM VI RIÊNG TỪNG CỜ — đo được: phạm vi theo cấu trúc giúp isNegated (+0,07 F1) nhưng
   HẠI isHistorical (−0,08). Đừng dùng một chính sách cho cả ba cờ.
6. assertion/decode.py — softmax 8 CHIỀU trên tập con. 3 sigmoid độc lập KHÔNG biểu diễn
   được tương quan {isNegated, isHistorical} (1,2% gold mang cả hai).
   Giải mã bằng ARGMAX KỲ VỌNG JACCARD trên 8 tập con (64 phép/entity) — metric là
   Jaccard nên tối đa hoá kỳ vọng Jaccard, KHÔNG phải likelihood.
7. tests/fixtures/ — CONTRAST SET ~80 cặp lật assertion bằng sửa TỐI THIỂU.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) ĐỪNG BIẾN ĐẶC TRƯNG THÀNH LUẬT QUYẾT ĐỊNH. Span trong mục tiền sử/gia đình có
    isHistorical ở 42,1% so với 21,2% nơi khác (nâng 1,99×) — NHƯNG 55,2% span trong mục
    đó VẪN KHÔNG mang cờ. Đo trực tiếp, mốc "bỏ hẳn isHistorical" = 66,06:
        luật cứng R=0,421 P=0,448 (đúng như đo)  → 65,86  ⇒ ÂM 0,21 điểm
        luật cứng R=0,421 P=0,55                 → 66,48  ⇒ +0,41
        luật cứng R=0,90  P=0,70                 → 68,08  ⇒ +2,01
    ĐIỂM HOÀ VỐN LÀ P ≈ 0,50 BẤT KỂ R. Luật mục thuần có P = 0,448 ⇒ âm.
    ⇒ ĐO P CỦA MỌI BỘ SINH CẠNH TRƯỚC KHI BẬT NÓ. Ghi số vào báo cáo.
(b) SCHEMA. assertions PHẢI RỖNG với TÊN_XÉT_NGHIỆM và KẾT_QUẢ_XÉT_NGHIỆM. Silver có
    165 vi phạm CHÍNH CHỖ NÀY. Nếu bạn học từ silver, bạn sẽ học cả lỗi này —
    io/corpus.py đã lọc lúc nạp ở P0, đừng vô hiệu hoá bộ lọc đó.
(c) fp ≫ fn nghĩa là luật đang cháy trên ngữ cảnh giả định hoặc giáo dục bệnh nhân, không
    phải trên phủ định thật. Đọc diagnostics()["assertions"] tp/fp/fn TỪNG CỜ.
    SIẾT veto.py, ĐỪNG chỉnh model.
(d) ĐỪNG dùng constrained decoding để ép định dạng assertions — đã loại, ép định dạng làm
    giảm năng lực suy luận.
(e) ĐỪNG ép nhất quán assertions theo tài liệu (3,98% xung đột là THẬT). Chỉ ép type và mã.

## TIÊU CHÍ NGHIỆM THU
[ ] assertions_score ≥ 0,90 toàn cục (rỗng hết = 0,7271; hoàn hảo = 1,0000)
[ ] F1 isNegated và isHistorical báo RIÊNG, kèm tp/fp/fn từ diagnostics()
[ ] 0 vi phạm lược đồ: không entity xét nghiệm nào mang assertions
[ ] contrast set ~80 cặp: nhất quán ≥ 0,95. Dưới 0,95 là BUG, không phải khoảng trống
    mô hình. Đây là cách DUY NHẤT kiểm được isFamily ở tần suất 1,1%
[ ] P của TỪNG bộ sinh cạnh được đo và GHI LẠI trước khi bật — không bật cái nào có P < 0,50
[ ] overlap_type không giảm quá 0,010
[ ] fp không ≫ fn

## CỔNG DỰ PHÒNG
- Chưa xong hoặc ΔC < +4 ⇒ trả assertions=[] TOÀN BỘ. Mất 8,19 nhưng KHÔNG BAO GIỜ HỎNG.
  Mô phỏng r0,85 sp0,12 → 47,1.
- KHÔNG mở rộng sang isFamily trong mọi trường hợp. Giữ 3 dòng cue và dừng.

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
src/smart_medic/assertion/ · resources/{cues_vi,sections_vi}.yaml · tests/fixtures/
KHÔNG đụng: extract/ · linking/ · decision/ · configs/*.yaml

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau khi luật cue chạy và đo được trên gold: báo assertions_score, F1 hai cờ chính,
tp/fp/fn, P của từng bộ sinh cạnh, và kết quả contrast set.
DỪNG, chờ xác nhận trước khi mở rộng sang isFamily (gần như chắc chắn tôi sẽ nói không).

## CẬP NHẬT TIẾN ĐỘ TRONG PLAN — CHỈ SAU KHI USER XÁC NHẬN
Điều kiện kích hoạt DUY NHẤT: user nói rõ P4 đã xong / đã duyệt. Bạn vừa báo cáo
xong mà user chưa trả lời ⇒ CHƯA được sửa gì. Tự tick là làm bảng mất giá trị.

NGOẠI LỆ SỞ HỮU FILE: khi và chỉ khi điều kiện trên thoả, bạn được ghi vào
`docs/reports/plan-v4.html`, GIỚI HẠN ở các ô trạng thái. KHÔNG sửa số liệu, KHÔNG
sửa bảng đòn bẩy, KHÔNG sửa văn bản phân tích — đổi một con số trong plan là việc
khác hẳn và phải hỏi riêng.

1. Danh sách việc lấy bằng MỘT lệnh — dò theo tag phase, ĐỪNG dùng số dòng (số dòng
   trôi sau mỗi lần sửa plan):
       grep -nE '(class="c">|<td>)(⬜|⚠) (P[0-9] · )*P4( |<)' docs/reports/plan-v4.html
   Neo vào `class="c"`/`<td>` để KHÔNG bắt văn xuôi tiền đề trong tab 07.
   `grep '⬜ P4'` trần thì BỎ SÓT marker đa phase — ví dụ thật: dòng `extract/`
   mang `⬜ P1 · P3 · P5`.
2. Đổi marker theo trạng thái THẬT, ba mức:
     ✅  chạy được VÀ có số đo chứng minh
     ⚠   cơ chế có nhưng số liệu/độ phủ còn thiếu — ghi rõ thiếu gì, ngay trong ô đó
     ⬜  chưa làm
   Đạt một phần thì ghi ⚠ kèm con số thực tế. KHÔNG làm tròn lên thành ✅.
3. Hai bảng trạng thái khác phải khớp theo:
     tab 02 §D "Chế độ hỏng & phòng thủ" — cột "Đã có?"
     tab 04 bảng runbook 8 ô — cột "Trạng thái hôm nay" (pill nào P4 vừa mở khoá)
4. File mới sinh trong phase ⇒ thêm vào cây thư mục tab 01 §B. Cây là một khối `<pre>`
   căn bằng khoảng trắng, và căn lề KHÔNG đều: dòng file ở cột 36, dòng thư mục ở cột
   35, vài tên dài tràn 37–38. ĐỪNG tin con số — COPY căn lề của dòng anh em ngay trên.
5. Tab 08 Checklist lưu ở localStorage của TRÌNH DUYỆT, không có gì trong file để sửa.
   BẢO USER tự tick P4-1…P4-6. ĐỪNG báo là đã tick hộ.
6. Commit RIÊNG, đừng trộn với code: `docs: mark P4 progress in plan-v4`.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`span-eval`** — `diagnostics()["assertions"]` tp/fp/fn từng cờ, và ma trận nhầm lẫn. Đây là cách duy nhất thấy được "fp ≫ fn" để biết phải siết `veto.py` thay vì chỉnh model.

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
