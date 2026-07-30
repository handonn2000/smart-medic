# P0 · NỀN MÓNG & CỔNG SỐNG CÒN

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
Bạn làm PHASE P0 — NỀN MÓNG & CỔNG SỐNG CÒN. Không phase nào chạy được trước bạn.
NHẮM: 11,59 điểm (ràng buộc lược đồ) + chống điểm 0 tuyệt đối.

## KIỂM TIỀN ĐỀ — làm trước khi viết dòng code đầu tiên
1. `python3 -m pytest tests/ -q` chạy được. CHỈ test_silver_offsets được FAIL
   (165 vi phạm — lỗi thật trong dữ liệu bạc). Bất kỳ test nào khác fail ⇒ BÁO, DỪNG.
2. `ls src/smart_medic/` thấy 8 thư mục layer, mỗi thư mục có __init__.py và README.md.
3. `ls data/test/*.txt | wc -l` = 100.
Nếu một trong ba không thoả: BÁO CÁO và DỪNG. Đừng tự sửa cấu trúc repo.

## ĐỌC
- src/smart_medic/{io,layout,validate}/README.md — hợp đồng và bất biến của 3 layer bạn sở hữu
- configs/README.md — khung 3 file YAML
- tests/README.md — 3 test chống rò API bạn phải viết
- docs/reports/plan-v4.html tab 04 → P0

## VIỆC
1. L1 io/document.py
   - Document(raw) frozen dataclass. `raw` đọc với newline="" — KHÔNG để Python dịch \r\n.
   - .normalized + .char_map CHỈ để so khớp. .slice(s,e) → raw[s:e]. .to_raw(norm_idx).
   - io/corpus.py: load_test() / load_gold() / load_silver().
     load_silver() LỌC 165 vi phạm lược đồ LÚC NẠP (~5 dòng).
     KHÔNG regenerate 543 file — làm vậy là làm mọi số liệu đã đo không tái lập được.
2. L2 layout/{lines,outline,kv}.py
   - lines.py: NUM_HEADER · COLON_HEADER · KV · BULLET · PROSE. 97/100 file có dòng "Nhãn:".
   - outline.py: ngăn xếp thụt lề {0,4,8} → cây mục + đường tổ tiên.
   - kv.py: tách `;` VÔ ĐIỀU KIỆN; tách `,` CHỈ KHI phần theo sau khớp mẫu tên xét nghiệm
     (`Chol: 4,7 mmol/l` — 4,7 là DẤU PHẨY THẬP PHÂN); tách hai cặp KV cách nhau chỉ bằng
     khoảng trắng.
   - XUẤT ĐÚNG 3 THỨ: boundary_priors · section(offset) · unit(offset).
3. L6 validate/{schema,offsets,emit_json}.py  ⇐ 11,59 ĐIỂM Ở ĐÂY
   - assert raw[start:end] == text trên chuỗi GỐC, byte-exact, dung sai 0
   - type thuộc 5 nhãn; assertions là tập con của 3 nhãn
   - assertions PHẢI RỖNG với TÊN_XÉT_NGHIỆM và KẾT_QUẢ_XÉT_NGHIỆM  ⇐ 11,59 điểm
   - candidates rỗng trừ CHẨN_ĐOÁN/THUỐC
   - mọi mã tồn tại trong KB · 0 span lồng nhau
   - ÉP Ở TẦNG TUẦN TỰ HOÁ. KHÔNG BAO GIỜ tin model tự nhớ.
4. L0 configs/{pipeline,models,metric}.yaml
   - models.yaml có trường `params` từng model + assert tổng < 9e9 LÚC KHỞI ĐỘNG
   - metric.yaml: alignment: [greedy_iou, overlap_type] — CẢ HAI
5. scripts/submit/package_submission.py + runs/ + pyproject.toml + Makefile
   - zip: `cd data && zip -r ../output.zip output -x '*/.*'` (thư mục output/ NẰM TRONG archive)
   - json.dump(..., ensure_ascii=False), UTF-8, KHÔNG BOM, \n cuối file
   - LOẠI run_manifest.json, metric_internal.json, .DS_Store, __pycache__
   - manifest.json 10 trường (xem runs/README.md)
6. tests/test_no_api_in_runtime.py — 3 test:
   - test_no_vendor_http_in_runtime: import smart_medic.pipeline, đi hết sys.modules,
     khẳng định KHÔNG có openai/anthropic/google.genai/httpx/requests/aiohttp.
     Test CẤU TRÚC, không phải grep — phải bắt cả import gián tiếp.
   - test_no_network_at_inference: monkeypatch socket.socket thành ném lỗi, chạy 3 file.
   - test_param_budget: nạp configs/models.yaml, assert Σparams < 9e9.
7. tests/test_layer_boundaries.py — đi hết cây import từng layer, fail nếu một layer
   import từ layer CAO HƠN nó. Thứ tự: io < layout < extract < {assertion, linking}
   < decision < validate; eval/ không import layer nào.

## CÁI BẪY CỤ THỂ CỦA PHASE NÀY
(a) NFC. 20/100 file test và 41/162 gold KHÔNG ở NFC. Một lần normalize sai chỗ là lệch
    tới 143 ký tự và KHÔNG có exception nào. Đây là lỗi tốn kém nhất có thể mắc.
(b) NEWLINE. Đọc file mà không có newline="" thì Python dịch \r\n → \n và mọi offset
    lệch theo số dòng. Không ai phát hiện bằng mắt.
(c) SIDECAR TRONG ZIP. load_dir() của ta bỏ qua sidecar theo hình dạng, nhưng scorer của
    BTC có thể KHÔNG. Loại file phụ ra khỏi archive, đừng dựa vào việc nó sẽ bị bỏ qua.
(d) ĐỪNG cài ràng buộc lược đồ ở trong model hay trong extract/. Nó phải ở validate/ —
    đó là điểm khác biệt giữa "ràng buộc" và "kỳ vọng".

## TIÊU CHÍ NGHIỆM THU — báo từng dòng kèm số thực tế
[ ] pytest tests/test_offsets.py -q SẠCH; round-trip NFC/NFD 262 file, dung sai 0
[ ] unzip -l output.zip đúng 100 file 1.json…100.json trong thư mục output/, 0 file phụ
    → DÁN NGUYÊN output của unzip -l vào báo cáo. Không mô tả bằng lời.
[ ] ≥97/100 file test nhận diện được dòng header; 0 ca `4,7` bị tách thành hai token
[ ] 0 entity xét nghiệm mang assertion; 0 entity không mã có candidates — kiểm trên
    chính file JSON đã ghi, không kiểm trên biến trong bộ nhớ
[ ] 3 test chống rò API xanh; test_param_budget xanh; test_layer_boundaries xanh
[ ] grep không tìm được ngưỡng số nào trong src/ — chúng ở configs/pipeline.yaml

## SỞ HỮU FILE (chỉ ghi vào đây)
src/smart_medic/{io,layout,validate}/ · configs/*.yaml · scripts/submit/ ·
tests/test_{document,no_api_in_runtime,layer_boundaries}.py · pyproject.toml · Makefile
KHÔNG đụng: src/smart_medic/eval/scoring.py · data/test/ · scripts/data_gen/

## ĐIỂM DỪNG ĐỂ BÁO CÁO
Sau khi cả 6 ô nghiệm thu có số: báo bảng nghiệm thu, output của `unzip -l`, và
`pytest tests/ -q`. DỪNG, chờ xác nhận. ĐỪNG bắt đầu P1.
```

---

## ⚡ TẬN DỤNG HẠ TẦNG ĐÃ CÓ — đừng làm lại bằng tay

Repo này đã có sẵn subagent, skill và hook. Dùng chúng thì phase chạy nhanh hơn và ít lỗi hơn.

**Subagent** (`.claude/agents/` — gọi bằng Task tool):
- **`probe-builder`** — cho `scripts/submit/package_submission.py` và bộ kiểm 7 mục của `output.zip`. Nó KHÔNG bao giờ tự nộp, an toàn để giao trọn khâu đóng gói.

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
