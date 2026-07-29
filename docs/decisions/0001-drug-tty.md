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
