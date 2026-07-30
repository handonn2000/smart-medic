# ADR 0001 — Mức `tty` cho mã RxNorm của entity THUỐC

- **Trạng thái:** ✅ **TẠM CHỐT CHO GOLD ANNOTATION: `IN`**; lựa chọn khi nộp thi vẫn chờ Probe B
- **Ngày:** 2026-07-29 (bản 3)
- **Ảnh hưởng:** nhánh THUỐC → RxNorm, chủ yếu các span có hàm lượng

## Bối cảnh

RxNorm mô tả cùng một thuốc ở nhiều tầng cụ thể hoá, mỗi tầng là một RxCUI khác nhau.
Với `amlodipine 10 mg`: `IN` = 17767 (`amlodipine`), `SCDC` = 329526
(`amlodipine 10 MG`), `SCD` = 308135 (`amlodipine 10 MG Oral Tablet`). Không có điểm
Jaccard một phần giữa các tầng.

## Bằng chứng chính thức từ PRD

Ví dụ gold trong `docs/PRD.html` có 11 span thuốc, không phải 4:

| Span | RxCUI gold | tty |
|---|---:|---|
| `amlodipine 10 mg po daily` | 308135 | `SCD` |
| `aspirin 81 mg po daily` | 243670 | `SCD` |
| `metoprolol succinate xl 50 mg po daily` | 866436 | `SCD` |
| `guaifenesin ml po q6h:prn` | 392085 | `SCD` |
| `nystatin oral suspension 5 ml po qid:prn` | 7597 | `IN` |
| `acetaminophen 325-650 mg po q6h:prn` | 313782 | `SCD` |
| `pravastatin 40 mg po daily` | 904475 | `SCD` |
| `docusate sodium 100 mg po bid` | 1099278 | `SCDC` |
| `senna 8.6 mg po bid:prn` | 312935 | `SCD` |
| `clonazepam 0.5 mg po qam:prn` | 197527 | `SCD` |
| `clonazepam 1.5 mg po qhs` | 197528 | `SCD` |

Phân bố là 9 `SCD`, 1 `SCDC`, 1 `IN`. Gold thích ứng theo mức chi tiết của span:
hàm lượng thường dẫn tới sản phẩm, còn thể tích liều dùng như `5 ml` không tự tạo hàm
lượng. `docusate sodium → SCDC` vẫn là ngoại lệ chưa giải thích được.

## Bằng chứng từ corpus nội bộ

100 file gold đầu tiên dùng quy ước ingredient-level nhất quán. Đây là quy ước có chủ
đích: biệt dược được rút về hoạt chất và thuốc phối hợp được tách thành toàn bộ hoạt chất,
ví dụ `Imuran → azathioprine`, `Plaquenil → hydroxychloroquine`, `Advair → fluticasone +
salmeterol`.

Corpus nội bộ không phải gold của BTC nên không thể tự chứng minh tầng chấm điểm, nhưng là
baseline ổn định để hoàn thiện annotation trước khi có kết quả probe.

## Mức ảnh hưởng thực tế

Trong snapshot dùng để ra quyết định:

| Nhóm | Span | Tỷ lệ THUỐC |
|---|---:|---:|
| Không có hàm lượng — `IN` và quy tắc thích ứng cho cùng kết quả | 503 | 81,4% |
| Có hàm lượng — `IN` và tầng sản phẩm có thể khác nhau | 115 | 18,6% |

115 span tương đương khoảng 7,0% entity có candidates, nên trần ảnh hưởng ước lượng khoảng
1,1 điểm/100. Tranh chấp quan trọng nhưng không nên chặn text, type, assertion hay ICD.

## Quyết định vận hành

1. **Toàn bộ `annotations_gold/` hiện dùng `target_tty=IN`** để giữ một convention duy nhất.
2. **Không áp `scd_changes.json` hiện tại.** `scd_probe3.py` còn sai hoạt chất ở khoảng 11%
   đề xuất do khớp token trực tiếp trên biệt dược.
3. Pipeline candidates sau này phải tham số hoá `target_tty`; không hard-code `IN` hay `SCD`.
4. Chỉ chuyển gold sang tầng sản phẩm sau Probe B và một review thủ công độc lập.

Nếu Probe B chọn tầng sản phẩm, thứ tự bắt buộc là:

1. Biệt dược → hoạt chất qua `brand_to_ingredient.json`.
2. Tra sản phẩm theo hoạt chất + hàm lượng + dạng bào chế.
3. Tách hai nhóm để adjudicate riêng: generic có liều và biệt dược có liều.
4. Không suy rộng quy tắc `docusate sodium → SCDC` nếu chưa có thêm bằng chứng.

## Quy ước độc lập với tranh chấp tty

1. Thuốc phối hợp có thể có nhiều mã ingredient, ví dụ `Advair` có hai hoạt chất.
2. Chẩn đoán được phép tổng quát hoá lên ICD ba ký tự khi văn bản không đủ chi tiết.
3. Chỉ dùng RxCUI có atom hoạt động `sab=RXNORM`; mã chỉ tồn tại ở nguồn khác không hợp lệ.

## Hệ quả kỹ thuật

- Khi hỗ trợ tầng sản phẩm, cần giữ chính xác số thập phân của hàm lượng và mở rộng viết
  tắt dạng bào chế (`xl`, `sr`, đường dùng).
- Hàm lượng không nhất thiết khớp tuyệt đối nếu RxNorm không có đúng sản phẩm được nêu;
  mọi fallback gần nhất phải được reviewer duyệt.
- Khi dùng `IN`, tra cứu biệt dược phải đi qua quan hệ brand-to-ingredient và giữ đủ hoạt
  chất của thuốc phối hợp.

---

## Cập nhật 30/07/2026 — phase P2: Probe B đã dựng, ADR **GIỮ TREO**

Phần thân giữ nguyên. Mục này ghi trạng thái Probe B và **quy tắc chốt**, để lần chốt sau
không phải suy diễn lại.

### Trạng thái

**GIỮ TREO ở `IN`.** Chưa nộp, nên chưa có ΔB thật. Zip đã sẵn sàng:
`runs/p2/output_probe_B.zip`, 7/7 kiểm tra đóng gói, `--probe B`.

Chủ dự án quyết định 30/07 **hoãn mọi lần nộp tới sau P3 · P4 · P5**. Với riêng ADR này thì
hoãn gần như không tốn gì — `target_tty` đã tham số hoá, trần ảnh hưởng ~1,1 điểm — nên treo
tiếp là hợp lý. Nhưng zip nói trên dựng từ đầu ra làn R (P1) và sẽ **hết hạn** khi P3/P4/P5
ghi đè `data/output/`: dựng lại trước khi nộp, đừng nộp file cũ.

### Probe B đã dựng thế nào

`eval/probe.py --variant B`: Probe A cộng RxCUI mức `IN`/`PIN`/`MIN` cho THUỐC, **khớp chuỗi
chính xác** với `data/artifacts/gazetteer.json` (bộ lọc `tty ∈ {IN,PIN,MIN}` của
`scripts/build_gazetteer.py` *chính là* "mức IN" của ADR này). Tối đa 2 mã/span, theo
`configs/pipeline.yaml: max_candidates`.

Khớp chính xác là có chủ đích: câu hỏi là **tầng mã**, không phải **recall của linker**.
Khớp mờ sẽ nhét recall của linker vào một delta đáng lẽ chỉ mang một biến.

- Trên `data/output` (bài nộp): **196/199** span THUỐC được mã hoá — 98,5%, 228 mã.
- Trên corpus gold (162 file): 979/1109 — 88,3%.

### ΔB nội bộ — cái mà lần nộp phải vượt qua

Đo trên gold, paired bootstrap B=10.000, `penalised/greedy_iou`:

    ΔB = +2,796   SE 0,201   CI95 [+2,413; +3,201]   MDE 0,394

Dưới `overlap_type`: +2,70. Cả hai cột cùng tăng ⇒ không vi phạm cột chặn.

### Quy tắc chốt — quyết định trước, đọc sau

| ΔB thật | Kết luận | Hành động |
|---|---|---|
| > +0,3 (kỳ vọng ≈ +3,9) | gold BTC ở tầng `IN` | **CHỐT** ADR này, `target_tty=IN` |
| ≈ 0 hoặc âm | gold BTC ở tầng sản phẩm | bật `target_tty=SCD`, chạy trình tự 4 bước ở "Quyết định vận hành" |
| \|ΔB\| < 0,3 | không phân giải được | **GIỮ `IN` VÀ ĐI TIẾP** |

Hàng cuối là hàng quan trọng: trần ảnh hưởng của tranh chấp này chỉ **~1,1 điểm** (18,6% span
thuốc có hàm lượng). **Không nộp probe thứ hai cho câu hỏi này** — một lần nộp đáng giá hơn
khi dùng cho thứ chưa biết đáp án.

### Ràng buộc kỹ thuật đã thoả

Điểm 3 của "Quyết định vận hành" — *pipeline candidates phải tham số hoá `target_tty`, không
hard-code* — đã có mặt: `configs/pipeline.yaml` mang `target_tty: 'IN'` kèm chú thích trỏ về
ADR này. Chuyển tầng là đổi một dòng YAML, không phải sửa code.
