# P5 · CANDIDATES + TẦNG KIỂM CHỨNG CẠNH

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
Bạn làm PHASE P5 — CANDIDATES + TẦNG KIỂM CHỨNG CẠNH.
NHẮM: 1,0–3,0 điểm. NGÂN SÁCH THỜI GIAN: ≤ 1,5 NGÀY-NGƯỜI. Đọc mục dưới trước khi làm gì.

## ĐỌC TRƯỚC KHI LÀM BẤT CỨ VIỆC GÌ — ngân sách điểm của phase này
Toàn bộ nhánh candidates đáng 10,00 điểm trong trần 70,00, và cận trên của việc CẢI THIỆN
nó hẹp hơn nhiều — đo bằng scorer thật trên 162 gold:
    sai 10% mã −0,96 · 20% −1,96 · 30% −2,96 · 50% −4,98 · sai hết −10,00
⇒ Đi từ 30% mã sai xuống 10% mã sai chỉ đáng 2,00 ĐIỂM.
So sánh: ở vùng recall hiện tại, mỗi điểm phần trăm recall span đáng 0,72 điểm — tức toàn bộ
phần cải thiện được của phase này bằng CHƯA TỚI 3 điểm phần trăm recall.
NẾU BẠN THẤY MÌNH SẮP TIÊU HƠN 1,5 NGÀY-NGƯỜI, DỪNG LẠI VÀ BÁO CÁO.
Trọng số danh nghĩa 0,4 là CÁI BẪY LỚN NHẤT của đề bài này.
(Graph-walk bundle sampler đã BỊ HẠ CẤP đúng vì lý do này — đừng đề xuất lại.)

## KIỂM TIỀN ĐỀ
1. P3 có đầu ra span CHẨN_ĐOÁN/THUỐC. Không cần recall cao như P4 — mã tính trên entity
   đã khớp, nên P5 chạy SONG SONG P4 được.
2. Kết quả Probe B từ P2. Nếu vẫn treo thì target_tty vẫn là THAM SỐ và ĐỪNG tinh chỉnh
   ngưỡng nhánh thuốc.
3. ls data/knowledge_base/ (PHẲNG) có RXNCONSO · RXNREL · RXNSTY · RXNATOMARCHIVE ·
   ICD10.csv · icd10cm-codes-2027.txt. Thiếu RXNATOMARCHIVE ⇒ mất chế độ "mã đã rút"
   (360047 CHỈ tồn tại ở đó). Đọc qua scripts/kb_sources.py, ĐỪNG hard-code đường dẫn.
   ⚠ ICD10.csv là bảng TIẾNG VIỆT của ban tổ chức (13.189 mã · 36.689 tên, 99,6% có dấu).
     icd10cm-codes-2027.txt là ICD-10-CM TIẾNG ANH của Mỹ và CHỈ chứa 41,4% số mã đó —
     nó là nguồn LÀM GIÀU theo mã, KHÔNG phải bản thay thế. Đừng tra tiếng Việt vào nó.
4. extract/aho.py từ P1 đã ghi chỉ mục gazetteer vào data/artifacts/ — DÙNG LẠI, đừng build lại.

## ĐỌC
- src/smart_medic/linking/README.md — TOÀN BỘ, đặc biệt bảng chi tiết RRF
- docs/decisions/0001-drug-tty.md (BẢN 3 — tạm chốt IN, KHÔNG phải SCD)
- docs/reports/plan-v4.html tab 04 → P5

## NGƯỠNG LỚP QUYẾT ĐỊNH — đo trên GOLD, sắc hơn plan v3
q0 = P(gold rỗng): CHẨN_ĐOÁN 0,0521 · THUỐC 0,0588 · tổng thể 0,0547
  (plan v3 ước 0,209 từ silver — SAI GẤP 4×) ⇒ GẦN NHƯ KHÔNG BAO GIỜ BỎ TRỐNG.
p_d = P(|G| ≥ 2 | có mã): CHẨN_ĐOÁN 0,0000 TUYỆT ĐỐI trên 1.456 mention ⇒ LUÔN trả ĐÚNG
  1 MÃ, KHÔNG cần ngưỡng gap. THUỐC 0,0915 ⇒ gap 0,1007 (chỉ là mốc kiểm).
Cỡ tập: CHẨN_ĐOÁN {0: 5,21%, 1: 94,79%} · THUỐC {0: 5,88%, 1: 85,5%, 2: 8,4%, 3: 0,21%}.
Doublet của THUỐC gần như luôn là THUỐC PHỐI HỢP ⇒ quyết định bằng LUẬT từ KB
(consists_of), KHÔNG bằng ngưỡng xác suất.

## VIỆC
1. linking/icd.py — dense PHẲNG VÉT CẠN 45 MB, một GEMM, <1 ms, recall 100%,
   0 siêu tham số. ĐỪNG XÂY ANN (HNSW/DiskANN/ScaNN) — ở quy mô 14.678 chuỗi nó chỉ thêm
   siêu tham số và mất recall.
   Gazetteer làm giàu: 5.460 nhãn tiếng Anh join theo mã + 302 nhãn khối `Nhóm bệnh`.
   13.189 mã duy nhất; ĐƯỢC PHÉP trả mã 3 ký tự (I48.0 → I48).
2. linking/rxnorm.py — TF-IDF char-ngram cho thuốc (THẮNG DENSE 1,4 ĐIỂM — tên thuốc là
   bài toán chuỗi, không phải bài toán ngữ nghĩa).
   ⚠ LỌC BỎ 1.673.734 cạnh inactive_ingredient_of TRƯỚC KHI nạp RXNREL (nhiễu thuần).
   Cạnh dùng được: tradename_of 118.543 · has_active_moiety 266.440 ·
   has_active_ingredient 288.367 · consists_of 116.818 · isa/inverse_isa 292.028.
   target_tty THAM SỐ HOÁ trong configs/pipeline.yaml — chạy được cả IN lẫn SCD bằng MỘT CỜ.
3. linking/edge_verify.py — 6 luật đọc RRF/CSV, trả vector 6 BIT vi phạm + hành động
   keep / remap→X / lift→IN / drop / abstain.
   Bản rút gọn (nửa ngày) nếu hết giờ — CHỈ 2 luật, và hai luật này cover chế độ hỏng
   "mã đã rút" vốn không sinh được bằng cách khác:
   - remap qua MERGED_TO_RXCUI trong RXNATOMARCHIVE.RRF (373.484 dòng khác rỗng,
     vd 360047 → 2178097). RXNCUI.RRF: 22.330/30.269 dòng remap.
   - LOẠI theo RXNSTY T200.
4. linking/retrieve.py + rerank.py — CombMNZ, KHÔNG DÙNG RRF (RRF vứt bỏ độ lớn điểm).
   LambdaMART chỉ nếu còn thời gian sau khi mọi ô nghiệm thu đã xanh.
5. linking/redaction.py — thuốc bị che `*****` CHỈ CẮT danh sách ứng viên.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) LUẬT WHITELIST SEMANTIC TYPE SẼ LOẠI SAI. Đo được: 220/220 RxCUI gold ở mức IN, và
    218/220 có T109|T121 — nhưng HAI NGOẠI LỆ LÀ THẬT: 9863 sodium chloride (T197) và
    11124 vancomycin (T116/T195). Whitelist T109/T121 LOẠI OAN chúng.
    ⇒ Dùng RXNSTY để LOẠI T200, ĐỪNG whitelist T109/T121.
(b) tty CÒN TREO. ADR 0001 bản 3 tạm chốt IN cho gold annotation; lựa chọn khi nộp chờ
    Probe B. PHẢI tham số hoá. ĐỪNG hard-code. ĐỪNG tinh chỉnh ngưỡng nhánh thuốc trước
    khi Probe B trả lời. Trần ảnh hưởng chỉ ~1,1 điểm (18,6% span thuốc có hàm lượng).
(c) THUỐC BỊ CHE: 30/100 file test có `*****` (99 token). 20/30 có tên hoạt chất lộ rõ ở
    chỗ khác, 9–11/30 khớp đúng độ dài dãy sao — NHƯNG CÓ DƯƠNG TÍNH GIẢ ĐÃ XÁC ĐỊNH:
    1.txt khớp "glucose", 18.txt khớp "lipase", KHÔNG phải thuốc bị che.
    ⇒ CHỈ dùng để CẮT DANH SÁCH ỨNG VIÊN, KHÔNG dùng để quyết định mã. Không suy được
    thì trả rỗng — đây là ngoại lệ DUY NHẤT được bỏ trống.
(d) THÊM MÃ "CHO CHẮC" là miễn phí dưới công thức official (thêm 1/4/9 mã rác = 0,00)
    nhưng đắt dưới `plain`. GIỮ "đúng 1 mã hoặc 0" tới khi Probe B trả lời.
(e) CO NGÓT ĐỆ QUY ĐÃ XẢY RA: retention chuỗi bề mặt translated→restyled chỉ 63,5%;
    mã chẩn đoán 158→136, RxCUI 288→223. Nếu bạn dựng thêm tầng biến đổi dữ liệu, thêm
    thẻ độ phủ và hợp đồng accumulate — đừng để nó co tiếp.
(f) ĐỪNG lấp toàn bộ vùng trắng ICD — đã loại, không hoàn vốn.

## TIÊU CHÍ NGHIỆM THU
[ ] candidates_score ≥ 0,20 (rỗng hết = 0,0000; TRẦN = 0,2501)
[ ] code_accuracy từ diagnostics() ≥ 0,80 trên entity codeable có mã
[ ] 0 mã trong bài nộp không tồn tại trong KB đóng gói kèm
[ ] tỷ lệ bỏ trống ≤ 0,06 (gold: 0,0547). Bỏ trống nhiều hơn gold là mất điểm KHÔNG LÝ DO
[ ] CHẨN_ĐOÁN trả ĐÚNG 1 MÃ trong ≥ 94% trường hợp có mã
[ ] target_tty chạy được cả IN lẫn SCD bằng một cờ — không hard-code ở đâu
[ ] TỔNG THỜI GIAN PHASE ≤ 1,5 NGÀY-NGƯỜI
[ ] overlap_type không giảm quá 0,010

## CỔNG DỰ PHÒNG
- linking/ chưa chạy ⇒ trả candidates=[] TOÀN BỘ. Mất 10,00 nhưng HỢP LỆ.
  Mô phỏng r0,85 sp0,12 với N+H → 45,3.
- Whitelist đang loại >2 mã gold ⇒ chuyển sang loại-theo-T200 NGAY, đừng debug whitelist.
- ***** sinh dương tính giả ⇒ trả rỗng cho ca đó.

[ ] notebooks/runbook.ipynb chạy lại từ đầu, Ô 8 (TỰ KIỂM) XANH.
    Phase thêm file mới hoặc đổi cờ dòng lệnh ⇒ PHẢI cập nhật notebook. Một notebook
    sai còn tệ hơn không có notebook.

## SỞ HỮU FILE
src/smart_medic/linking/ · resources/lay_terms_vi.yaml · data/artifacts/ (gazetteer)
KHÔNG đụng: extract/ · assertion/ · decision/ · configs/*.yaml

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau khi luật kiểm chứng chạy và đo được trên 162 gold: báo candidates_score,
code_accuracy, tỷ lệ abstain, tỷ lệ bỏ trống, và SỐ ĐIỂM THẬT thu được so với baseline.
Nếu số đó dưới 1,00 điểm: NÓI THẲNG RA và đề xuất chuyển người sang P3/P6. DỪNG.

## CẬP NHẬT TIẾN ĐỘ TRONG PLAN — CHỈ SAU KHI USER XÁC NHẬN
Điều kiện kích hoạt DUY NHẤT: user nói rõ P5 đã xong / đã duyệt. Bạn vừa báo cáo
xong mà user chưa trả lời ⇒ CHƯA được sửa gì. Tự tick là làm bảng mất giá trị.

NGOẠI LỆ SỞ HỮU FILE: khi và chỉ khi điều kiện trên thoả, bạn được ghi vào
`docs/reports/plan-v4.html`, GIỚI HẠN ở các ô trạng thái. KHÔNG sửa số liệu, KHÔNG
sửa bảng đòn bẩy, KHÔNG sửa văn bản phân tích — đổi một con số trong plan là việc
khác hẳn và phải hỏi riêng.

1. Danh sách việc lấy bằng MỘT lệnh — dò theo tag phase, ĐỪNG dùng số dòng (số dòng
   trôi sau mỗi lần sửa plan):
       grep -nE '(class="c">|<td>)(⬜|⚠) (P[0-9] · )*P5( |<)' docs/reports/plan-v4.html
   Neo vào `class="c"`/`<td>` để KHÔNG bắt văn xuôi tiền đề trong tab 07.
   `grep '⬜ P5'` trần thì BỎ SÓT marker đa phase — ví dụ thật: dòng `extract/`
   mang `⬜ P1 · P3 · P5`.
2. Đổi marker theo trạng thái THẬT, ba mức:
     ✅  chạy được VÀ có số đo chứng minh
     ⚠   cơ chế có nhưng số liệu/độ phủ còn thiếu — ghi rõ thiếu gì, ngay trong ô đó
     ⬜  chưa làm
   Đạt một phần thì ghi ⚠ kèm con số thực tế. KHÔNG làm tròn lên thành ✅.
3. Hai bảng trạng thái khác phải khớp theo:
     tab 02 §D "Chế độ hỏng & phòng thủ" — cột "Đã có?"
     tab 04 bảng runbook 8 ô — cột "Trạng thái hôm nay" (pill nào P5 vừa mở khoá)
4. File mới sinh trong phase ⇒ thêm vào cây thư mục tab 01 §B. Cây là một khối `<pre>`
   căn bằng khoảng trắng, và căn lề KHÔNG đều: dòng file ở cột 36, dòng thư mục ở cột
   35, vài tên dài tràn 37–38. ĐỪNG tin con số — COPY căn lề của dòng anh em ngay trên.
5. Tab 08 Checklist lưu ở localStorage của TRÌNH DUYỆT, không có gì trong file để sửa.
   BẢO USER tự tick P5-1…P5-6. ĐỪNG báo là đã tick hộ.
6. Commit RIÊNG, đừng trộn với code: `docs: mark P5 progress in plan-v4`.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`kb-linker`** — phase này *là* việc của nó: gazetteer, truy hồi ứng viên, phân giải `tty`, đọc RRF. Giao trọn `src/smart_medic/linking/` cho nó thay vì tự viết.

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
