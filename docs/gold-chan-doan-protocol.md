# Gán gold cho CHẨN_ĐOÁN — quy trình

> **Đọc mục 1 trước khi làm bất cứ thứ gì.** Việc này đã từng được làm một lần,
> và gold sinh ra khi đó **dự đoán sai dấu**: nó nói mã chẩn đoán đáng giá
> `+5,11`, leaderboard nói `−1,77`. Không hiểu vì sao thì lặp lại nguyên xi.

---

## 1. Đã có sẵn những gì

Nhánh `origin/feature/solution_v6` và `feature/solution_v5` chứa cả một đợt làm
gold trước đó. **Không dựng lại từ đầu.**

| Tài nguyên | Đường dẫn | Dùng để |
|---|---|---|
| Guideline gán nhãn đầy đủ | `docs/gold-annotation-handoff.md` (v6) | Quy ước type/span/assertion — vẫn dùng được nguyên |
| Gold đồng thuận 20 file | `data/dev_gold_consensus/` (v5) | Mốc đối chiếu |
| Gold 100/162 file restyled | `data/generated_medical_records/restyled/annotations_gold/` (v6) | Corpus lớn hơn |
| ADR quyết định | `docs/decisions/0001…0006` (v6) | Vì sao chốt như vậy |
| **Số đo leaderboard** | commit `cfe764c`, `23f91b9`, `6fe0840`, `4e8e148` | ★ Tín hiệu KHÔNG thiên lệch duy nhất |
| Skill dựng gold đa model | `smart-medic-preannotate` | Tự động hoá bước 2 |

Lấy về:

```bash
git show origin/feature/solution_v6:docs/gold-annotation-handoff.md > /tmp/handoff.md
git checkout origin/feature/solution_v6 -- docs/decisions/
```

---

## 2. ★ Vì sao gold CHẨN_ĐOÁN cũ sai — và sai ở đâu

### 2.1 Số đo

Ba lần nộp thử, đo tách bạch đóng góp của từng loại mã:

```
Probe A   0 mã                      J_candidates 11,0259
Probe B   228 mã THUỐC              J_candidates 14,8832   (+3,86)
full      948 mã (764 CHẨN_ĐOÁN)    J_candidates 10,4617   (−0,56)
```

⇒ mã thuốc đáng `+3,86`; **764 mã chẩn đoán ngốn ≈ −4,42 điểm J**, tức `−1,77`
điểm cuối. Hiệu chỉnh lại lần hai còn tệ hơn: `−4,54 pp`.

### 2.2 Cơ chế

Với một entity **đã khớp span**, phát ra mã trong khi gold để rỗng biến một
`J = 1` cho không thành `J = 0`. Gold cũ đo được `P(gold rỗng | CHẨN_ĐOÁN) =
0,0521` nên canh bạc *trông có vẻ* an toàn. Trên tập test thật thì không.

### 2.3 Lỗi tư duy — chép nguyên văn từ `23f91b9` vì nó đáng giá

> *"Gold chứng minh gold CÓ MANG mã, đó là điều kiện cần. Điều kiện đủ là mã CỦA
> TA phải vượt điểm hoà vốn. Tôi gộp hai thứ làm một."*
>
> *"Hai nguồn đồng ý với nhau không mạnh hơn một nguồn, khi cả hai cùng đo 'gold
> có mã ở đây không' còn câu hỏi được chấm là 'mã của ta có đúng không'."*

Gold cũ dựng bằng đồng thuận opus-5 × sonnet-5. Khi hai LLM cùng chọn một mã sai
hợp lý, gold **đóng đinh cái sai đó**; hệ của ta (cũng dùng LLM) khớp đúng cái
sai ấy và ăn điểm nội bộ. Đây là vòng lặp tự khen — cùng lớp lỗi mà
`retrieval_probe.yaml` đã cảnh báo, chỉ ở tầng cao hơn.

### 2.4 Vì sao THUỐC chuyển được mà CHẨN_ĐOÁN thì không

> *"Triệu chứng vượt được ngưỡng vì chương XVIII của ICD là một từ vựng đóng, nhỏ,
> gồm đúng những chữ bệnh nhân viết ra; còn chẩn đoán là cụm danh từ mở, mà trượt
> gần thì cũng chỉ là trượt."*

Tên thuốc là **định danh đóng** (`amlodipine` chỉ có một nghĩa). Tên bệnh là cụm
danh từ **mở**, và Jaccard không cho điểm cho "gần đúng".

---

## 3. Câu hỏi mà gold mới PHẢI trả lời

Không phải *"gold có mã ở đây không"*. Mà:

> **Mã do hệ của ta sinh ra có bằng đúng mã của gold không?**

### 3.1 Ngưỡng hoà vốn — con số cần ước lượng

Từ `23f91b9`: phát mã chỉ có lãi khi

```
a / (1 − a)  >  P(gold rỗng) / (1 − P(gold rỗng))  =  0,553
⇒  a  >  0,356
```

với `a` = **tỉ lệ mã ta phát ra khớp CHÍNH XÁC gold**.

Toàn bộ mục tiêu của đợt gán nhãn này là ước lượng `a` cho đủ chắc để trả lời
`a > 0,356` hay không. Không phải để "có bộ gold đẹp".

### 3.2 Cỡ mẫu — ít hơn bạn tưởng

Đóng khung thành **quyết định nhị phân** thì cỡ mẫu nhỏ hẳn. Kiểm định một phía,
`α = 0,05`, power `0,8`, phân biệt `a = 0,356` với `a = 0,50`:

```
n ≈ [(1,645·√(0,356·0,644) + 0,842·√(0,5·0,5)) / 0,144]²  ≈  71
```

⇒ **~100 mention CHẨN_ĐOÁN là đủ** để chốt bật/tắt. Muốn ước lượng `a` với sai
số ±0,05 thì mới cần ~350 — nhưng đó là câu hỏi khác và chưa cần.

---

## 4. Chống thiên lệch — ba quy tắc không được phá

**① Lấy mẫu MÙ.** Chọn mention bằng tiêu chí độc lập hoàn toàn với kết quả
retrieval. Lấy ngẫu nhiên phân tầng theo **chương ICD** và **thể loại văn bản**.
Tuyệt đối không chọn "ca BM25 trượt" — đó là dựng test set đối kháng với chính
baseline, mọi cải thiện đo sau đó đều ảo.

**② Người gán KHÔNG được nhìn output của hệ.** Nếu dùng
`smart-medic-preannotate` để tiền gán, thì mã do LLM đề xuất phải bị **che** khi
người phân xử đọc, hoặc người phải tra độc lập rồi mới so. Nhìn trước là biến
phép đo thành đo mức đồng ý với LLM.

**③ Không dùng cùng họ model với pipeline.** Gold cũ hỏng vì opus-5 × sonnet-5
đồng thuận, mà pipeline cũng chạy trên cùng họ model — sai số tương quan. Nếu
buộc phải tiền gán bằng LLM, dùng model **khác họ**, và coi kết quả là *gợi ý*,
không phải nhãn.

---

## 5. Quy ước riêng cho CHẨN_ĐOÁN

Guideline chung ở `gold-annotation-handoff.md` §3 vẫn đúng. Bổ sung ba điểm mà
số đo mới cho thấy là quyết định:

### 5.1 Mức phân cấp — điểm tắc lớn nhất

12/12 ca trượt hạng-1 ở nhánh ICD là lỗi **mức phân cấp**, không phải lỗi nghĩa.
Gold phải chốt dứt khoát, nếu không nó vô dụng:

| Tình huống | Chốt |
|---|---|
| Mention **không** nêu chi tiết (`"đái tháo đường"`) | Mã **3 ký tự** (`E14`), không phải `E14.9` |
| Mention nêu chi tiết (`"đái tháo đường típ 2"`) | Mã đặc hiệu (`E11`) |
| **Mã khối** (`E10-E14`, `D55-D59`) | ❌ **KHÔNG BAO GIỜ** là đáp án |

Quy ước mã khối cần gold xác nhận, nhưng bằng chứng đã mạnh: mọi mã trong ví dụ
của BTC (`D55.0`, `K21.0`, `O14`, `243670`) đều là mã thật. Loại mã khối khỏi
ứng viên nâng `R@1` nhánh ICD **0,857 → 0,893**, 3 ca cứu, 0 hồi quy.

### 5.2 `ICD10.csv` của BYT là thẩm quyền, không phải WHO *(D4)*

Danh mục BYT **đặt lại nghĩa** nhiều mã:

```
K32   BYT: "Xuất Huyết Tiêu Hóa"      WHO: rò dạ dày–tá tràng
K32.0 BYT: "Xuất Huyết Tiêu Hóa Cao"
```

⇒ chọn mã có **nhãn tiếng Việt khớp sát mention nhất**.

⚠️ **Không tự động hoá D4.** Khớp chữ có lúc sai y khoa: `"hẹp động mạch chủ"`
khớp nhãn `Q25.3` (hẹp **bẩm sinh**) nhưng ở người lớn phải là `I35.0` (hẹp van
**mắc phải**).

> Lưu ý về KB hiện tại: `SOURCE_PRIORITY` đặt `icd10_pdf_who` **trước**
> `icd10_csv_byt`, nên `pref_vi` hiển thị tên WHO. Retrieval không bị ảnh hưởng
> (nó tìm trên mọi term), nhưng người gán nhãn đọc `pref_vi` sẽ thấy tên WHO —
> phải tra cả hai trước khi chốt.

### 5.3 Chín lỗi mã lặp đi lặp lại trong dữ liệu cũ

Kiểm riêng chín ca này, chúng đã sai một lần rồi:

| Mention | Sai | Đúng | Vì sao |
|---|---|---|---|
| bệnh động mạch vành | `I79` | `I25.1`/`I25.9` | `I79` là bệnh phân loại nơi khác |
| đái tháo đường | `O24.0` | `E14`/`E11` | `O24.0` là ĐTĐ **thai kỳ** |
| ung thư bàng quang | `D30.3` | `C67` | `D30.3` là u **lành** |
| phì đại tuyến tiền liệt | `D29.1` | `N40` | `D29.1` là u **lành** |
| thiếu máu | `D46.4` | `D64`/`D62` | `D46.4` là thiếu máu kháng trị |
| chậm phát triển (trẻ) | `P05.9` | `R62.0` | `P05.9` là chậm phát triển **trong tử cung** |
| đột quỵ | `I69.4` | `I64` | `I69.4` là **di chứng** |
| đau đầu gối | `R51` | `M25.5` | `R51` là đau **đầu** |
| COPD | `[]` | `J44` | bỏ trống dù tra được |

---

## 6. Schema — phải khác `retrieval_probe.yaml`

★ Đây là chỗ dễ sai nhất, và nó vô hiệu hoá phép đo nếu làm ẩu.

`retrieval_probe.yaml` dùng ngữ nghĩa **"tập chấp nhận được"**:

```yaml
- {mention: "đái tháo đường", gold: [E14, E11, E10]}   # trúng BẤT KỲ mã nào = đạt
```

`evaluate.py` tính `rank = ... if code in c.gold` — nên nó đo `Recall@k`, **không
đo được Jaccard**. Với gold thật, `gold` là **tập đáp án đúng**, và Jaccard phạt
cả thiếu lẫn thừa. Hai thứ này không thể dùng chung một file.

Gold mới phải ghi đúng tập đáp án, và cần **bộ chấm Jaccard riêng**:

```yaml
# data/probe/gold_icd.yaml — ngữ nghĩa TẬP ĐÚNG, không phải tập chấp nhận
- mention: "đái tháo đường"
  file: 42.txt
  span: [63, 77]          # tính bằng stages.textio.read_document, KHÔNG normalize
  gold: ["E14"]           # đúng tập này; thừa mã cũng bị phạt
  chapter: IV             # để phân tầng khi lấy mẫu
  genre: benh_an
```

Ba bất biến, kiểm bằng test:

1. `text == read_document(f)[span[0]:span[1]]` — dùng `stages/textio.py`, không
   `read_text()`, không `unicodedata.normalize`. **20/100 file trong `data/test/`
   không ở dạng NFC** — chuẩn hoá là lệch offset.
2. Mọi mã tồn tại trong KB (`lookup('icd10', code)` không trả `None`).
3. Không mã nào chứa `-` (mã khối).

---

## 7. Quy trình

```
1. Lấy mẫu mù        chọn ~100 mention theo tầng (chương ICD × thể loại)
                     KHÔNG nhìn kết quả retrieval

2. Tiền gán          smart-medic-preannotate, model KHÁC HỌ với pipeline
   (tuỳ chọn)        → chỉ là gợi ý, phải che khi phân xử

3. Người tra         tra ICD10.csv + PDF WHO, chốt theo §5
                     ghi lại ca lưỡng lự — chúng là dữ liệu, không phải rác

4. Kiểm bất biến     3 bất biến ở §6, chạy như test

5. Đo `a`            so mã hệ sinh ra với gold, tính tỉ lệ khớp CHÍNH XÁC
                     `a > 0,356` → bật mã chẩn đoán;  ngược lại → tắt

6. Xác nhận bằng     ★ BẮT BUỘC. Gold chỉ là proxy. Một lần nộp thử
   leaderboard       A/B là tín hiệu không thiên lệch duy nhất
```

**Bước 6 không được bỏ.** `cfe764c` ghi rõ: *"Chỉ nâng lại giá trị này dựa trên
số đo leaderboard, không bao giờ dựa trên số đo gold."*

---

## 8. Cạm bẫy

| Cạm bẫy | Hậu quả | Chặn bằng |
|---|---|---|
| Đo "gold có mã" thay vì "mã ta đúng" | Sai dấu quyết định — **đã xảy ra** | §3.1, đo `a` |
| Gold dựng bằng cùng họ model với pipeline | Sai số tương quan, vòng tự khen | §4 quy tắc ③ |
| Chọn mention theo ca baseline trượt | Test set đối kháng, cải thiện ảo | §4 quy tắc ① |
| Dùng chung schema với `retrieval_probe.yaml` | Không đo được Jaccard | §6 |
| `read_text()` hoặc normalize Unicode | Lệch offset, im lặng | `stages/textio.py` |
| Khử trùng lặp mention | Gold lặp `(text,type)` **33,1%** — mỗi lần nhắc là một span | handoff §3.3 |
| Tin gold mà không nộp thử | Lặp lại `cfe764c` | §7 bước 6 |

---

## 9. Vì sao nhánh THUỐC không cần đợt này

Track 0 đã nâng `R@1` trên gold thật của BTC `0,182 → 0,636` bằng luật, không
model. Và quy tắc `has_strength()` giải thích **10/11** dòng gold thuốc — trong
đó có ngoại lệ `nystatin → 7597` (IN) mà ADR-0001 để ngỏ là "SCD hay IN?".

> Đính chính cho ADR-0001: `gold-annotation-handoff.md` §5.3 ghi
> `docusate sodium 100 mg po bid → 1099278 (SCDC)`. Sai. `sample_output.json`
> của BTC ghi **`1099279`**, và `1099279` là *Docusate Sodium 100 mg Oral Tablet*
> (tầng SCD) còn `1099278` mới là SCDC `docusate sodium 100 mg`. Bỏ ca chép nhầm
> này thì bảng gold chỉ còn **một** ngoại lệ duy nhất là nystatin — và nystatin
> là ca **không có hàm lượng**. Quy tắc "có hàm lượng → SCD, không → IN" phủ
> trọn phần còn lại.
