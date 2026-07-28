# Kết quả phân xử gold dev — 314/314 (2026-07-27)

Chốt `data/dev_gold/`. Mọi quyết định nằm trong `DECISIONS` của
`scripts/adjudicate_dev_gold.py`, mỗi mục kèm lý do; chạy lại script là dựng lại
được gold từ `dev_gold_consensus` + `dev_adjudication.json`.

| | consensus (cũ) | phân xử (mới) |
|---|---|---|
| mention | 689 | **979** |
| giữ / bỏ trong 314 mục | — | 290 / 24 |
| schema + verify position | OK | OK |
| mã không có trong KB | — | **0** / 304 mã |
| vi phạm type-gate / assert-gate | — | 0 / 0 |

## Bốn quy ước, mỗi cái tựa vào bằng chứng chứ không phải khẩu vị

**A · Mã ICD: chuộng con `.9` hơn mã cha 3 ký tự.** v4.2 đo trên tập consensus
*rời* với tập xung đột này: 22/37 lỗi gazetteer là do trả mã cha trong khi gold
trả con `.9`. Đề bài cũng dùng mã con (`K21.0`/`K21.9`). Áp cho `A82.9` ×14,
`E85.9` ×8, `K25.9`, `N97.9`, `O00.9`, `I48.9` ×2, `E11.9` ×4.

**B · Mã RxNorm theo mức bằng chứng (v4.1).** Có hàm lượng *và* đường dùng →
SCD, đúng khuôn ví dụ chính thức (`amlodipine 10 mg po daily` → 308135 = SCD):
`metoprolol 25mg po bid` → 866924, `aspirin 325mg x 1` → 212033. Tên trơ → RXCUI
của anchor: IN cho hoạt chất, **BN cho biệt dược**.

**C · Ranh giới = cụm khái niệm tối thiểu.** Bỏ bổ ngữ mức độ/thời lượng/vị
trí/người chứng kiến và danh từ dẫn ("tình trạng", "kết quả", "cảm giác"). Giữ
phần trong ngoặc khi nó *gọi tên* khái niệm (`Vastarel (trimetazidin)`), bỏ khi
chỉ là viết tắt (`(AH)`, `(RLL PNA)`).

**D · Nhất quán trong file thắng sở thích cá nhân.** Khi consensus đã gán mã hay
assertion cho cùng một chuỗi ở chỗ khác trong cùng file, mục xung đột đi theo.
Đây là quy ước quyết định nhiều nhất, và nó tự kiểm chứng được.

## Năm chỗ cả hai model đều sai

| file | span | hai model | chốt | vì sao |
|---|---|---|---|---|
| 1 | `Vitamin K` | opus `[]` · sonnet `8163` | **11258** | 8163 là **phenylephrine**; "vitamin K" là chuỗi duy nhất của RXCUI 11258 |
| 8 | `seroquel` | `51272` · `[]` | **83553** | 51272 là quetiapine (hoạt chất); Seroquel là **biệt dược** → BN |
| 14·54 | `gleevec` ×4 | `282388` · `[]` | **282386** | 282388 là imatinib; Gleevec là biệt dược |
| 26 | `eliquis` | `[]` · `1364430` | **1364436** | 1364430 là apixaban; Eliquis là biệt dược |
| 1 | `thiếu máu tan huyết` ×3 | `D59.9` · `[]` | **D55.0** | D59.9 là tan máu **mắc phải**; G6PD là bệnh men **di truyền** — sai cơ chế |
| 21 | `amyloidosis tự miễn dịch` | `[]` · `E85.9` | **E85.3** | trong bộ ba AL–AA–di truyền, "tự miễn dịch" là thể AA (thứ phát) |

Đáng chú ý nhất là bốn dòng biệt dược: cả hai model đều quy biệt dược về hoạt
chất. Tra KB thì mỗi chuỗi biệt dược thuộc **đúng một** concept BN, nên đây là
lỗi sửa được tất định, không phải chuyện phán đoán.

## Một chỗ bằng chứng lâm sàng lật ngược

File 6, `xuất huyết dưới nhện`: opus gán `I60.9` (tự phát), sonnet gán `S06.6`
(chấn thương). Văn bản: *"bệnh nhân **bị ngã** và được chẩn đoán xuất huyết dưới
nhện. Chụp CT … **bầm dập nhu mô** … kèm một lớp dịch dưới màng cứng"*. Ngã +
bầm dập nhu mô + tụ dịch dưới màng cứng ⇒ chấn thương. **S06.6**.

## 10 lỗi gán vị trí trong consensus, đã sửa

Không phải lỗi nhãn mà là lỗi định vị: khi annotation liệt kê cả `buồn nôn` lẫn
`nôn` cho câu "buồn nôn, nôn", bộ định vị ăn `nôn` **vào trong** `buồn nôn`.
Span lồng nhau thì nhãn BIO không biểu diễn được.

Cách sửa: dời sang một lần xuất hiện **có thật** của đúng chuỗi đó, không có chỗ
trống thì bỏ và báo cáo — không bao giờ tự chế offset. 10/10 đều dời được.
Đáng kể nhất là file 27: consensus gán `viêm phổi`[20,29] trong khi văn bản ở đó
là `viêm phổi hoại tử`; `viêm phổi` đã được dời về [68,77] — *"giai đoạn nặng
của **viêm phổi**"* — đúng chỗ nó thuộc về.

## Đo lại: precision 74.5% → 97.6%

| gold | recall | precision | thiếu | thừa | FINAL |
|---|---|---|---|---|---|
| consensus (689) | 45.7% | 74.5% | 374 | 108 | 0.3214 |
| **phân xử (979)** | **42.2%** | **97.6%** | **566** | **10** | **0.3627** |

**"Vấn đề precision" của pipeline phần lớn là ảo ảnh của gold thưa.** 98/108
mention từng bị tính là thừa hóa ra khớp một span mà ít nhất một annotator có
bắt được và đã được xác nhận là hợp lệ. Chỉ còn **10** mention thực sự thừa.

Kết luận "recall là nút thắt" vì thế **mạnh lên**, không yếu đi: tỉ lệ
thiếu:thừa từ 3.5:1 thành **57:1**. Kế hoạch v4 recall-first đứng vững.

## CẢNH BÁO: khoảng cách với leaderboard rộng ra, không hẹp lại

Điểm nội bộ 0.3214 → **0.3627**, trong khi leaderboard là **23.53**. Khoảng cách
từ ~8.6 điểm thành **~12.7 điểm**. Điểm tăng là do cơ học của `--unmatched
zero`: bỏ được 98 mục 0.0 phía pred thì trung bình lên, dù đã thêm 192 mục 0.0
phía gold.

Đừng đọc con số này là "hệ thống vừa tốt lên". Không có gì trong pipeline đổi cả
— chỉ có thước đo đổi. Hai cách giải thích còn để ngỏ:

1. Gold thật **thưa hơn** gold này ⇒ ta đang nới tay. Chặn suy từ delta
   leaderboard ở v4.2 là `G_corpus ≤ 2.940`; quy mô của gold này là ~3.589,
   **vượt chặn ~22%**.
2. Gold thật **dày** nhưng chất lượng `text`/`candidates` của ta tệ hơn mức đo
   được ở đây, vì gold này do chính hai LLM sinh ra rồi lại dùng để chấm — thiên
   kiến cùng-annotator.

Chưa phân biệt được hai khả năng đó bằng dữ liệu đang có. Nên: **dùng gold này
để so TƯƠNG ĐỐI giữa các phiên bản, đừng đọc mức tuyệt đối** — cảnh báo của v4.2
vẫn nguyên giá trị và nay còn đáng lưu ý hơn.

## 24 mục bị bỏ, theo bốn lý do

| lý do | số | ví dụ |
|---|---|---|
| thủ thuật **điều trị**, không phải "thủ thuật chẩn đoán" | 12 | cắt bỏ ống mật chủ, đặt stent, cắt bao quy đầu, ghép mô mềm |
| chồng lấn một mention đã chọn | 6 | `Vastarel` (lồng trong `Vastarel (trimetazidin)`), `tiểu đường` (lồng trong `bệnh tiểu đường`) |
| thực phẩm, không phải thuốc | 3 | trà gừng, mật ong, trà đinh hương |
| hành vi/nguy cơ, không phải tên bệnh | 2 | `Vệ sinh răng miệng kém`, `Hút thuốc lá` |
| tiêu đề nhóm, không phải một chẩn đoán | 1 | `Biến chứng tim mạch` |

Cả 5 type trong đề bài đều không có chỗ cho thủ thuật điều trị — đó là lý do bỏ,
không phải vì thấy chúng không quan trọng.

## Việc tiếp theo

1. `data/dev_gold/` đã chốt — mở khóa §1 của
   [kế hoạch silver](2026-07-27-silver-plan.md).
2. Tách 6 file gold làm holdout trước khi train (§2 của kế hoạch đó): §4c hiện
   đo trên chính dữ liệu train.
3. Thêm lớp validate mã vào `_clean_candidates()` — nó vẫn chỉ ép kiểu string,
   không kiểm mã có tồn tại trong KB. Bốn lỗi biệt dược ở trên là đúng loại lỗi
   mà lớp này bắt được (candidates chiếm trọng số 0.4).
