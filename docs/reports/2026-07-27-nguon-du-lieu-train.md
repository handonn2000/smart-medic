# Nguồn dữ liệu train — đo trên dữ liệu thật (2026-07-27)

## Phát hiện quan trọng: 100 file test CHÍNH LÀ bệnh án tiếng Anh đã dịch

Đo trên toàn bộ 100 file `data/test/`, khớp tiêu đề mục với tên section của bệnh án Mỹ:

| tiêu đề tiếng Việt trong test | số file | tương ứng section MIMIC/n2c2 |
|---|---|---|
| Tiền sử bệnh | 56 | Past Medical History |
| Bệnh sử | 23 | History of Present Illness |
| Thuốc trước khi nhập viện | 22 | Medications on Admission |
| Kết quả xét nghiệm | 14 | Pertinent Results |
| Dị ứng | 11 | Allergies |
| Các yếu tố nguy cơ | 8 | Risk Factors |
| Lý do vào viện | 5 | Chief Complaint |
| Tiền sử gia đình | 3 | Family History |
| Khám thực thể | 2 | Physical Exam |

**69/100 file có ít nhất một tiêu đề kiểu này.** Thêm ba bằng chứng độc lập:

- 24 file chứa tên thuốc tiếng Anh nguyên văn (metoprolol, doxycycline, atenolol, omeprazole...).
- 3 file còn nguyên sig tiếng Anh chưa dịch (`po bid`, `prn`, `q6h`) — file 2 và 28 có cả sig lẫn tên thuốc Anh.
- **71% span `THUỐC` không bị che trong gold là tiếng Anh thuần ASCII** (55/78).
- Ví dụ output trong PRD (`amlodipine 10 mg po daily`, `senna 8.6 mg po bid:prn`) là đúng format
  `Medications on Admission` của MIMIC. Chuỗi này KHÔNG có trong 100 file test — nó là ví dụ riêng
  BTC dựng, tức BTC cũng lấy từ cùng nguồn đó.

Hệ quả: dịch bệnh án tiếng Anh sang tiếng Việt **không phải cách gián tiếp — đó gần như là tái tạo
đúng quy trình BTC đã dùng để tạo đề.**

## Thí nghiệm đã chạy: dịch thật 12 note rồi đo

Lấy `harishnair04/mtsamples` (Apache-2.0, 4.999 note), chọn 145 note dài 800–2.600 ký tự,
dịch 12 note bằng Claude với prompt ép: tiêu đề theo lối bệnh án VN, **giữ nguyên tên thuốc tiếng Anh**,
giữ viết tắt xét nghiệm và đơn vị, tên bệnh dịch theo thuật ngữ ICD-10 tiếng Việt.

| nguồn | ký tự TB | tên ICD /1000 ký tự | % file có ICD | % tiêu đề mục | % kết quả XN | % viết tắt lab |
|---|---|---|---|---|---|---|
| **TEST (BTC)** — đích | 2.038 | **2,1** | 94 | 81 | 30 | 8 |
| **mtsamples dịch VN** | 1.470 | **2,0** | 91 | 83 | 25 | **0** |
| blog VN 752k | 1.176 | 1,1 | — | 0 | 13 | 1 |
| VietnameseMedicalText | 3.754 | 1,3 | — | 2 | 32 | 2 |
| vietnamese-medical-notes 18k | 2.551 | 0,9 | — | 0 | 10 | 1 |

Mật độ tên ICD nguyên văn của bản dịch là **2,0 /1000 ký tự — gần như bằng test (2,1) và gấp đôi
mọi corpus tiếng Việt công khai**. Đây là con số quyết định vì `candidates_score` có trọng số ×0,4
và 94/100 file test lấy được mã ICD bằng tra bảng nguyên văn.

Alias thật sự khớp được, lấy từ chính bảng `ICD10.csv` của BTC: `viêm mũi dị ứng`, `viêm khớp dạng thấp`,
`suy tim sung huyết`, `thoái hóa khớp`, `hở van ba lá`, `hở van động mạch phổi`, `béo phì`, `loạn nhịp tim`.
Nhánh thuốc: **1,7 tên RxNorm/file, ngang test (1,6)** — `loratadine`, `claritin`, `allegra`.

## Ba hạn chế đã đo được, phải xử lý

1. **Viết tắt xét nghiệm: 0/12 file** (test 8%). Nguyên nhân ở nguồn, không ở bản dịch — mtsamples
   chỉ 3% note có WBC/AST/CRP. Phải lọc riêng note có `LABORATORY DATA` hoặc lấy từ nguồn khác.
2. **Prompt "giữ nguyên tên thuốc tiếng Anh" bị bỏ qua 11/12 lần.** Model dịch `Claritin` thành
   `loratadine` (đúng hoạt chất nhưng sai văn bản gốc). Phải ép bằng hậu xử lý: khoá tên thuốc
   trước khi dịch (thay bằng placeholder rồi hoàn nguyên), không tin prompt.
3. **Token bị che `***`: 8% vs test 30%.** Phải chèn nhân tạo sau khi dịch — bẫy này quyết định
   `TÊN_XÉT_NGHIỆM`/`THUỐC`, và PRD nói rõ 30 file test có 99 token bị che.

## License — kiểm rồi, có cái không dùng được

| dataset | license | dùng được? |
|---|---|---|
| `harishnair04/mtsamples` | **Apache-2.0** | ✅ dùng được, kể cả nộp kèm source code |
| `AGBonnet/augmented-clinical-notes` (30k) | **MIT** | ✅ dùng được |
| `starmpcc/Asclepius-Synthetic-Clinical-Notes` (158k) | **CC-BY-NC-SA-4.0** | ⚠️ phi thương mại — cuộc thi Viettel có yếu tố thương mại, nên tránh |
| `bigbio/n2c2_*` | other (DUA) | ❌ cần ký thoả thuận với n2c2/Harvard |
| MIMIC-III/IV | PhysioNet DUA | ❌ cần khoá học CITI + ký DUA, và **cấm redistribute** — không nộp kèm được |
| `ura-hcmut/vi_Asclepius-Synthetic-Clinical-Notes` | MIT | ⚠️ đã là bản dịch VN sẵn nhưng gốc là CC-BY-NC-SA |

PRD yêu cầu nộp kèm **dữ liệu nhóm sử dụng** cho top ~15. Điều này loại MIMIC và n2c2 ngay:
không redistribute được thì không nộp được, không nộp được thì BTC không chạy lại được → bị loại.
**Apache-2.0 và MIT là hai lựa chọn an toàn duy nhất.**

## Đề xuất: ba nguồn, ba vai trò khác nhau

| nguồn | vai trò | nhãn từ đâu | chất lượng nhãn |
|---|---|---|---|
| **sinh từ bảng ICD của BTC** | sửa lỗi thu ngắn span | code tính offset | **đúng 100%** |
| **mtsamples dịch VN** | phủ thể loại bệnh án | Claude annotate | thừa hưởng sai số Claude |
| **corpus VN công khai** | phủ cách nói dân gian | Claude annotate | thừa hưởng sai số Claude |

Thứ tự làm theo lợi/công: nguồn 1 trước (nhãn đúng tuyệt đối, sửa trực tiếp chuỗi thu ngắn
gold 3,53 → silver 3,09 → pred 2,36 từ), nguồn 2 thứ hai (thể loại khớp nhất, license sạch),
nguồn 3 cuối. Mọi phương án đều phải đo trên **6 file holdout thật** — đó là tài sản duy nhất
cho phép nói "chưa thấy".

## Đo lại được

Bảng số liệu: `nguon_du_lieu_train.csv`. Mọi con số trong báo cáo này đo trực tiếp trên
`data/test/` (100 file), `data/dev_gold/` (20 file), `data/kb/icd10_aliases.csv.gz` (15.464 alias
dài ≥6 ký tự) và dữ liệu tải thật từ HuggingFace datasets-server.
