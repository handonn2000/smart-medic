# S1 — SNOMED làm máy sinh dữ liệu huấn luyện cho embedding

> **Phạm vi:** kế hoạch khoa học cho mục S1 trong [`solution-backlog.md`](solution-backlog.md).
> **Trạng thái:** đã khảo sát bằng số đo thật trên KB Phase 3. Chưa triển khai.
> **Kết luận ngắn:** ý tưởng đúng về kỹ thuật, **sai về thời điểm**. Có một biến
> thể của nó (pivot Việt–Anh) giá trị hơn hẳn phiên bản gốc trong backlog, nhưng
> cả hai đều phải xếp sau ba luật rẻ tiền — vì đo được rằng ba luật đó mới đánh
> trúng chỗ đang tắc.

---

## 0. Tóm tắt điều hành

Ba phát hiện, tất cả đều từ số đo chứ không từ suy luận:

**① Nút thắt hiện tại là CẤU TRÚC, không phải NGỮ NGHĨA.** KB đạt `R@20 = 1,000`
và `R@1 = 0,836`, tức còn đúng **20 ca** xếp sai hạng. Bóc từng ca ra:

| Nhóm | n | Bản chất | Embedding giúp được? |
|---|---|---|---|
| Sai mức phân cấp ICD | 12 | `E10-E14` (khối) trên `E14`; `R03.0` trên `I10` | ✗ — việc của `closure` |
| Nhầm biến thể tiền tố | 4 | `Esomeprazole` trên `omeprazole` | **✗✗ LÀM TỆ HƠN** |
| Sai tầng TTY / dạng bào chế | 3 | `AB "EC TAB"` trên `CD` | ✗ — việc của luật ưu tiên |
| BM25 nhiễu thật | 1 | `amlodipine 10 mg` → `ZANAMIVIR rotadisk` | ✓ |
| Ngữ nghĩa thật | 2 | `"viêm khớp"` (hạng 19), `"co giật"` (hạng 10) | ✓ |

**Chỉ 3/20 ca có lợi từ embedding. 4/20 sẽ bị nó làm hỏng** — `esomeprazole` và
`omeprazole` gần như đồng nhất trong không gian ngữ nghĩa, nên model càng "hiểu"
càng lẫn. Đây chính xác là lớp lỗi mà khớp chuỗi phải thắng.

**② Backlog bỏ sót cầu nối Việt–Anh đã có sẵn.** S1 bản gốc viết *"SNOMED chỉ có
tiếng Anh ⇒ cặp đồng nghĩa là Anh–Anh; vẫn phải bắc cầu Việt→Anh riêng"*. Không
cần bắc thêm: **mã ICD chính là cầu**. 10.144 concept ICD có đồng thời tên tiếng
Việt của BYT và synonym tiếng Anh mượn từ SNOMED. Ghép chéo qua mã cho
**304.611 cặp Việt–Anh** — thứ mà nhánh `CHẨN_ĐOÁN` thực sự cần, chứ không phải
cặp Anh–Anh.

**③ Không đo được nếu không dựng probe set mới.** Với 2 ca ngữ nghĩa còn lại,
không phép đo nào phân biệt nổi cải thiện thật với nhiễu.

### Khuyến nghị

```
Track 0  (rẻ, ~3 ngày, KHÔNG phải S1)  →  đánh trúng 19/20 ca đang tắc
S1.0     (cổng đo)                     →  quyết định S1 có đáng làm không
S1.1–5   (S1 thật)                     →  chỉ chạy nếu S1.0 mở cổng
```

Làm S1 trước Track 0 là bỏ hàng tuần vào thứ nhắm sai đích, đúng loại sai lầm mà
Phase 5 đã trả giá một lần.

---

## 1. Hiện trạng đo được

### 1.1 Baseline

```
── Probe set: 122 cặp ─────────────────────────────────
  lát cắt            n      R@1      R@5     R@20      MRR
  ──────────────────────────────────────────────────────
  TỔNG THỂ         122    0.836    0.975    1.000    0.897
  chẩn đoán → ICD   84    0.857    0.976    1.000    0.911
  thuốc → RxNorm    38    0.789    0.974    1.000    0.867
```

`R@20 = 1,000` nghĩa là **bước truy hồi đã xong việc của nó**. Mọi điểm còn lại
nằm ở bước **xếp hạng**. Điều này trùng khớp với văn liệu: nghiên cứu chuẩn hoá
thuật ngữ tiếng Trung sang ICD đạt coverage 97,9% nhờ synonym KB, còn mức tăng
thật đến từ **BERT re-ranker** (92,1% acc@1) chứ không từ retriever tốt hơn.

> ⚠️ **Đính chính sau khi kiểm trên gold thật (§9).** Con số `R@20 = 1,000` ở
> nhánh THUỐC là **ảo tưởng của probe set**. Trên 11 mention có gold của BTC,
> nhánh thuốc chỉ đạt `R@20 = 0,909` · `R@5 = 0,545` · `R@1 = 0,182`. Kết luận
> "truy hồi đã xong" **chỉ đúng cho nhánh CHẨN_ĐOÁN**, và ngay cả ở đó cũng chưa
> được kiểm bằng gold thật. Xem §9 trước khi dùng bất kỳ con số nào ở mục này.

> **Hệ quả cho toàn bộ tài liệu này:** embedding nếu dùng thì phải dùng làm
> **re-ranker trên top-20**, không phải làm retriever thay BM25. Cách này còn rẻ
> hơn nhiều — nhúng 20 ứng viên/truy vấn thay vì 141.948 concept.

### 1.2 Bóc 20 ca trượt — nhánh CHẨN_ĐOÁN

12 ca, tất cả cùng một hình dạng: **tìm đúng vùng, chọn sai tầng**.

| mention | gold | hạng | đứng trên nó là |
|---|---|---|---|
| tăng huyết áp | `I10` | 2 | `R03.0` — chỉ số HA cao *chưa* chẩn đoán |
| đái tháo đường | `E14` | 2 | `E10-E14` — **khối**, không phải mã |
| suy thận | `N17` | 2 | `N17-N19` — khối |
| thiếu máu tan máu | `D59` | 2 | `D55-D59` — khối |
| đau thắt lưng | `M54.5` | 2 | `M54.56` — con *đặc hiệu hơn* |
| bệnh zona | `B02` | 3 | `B02.3`, `B02.7` — con |
| viêm gan virus B mạn | `B18.1` | 5 | `B18` — cha |

Không ca nào là lỗi hiểu nghĩa. Cả 12 ca là quan hệ **cha / con / anh em / khối**
trên chính cây ICD — mà bảng `closure` (168.451 cặp) **đã dựng xong ở Phase 3**
và hiện chưa được dùng vào việc xếp hạng.

### 1.3 Bóc 20 ca trượt — nhánh THUỐC

8 ca, chia làm ba lớp khác hẳn nhau:

**Lớp A — nhầm biến thể tiền tố (4 ca). Đây là lớp embedding sẽ làm HỎNG.**

| mention | gold | bị vượt bởi |
|---|---|---|
| `omeprazole` | `7646` omeprazol | `283742` **Es**omeprazole |
| `heparin` | `5224` Heparin | `235473` **Porcine** heparin |
| `albuterol` | `435` salbutamol | `237159` **Levo**salbutamol |
| `salbutamol` | `435` salbutamol | `237159` **Levo**salbutamol |

Mẫu số chung: ứng viên sai là một **biến thể đặc hiệu hơn** mà tên của nó *chứa
trọn* truy vấn làm chuỗi con. Đây là lỗi chuẩn hoá độ dài của BM25.

Cần nói rõ vì sao nguy hiểm: `esomeprazole` là đồng phân S của `omeprazole`,
`levosalbutamol` là đồng phân R của `salbutamol`. Về **ngữ nghĩa** chúng gần như
trùng nhau — nên **một embedding y sinh tốt sẽ xếp chúng gần nhau HƠN, không xa
hơn**. Hướng ngữ nghĩa đi ngược lại lời giải ở đây. Lời giải đúng là tín hiệu
**độ phủ chuỗi**: phạt ứng viên có token thừa không khớp truy vấn.

**Lớp B — sai tầng TTY / dạng bào chế (3 ca).**

| mention | gold | bị vượt bởi |
|---|---|---|
| `aspirin 81 mg po daily` | `243670` **CD** | `308416` **AB** "ASPIRIN 81 mg EC TAB" |
| `aspirin 81 MG Oral Tablet` | `243670` **CD** | `308416` **AB** |
| `metoprolol succinate xl 50 mg` | `866436` **AB** | `866438` **BD** |

PRD tab 04 §1.2 đã chốt quy tắc: *"mention có hàm lượng + đường dùng → map về
SCD/SBD"*. Quy tắc đó chưa được cài vào xếp hạng.

**Lớp C — BM25 nhiễu thật (1 ca).** `amlodipine 10 mg po daily` → hạng 1 là
`ZANAMIVIR 5 mg/BLSTR PO INHL ROTADISK KIT`. Khớp trên `mg` / `PO` / chữ số.
Đây là ca duy nhất ở nhánh thuốc mà embedding giúp được thật.

---

## 2. Phát hiện chính — cầu Việt–Anh pivot qua mã ICD

### 2.1 Ý tưởng

Backlog coi SNOMED là máy sinh cặp **Anh–Anh**:

```
mọi synonym của các concept SNOMED cùng map về một mã ICD
        ⇒ đều là positive pair của nhau            ← bản gốc: Anh–Anh
```

Nhưng KB Phase 3 đã có sẵn vế thứ hai: mỗi mã ICD còn mang **tên tiếng Việt
chính thức của BYT**. Nối hai vế qua mã:

```
   tên VI của BYT  ──┐
                     ├── cùng mã ICD ──⇒ positive pair  (VIỆT–ANH)
   synonym EN SNOMED ┘
```

### 2.2 Số đo

| | |
|---|---|
| concept ICD có **cả** term VI-authoritative và term EN từ SNOMED | **10.144** |
| tổng cặp Vi–En sinh được (chưa lọc) | **304.611** |
| SNOMED term/concept | trung vị 8 · p90 36 · max 180 |

### 2.3 Vì sao vế này mới là vế đáng giá

Probe set: 84/122 là mention chẩn đoán, trong đó **72 có dấu tiếng Việt**. Cặp
Anh–Anh của S1 bản gốc phục vụ được 38 ca thuốc + ~12 mention viết tắt ASCII —
mà nhánh thuốc thì Lớp A ở §1.3 nói rõ là embedding *có hại*. Cặp **Việt–Anh**
nhắm thẳng vào 72 ca còn lại.

Văn liệu ủng hộ đúng hình dạng này. BioELX (2026) chỉ ra đích danh điểm yếu:
retriever kiểu SapBERT huấn luyện trên alias *chủ yếu tiếng Anh* thì tổng quát
hoá kém sang mention ngoài tiếng Anh — và cách sửa của họ là **bổ sung alias đa
ngữ vào dữ liệu huấn luyện**, đúng việc §2.1 làm. Tiền lệ gần nhất: Fierens
(2025) huấn luyện SapBERT trên bản dịch máy tiếng Pháp của UMLS và **vượt
Cross-lingual SapBERT** trên QuaeroFrenchMed.

Ta còn ở thế tốt hơn họ một bậc: phía tiếng Việt là **tên chính thức do BYT ban
hành**, không phải dịch máy.

### 2.4 Cảnh báo: Vietnamese KHÔNG có trong XL-BEL

XL-BEL phủ 10 ngôn ngữ — EN, ES, DE, FI, RU, TR, KO, ZH, JA, TH. **Không có
tiếng Việt.** Nên:

- không có checkpoint XL-BEL nào đã được kiểm chứng cho tiếng Việt;
- khuyến nghị "XL-BEL" ở PRD §4 và ở backlog S4 phải đọc là *"kiến trúc XL-BEL"*,
  không phải *"model XL-BEL tải về dùng ngay"*;
- mọi năng lực tiếng Việt phải đến từ **base model đa ngữ** cộng với cặp Vi–En
  ta tự sinh.

---

## 3. Chất lượng dữ liệu sinh ra — đo bằng mắt

Lấy mẫu ngẫu nhiên theo từng dải fan-in (`seed=0`):

| fan-in | ví dụ đại diện | đánh giá |
|---|---|---|
| **1** | *Viêm da đầu chi teo mãn tính* ↔ *Acrodermatitis chronica atrophicans* | ✅ chất lượng bản dịch |
| **1** | *Nhiễm độc Nitrogen oxid* ↔ *Nitrogen oxides causing toxic effect* | ✅ song song thật |
| **≤5** | *Hội chứng MacLeod* ↔ *Emphysema of left lung* | ⚠️ liên quan, không đồng nghĩa |
| **≤5** | *Viêm da cơ địa, không xác định* ↔ *Adult atopic eczema commencing in adult life* | ⚠️ hạ danh |
| **≤20** | *Dị tật **hẹp** van hai lá* ↔ *Mitral **atresia*** | ❌ **sai nghĩa** (teo ≠ hẹp) |
| **≤50** | *Phơi nhiễm không khí cao áp* ↔ *Face mask squeeze* | ❌ vô nghĩa |
| **≤50** | *U ác tính thứ phát, không xác định vị trí* ↔ *Metastatic ganglioneuroblastoma* | ❌ mã gom |

Chất lượng rơi từ "bản dịch" xuống "sai nghĩa" trong khoảng fan-in 5–20.

### 3.1 Bộ lọc thứ hai, độc lập với fan-in

Thủ phạm lặp lại là **mã gom**: tên tiếng Việt chứa *"không xác định"*, *"khác"*,
*"không đặc hiệu"*, *"nơi khác"*. Regex trên tên VI bắt được lớp này.

Quan trọng: nó **gần như trực giao với fan-in**, nên không thừa —

```
fan-in trung bình của mã GOM      : 32,6 term/concept
fan-in trung bình của mã ĐẶC HIỆU : 26,9 term/concept
```

3.550/10.144 concept (35%) là mã gom, nuốt 115.701 term (39%). Nếu chỉ chặn bằng
fan-in thì phần lớn số này lọt.

### 3.2 Kích thước corpus theo cấu hình lọc

| cấu hình | concept | cặp Vi–En |
|---|---|---|
| `fan_in ≤ 1` + bỏ mã gom | 1.375 | 5.226 |
| `fan_in ≤ 3` + bỏ mã gom | 2.818 | 18.255 |
| **`fan_in ≤ 5` + bỏ mã gom** | **3.698** | **32.028** |
| `fan_in ≤ 10` + bỏ mã gom | 4.796 | 62.146 |
| `fan_in ≤ 50` (không lọc gì) | 10.144 | 283.389 |

**Đề xuất chốt: `fan_in ≤ 5` + bỏ mã gom → 32.028 cặp.**

### 3.3 ★ Rủi ro lớn nhất của corpus này: nó chỉ phủ 21% ICD

3.698 concept trên tổng 17.240 = **21,4%**. Và đó không phải mẫu ngẫu nhiên —
theo đúng định nghĩa bộ lọc, nó **thiên lệch về mã đặc hiệu, fan-in thấp**.
Fine-tune trên nó có thể làm model tốt lên ở 21% và **tệ đi ở 79% còn lại**.

Đây đúng là kịch bản E2/E4 của Phase 3: nạp thêm dữ liệu, chỉ số tụt. Nên cổng
hiệu quả ở §5 phải đo **cả phần không được phủ**, không chỉ phần được phủ.

So sánh quy mô để giữ tỉnh táo: SapBERT huấn luyện trên **4M+ concept UMLS**.
32K cặp là ít hơn hai bậc độ lớn. Đây là **fine-tune hẹp**, không phải
self-alignment pretraining — kỳ vọng phải đặt tương ứng, và nguy cơ *catastrophic
forgetting* là có thật.

---

## 4. Chi phí tính toán — đo thật, không ước

Benchmark trên chính máy này (M3 Pro, 18 GB unified, MPS, **không CUDA**), model
kích thước BERT-base (109M tham số, đúng cỡ SapBERT), seq len 25:

| batch | ms/step | thông lượng |
|---|---|---|
| 32 | 366 | 87 cặp/s |
| 64 | 348 | 184 cặp/s |
| 128 | 684 | 187 cặp/s |

⇒ **32.028 cặp ≈ 2,9 phút/epoch. 304.611 cặp ≈ 27 phút/epoch.**

Tính toán **không phải rào cản** — kết luận quan trọng, vì nó nghĩa là chi phí
thật của S1 nằm ở *gán nhãn probe set* và *rủi ro hồi quy*, không ở GPU.

Một lưu ý kỹ thuật: thông lượng bão hoà từ batch 64, tức MPS bị chặn bởi compute
chứ không bởi băng thông. SapBERT gốc dùng batch 512 để có nhiều negative
trong-batch; ở đây tăng batch gần như miễn phí về thời gian, chỉ tốn bộ nhớ.

---

## 5. Kế hoạch

### Track 0 — ba luật xếp hạng *(làm trước, KHÔNG thuộc S1)*

Không thuộc S1 nhưng phải nêu, vì nó là lý do S1 bị xếp sau.

| # | Luật | Nhắm | Vốn đã có |
|---|---|---|---|
| **R1** | Phạt ứng viên là **khối/cha/con** khi mention khớp mức khác | 12 ca ICD | bảng `closure` Phase 3 |
| **R2** | Ưu tiên **độ phủ chuỗi**: phạt token thừa của ứng viên | 4 ca Lớp A | `normalize/` |
| **R3** | Ưu tiên **TTY** theo dạng mention (có hàm lượng+đường dùng → CD/SCD/SBD) | 3 ca Lớp B | `term_type` đã nạp |

Ước lượng: 19/20 ca hiện trượt nằm trong tầm ba luật này. Chi phí ~3 ngày, không
model, không huấn luyện, không rủi ro tái lập.

**Đây là việc nên làm ngay.** S1 chỉ có nghĩa sau khi ba luật này đã ăn hết phần
dễ và lộ ra phần khó thật sự còn lại là gì.

---

### S1.0 — Cổng đo *(bắt buộc, quyết định làm tiếp hay dừng)*

Không có bước này thì S1 không thể chứng minh được gì — lặp lại đúng lỗi Phase 5.

**Làm gì:** mở rộng probe set lên ~300 cặp chẩn đoán, rút từ `data/test/`.

**Ràng buộc chống thiên lệch — điều kiện sống còn của phép đo:**

> Mention phải chọn bằng tiêu chí **độc lập với kết quả retrieval**: lấy mẫu
> ngẫu nhiên phân tầng theo chương ICD và theo thể loại văn bản. **Tuyệt đối
> không** chọn mention bằng cách "tìm ca BM25 trượt" — làm vậy là dựng test set
> đối kháng với chính baseline, và mọi cải thiện đo được sau đó đều là ảo.

**Cổng mở/đóng:** chạy lại eval **sau Track 0** trên probe set mới. Đếm tỉ lệ ca
trượt còn lại thuộc loại **ngữ nghĩa** (mention không chung token với mọi tên của
mã đúng, và không phải lỗi phân cấp/TTY).

| kết quả | quyết định |
|---|---|
| ngữ nghĩa < 15% số ca trượt | **DỪNG S1.** Ghi kết quả âm. Đầu tư vào re-rank luật/LLM |
| ngữ nghĩa ≥ 15% | mở cổng, sang S1.1 |

---

### S1.1 — Sinh corpus Vi–En

- Pivot qua mã ICD như §2.1.
- Lọc: `fan_in ≤ 5` **và** bỏ mã gom (§3.1) **và** bỏ concept chương/khối.
- Bổ sung cặp **Anh–Anh** từ chính SNOMED (bản S1 gốc) làm *regularizer* chống
  quên, không phải làm tín hiệu chính.
- **Đóng băng** thành `data/curated/s1_pairs.vN.jsonl`, commit vào git, ghi
  `sha256` — theo đúng kỷ luật E5 ở §P3.6 (không gọi gì lúc build).

**Cổng:** duyệt tay **100 cặp ngẫu nhiên**; ≥ 90 cặp phải là đồng nghĩa hoặc bản
dịch chấp nhận được. Dưới ngưỡng → siết bộ lọc, không huấn luyện.

---

### S1.2 — Chọn base model *(đo trước, huấn luyện sau)*

Vì tiếng Việt không có trong XL-BEL (§2.4), phải bắt đầu từ base **đa ngữ**:

| ứng viên | lý do |
|---|---|
| `BioLORD-2023-M` | đa ngữ + y sinh — khớp nhất về lý thuyết |
| `multilingual-e5-base` | retrieval đa ngữ mạnh, không chuyên y |
| `SapBERT` (đối chứng) | chỉ tiếng Anh — dùng để *chứng minh* giới hạn |

**Bước này chạy zero-shot trước, chưa huấn luyện gì.** Rất có thể phần lớn mức
tăng của Phase 5 nằm ở đây: Phase 5 thất bại vì
`paraphrase-multilingual-MiniLM-L12-v2` — đa ngữ nhưng **đa dụng**. Đổi sang một
base đa ngữ *y sinh* là thay đổi rẻ nhất có thể đo.

> Nếu zero-shot BioLORD-M đã đủ, S1.3 có thể không cần chạy. Đây là kết quả tốt
> chứ không phải thất bại — và phải đo trước khi bỏ công fine-tune.

---

### S1.3 — Fine-tune, dùng làm **re-ranker**

- **Vai trò:** re-rank top-20 của BM25. Không thay retriever (§1.1).
- **Loss:** multi-similarity + online hard mining (công thức SapBERT).
- **Hard negative — chỗ dùng lại `closure`:** lấy **anh em ruột dưới cùng mã
  cha** làm negative. Đây đúng là lớp ca đang trượt (`K21.0` vs `K21.9`,
  `E10` vs `E11`), và `closure` đã dựng sẵn để truy trong `O(log n)`.
- **Chống quên:** LoRA hoặc LR thấp + ít epoch. Corpus chỉ phủ 21% ICD (§3.3),
  full fine-tune rất dễ phá phần còn lại.
- **Tái lập:** ghim seed, ghim revision base model, ghi `content_sha256` của
  corpus vào metadata checkpoint — cùng cơ chế `IndexOutOfSync` của Phase 5.

Chi phí đo được: ~3 phút/epoch (§4).

---

### S1.4 — Cổng hiệu quả *(theo đúng kỷ luật Phase 3/5)*

Bắt buộc pass **toàn bộ**, nếu không thì bỏ và ghi kết quả âm:

- [ ] `R@1` trên probe set **mới** tăng ≥ 3 điểm tuyệt đối so với sau-Track-0
- [ ] **`R@20` không giảm** — re-ranker không được đánh rơi ứng viên đúng
- [ ] **4 ca Lớp A không hồi quy** (`omeprazole`, `heparin`, `albuterol`,
      `salbutamol`). Đây là cổng chống đúng thứ §1.3 cảnh báo. Nếu Lớp A tụt
      thì luật R2 phải thắng embedding ở nhánh thuốc — cấu hình cuối là *lai*.
- [ ] Đo **tách riêng** trên 21% concept được corpus phủ và 79% không được phủ.
      Nếu phần 79% tụt → corpus thiên lệch, phải mở rộng hoặc bỏ.
- [ ] Ablation: base zero-shot / +Vi–En / +Vi–En +Anh–Anh / +hard negative
- [ ] Toàn bộ đo lại được từ máy sạch, không gọi mạng

---

## 6. Rủi ro

| Rủi ro | Mức | Cách chặn |
|---|---|---|
| **Làm S1 trước Track 0** → hàng tuần công cho 3/20 ca | **Cao** | Thứ tự ở §5; S1.0 là cổng cứng |
| Corpus phủ 21% ICD, thiên lệch mã đặc hiệu | **Cao** | Cổng đo tách 21%/79% ở S1.4 |
| Embedding làm hỏng Lớp A (đồng phân) | **Cao** | Cổng chống hồi quy 4 ca; cấu hình lai |
| Catastrophic forgetting (32K cặp vs 4M của SapBERT) | Trung bình | LoRA, LR thấp, regularizer Anh–Anh |
| Probe set mới chọn thiên lệch → cải thiện ảo | **Cao** | Ràng buộc lấy mẫu mù ở S1.0 |
| Cặp "cùng mã" ≠ "đồng nghĩa" | Trung bình | Xem §7 — có chủ đích, nhưng phải chặn mã gom |
| Model weights phá tái lập (PRD §8) | Cao | Ghim seed/revision, đóng gói weights, `content_sha256` |

---

## 7. Một điểm lý thuyết cần nói rõ

Cặp sinh ra ở §2.1 là quan hệ **"cùng mã ICD"**, không phải **"đồng nghĩa"**.
SapBERT dùng cùng-CUI của UMLS, mà CUI *là* một khái niệm; mã ICD thì là một
**lớp** gom nhiều khái niệm.

Điều này thoạt nhìn là khiếm khuyết, nhưng với bài toán này nó **đúng có chủ
đích**: đề bài chấm việc trả về *mã*, không phải *khái niệm*. Kéo mọi cách diễn
đạt của một lớp ICD về gần nhau chính là mục tiêu, không phải tác dụng phụ.

Nó chỉ sai khi bản thân lớp đó **không nhất quán về ngữ nghĩa** — tức mã gom. Và
đó chính là lý do bộ lọc §3.1 không phải tuỳ chọn mà là **điều kiện để cách đặt
bài này đứng vững**.

---

## 8. Việc cần làm khi cầm lên

1. **Track 0** — ba luật R1/R2/R3 (§5). Không phụ thuộc gì ở đây.
2. **S1.0** — probe set ~300 cặp, lấy mẫu mù. Đo lại. **Cổng go/no-go.**
3. Nếu cổng mở: S1.1 sinh corpus → duyệt tay 100 cặp
4. S1.2 đo zero-shot 3 base model — có thể dừng ở đây nếu đã đủ
5. S1.3 fine-tune làm re-ranker, hard negative lấy từ `closure`
6. S1.4 cổng hiệu quả; không đạt thì **bỏ và ghi kết quả âm** vào `docs/reports/`

---

## 9. Kiểm chứng trên gold thật *(`sample_input.txt` / `sample_output.json`)*

Mẫu này là **gold đầu tiên của dự án** — 19 mục, trong đó **11 THUỐC** có
`candidates` và **0 CHẨN_ĐOÁN**. Nên nó kiểm được nhánh thuốc rất chặt và **không
kiểm được gì** ở nhánh chẩn đoán.

### 9.1 Trước hết: file gold lệch offset 19/19

Không mục nào có `position` trỏ đúng vào `sample_input.txt`. Lệch tăng đều **+2
mỗi mục danh sách**. Tái dựng được chính xác:

```
tách mục bằng " \r\n" (dấu cách + CRLF)  →  khớp 19/19
tách mục bằng "\r\n" / "\n\n" / " \n"    →  khớp  0/19
```

Bản gốc là danh sách đánh số, **mỗi dòng kết thúc bằng dấu cách rồi CRLF**. File
`.txt` hiện tại đã bị làm phẳng thành một dòng, nên mọi offset sau mục 1 lệch dần.

Không phải lỗi Unicode: `NFC == bản gốc`, và `len` theo NFD/UTF-16/UTF-8 đều
không khớp `position`.

> **Hệ quả vượt ra ngoài tài liệu này.** PRD §8 xếp *"position lệch do
> Unicode/khoảng trắng"* vào checklist rủi ro. Ca thật đầu tiên gặp phải lại do
> **CRLF**, không do Unicode. Python mặc định bật universal-newline: đọc file
> CRLF bằng `open(f)` sẽ biến `\r\n` → `\n` và **mọi `position` sau dòng 1 lệch
> 1 ký tự mỗi dòng** — âm thầm, không lỗi. Phải đọc bằng
> `open(f, newline='')` hoặc `Path.read_bytes()`.
>
> Đây là lớp lỗi ăn điểm cả `text_score` (0.3) lẫn tính hợp lệ của `position`.
> Đáng ưu tiên hơn toàn bộ S1.

### 9.2 Nhánh THUỐC — probe set đã nói dối

| | probe set (38 ca) | **gold thật (11 ca)** |
|---|---|---|
| R@1 | 0,789 | **0,182** |
| R@5 | 0,974 | **0,545** |
| R@20 | 1,000 | **0,909** |

Probe set **thổi phồng nghiêm trọng**. Nguyên nhân: probe dùng phần lớn là tên
hoạt chất trần (`omeprazole`, `heparin`), còn mention thật là chuỗi kê đơn đầy đủ
(`guaifenesin ml po q6h:prn`).

### 9.3 ★ Bug tìm được: token `po` là "hố hút"

`759471` (zanamivir ROTADISK) đứng **hạng 1 cho ba truy vấn không liên quan**
(amlodipine, guaifenesin, clonazepam). Lý do nằm ở `norm_term`:

```
zanamivir 5 mg/blstr po inhl rotadisk kit
                     ↑↑
```

`po` là **đường dùng** trong mention nhưng là **token thật** trong tên thuốc viết
tắt kiểu VA/MMSL. Vì `po` hiếm trong index nên IDF rất cao ⇒ mọi mention đơn
thuốc (đều chứa "po") bị hút về nhóm này. Cùng cơ chế với `inhl`, `ud`, `ml`.

Đây là **bug chuẩn hoá**, không phải giới hạn ngữ nghĩa — và nó đắt hơn mọi thứ
trong S1.

### 9.4 Thí nghiệm quyết định: Track 0 có cứu được gold thật không

Cài thử R2 (độ phủ token, phạt token thừa) × R3 (ưu tiên TTY) — **~30 dòng, không
ML**, re-rank trên chính top-20 của BM25:

| | trước | sau |
|---|---|---|
| R@1 | 0,182 | **0,636** |
| R@5 | 0,545 | **0,818** |
| MRR | 0,363 | **0,710** |
| R@20 | 0,909 | 0,909 |

**+45,5 điểm R@1.** 7/11 ca cải thiện, 1 ca hồi quy.

Một kết quả âm đáng ghi: **lần cài đầu làm R@1 tụt về 0,000**. Nguyên nhân là
R2 chạy một mình: `"aspirin 81 mg"` khớp *hoàn hảo* với SCDC `315431`
(đúng "aspirin 81 mg", không dạng bào chế) nên độ phủ token đẩy **SCDC lên trên
SCD**. Chỉ khi nhân với TTY prior thì mới đúng.

> Bài học: **R2 và R3 không cộng được, chúng phải nhân.** Độ phủ token một mình
> là tín hiệu *phản tác dụng* ở nhánh thuốc, vì tầng SCDC bao giờ cũng khớp
> chuỗi tốt hơn tầng SCD mà đề bài chấm.

### 9.5 Kế hoạch được xác nhận / bị bác bỏ ở đâu

| Luận điểm | Phán quyết |
|---|---|
| Nút thắt nhánh thuốc là **cấu trúc**, không phải ngữ nghĩa | ✅ **xác nhận mạnh** — 9/9 ca trượt là TTY, dạng bào chế, token hút, hoặc gold bất nhất. Không ca nào là "model không hiểu nghĩa" |
| Embedding **không** cứu được nhánh thuốc | ✅ xác nhận — đối thủ của gold là `Delayed Release Oral Tablet` vs `Oral Tablet`, `Oral Capsule` vs `Oral Tablet`: gần như đồng nhất về ngữ nghĩa, embedding chỉ làm mờ thêm |
| Track 0 rẻ và đánh trúng | ✅ xác nhận — +45,5 điểm R@1, không ML |
| "Truy hồi đã xong, chỉ còn xếp hạng" | ❌ **bác bỏ ở nhánh thuốc** — R@20 thật là 0,909 |
| Luật R3 dạng *"có hàm lượng+đường dùng → SCD/SBD"* | ⚠️ **phải sửa** — gold `nystatin oral suspension 5 ml` lại là `7597` = **IN** (hoạt chất), dù mention có đủ dạng bào chế. Luật cứng sẽ sai ca này |
| S1 (cặp Vi–En, nhánh CHẨN_ĐOÁN) | ⬜ **chưa kiểm được** — mẫu có 0 mục CHẨN_ĐOÁN |

### 9.6 Ba ca còn trượt sau Track 0 — và không ca nào cần embedding

1. **`guaifenesin ml po q6h:prn`** → gold `392085` = *guaifenesin 800 mg Oral
   Tablet*. Mention **không có hàm lượng**, gold lại chọn một hàm lượng cụ thể.
   Gần như không thắng được bằng bất kỳ retriever nào.
2. **`nystatin oral suspension 5 ml po qid:prn`** → gold `7597` = **IN**. Truy hồi
   trả `312055` *nystatin 100000 UNT/ML Oral Suspension* ở hạng 1 — khớp mention
   **sát hơn cả gold**. Đây là bất nhất về mức chi tiết của gold.
3. **`aspirin 81 mg po daily`** → đối thủ là *Delayed Release* và *Chewable* cùng
   81 mg. Mention không nói gì về dạng giải phóng.

Ca 1 và 2 cho thấy một rủi ro **không sửa được bằng kỹ thuật**: với mention thiếu
thông tin, mức chi tiết của gold không suy ra được từ mention. Vì `candidates`
chấm bằng Jaccard, hedging 2 mã sẽ hạ điểm còn một nửa — nên chiến lược đúng vẫn
là trả **1 mã**, và chấp nhận mất lớp ca này.

### 9.7 Việc phải thêm vào đầu hàng đợi

| # | Việc | Bằng chứng | Trạng thái |
|---|---|---|---|
| **P0** | Đọc file bằng `newline=''`; test bất biến offset trên CRLF | §9.1, 19/19 lệch | ✅ `stages/textio.py` |
| **P1** | Bóc token đường dùng/tần suất khỏi truy vấn thuốc | §9.3 | ✅ `normalize/sig.py` |
| **P2** | Track 0 = R2 × R3 (**nhân**, không cộng) | §9.4 | ✅ `query/rerank.py` |
| ~~P3~~ | ~~Sửa `is_preferred`~~ — **không phải bug**: `concepts.pref_en` đúng (`7597` → `"nystatin"`). `terms.is_preferred` toàn 0 với RxNorm nên câu truy vấn hiển thị của tôi trả hàng tuỳ ý | — | ❌ rút lại |
| **P4** | Gán gold cho **CHẨN_ĐOÁN** rồi mới xét S1 | §9.5 dòng cuối | ✅ `data/probe/gold` — **cổng ĐÓNG**, xem §9ter |

---

## 9bis. Track 0 — đã triển khai, kết quả đo

### Kết quả trên BA bộ đo độc lập

| bộ | lát cắt | R@1 trước | R@1 **sau** | R@20 sau |
|---|---|---|---|---|
| **gold lâm sàng** (114) | tổng | 0,684 | **0,816** | **1,000** |
| | chẩn đoán (48) | 0,354 | **0,562** | **1,000** |
| | thuốc (66) | 0,924 | **1,000** | 1,000 |
| **gold BTC** (11) | thuốc | 0,182 | **0,636** | 0,909 |
| **probe tự gán** (122) | tổng | 0,836 | **0,951** | 1,000 |
| | chẩn đoán (84) | 0,857 | **0,952** | 1,000 |
| | thuốc (38) | 0,789 | **0,947** | 1,000 |

Nhánh thuốc trên gold lâm sàng đạt **R@1 = 1,000** — 66/66. Nhánh chẩn đoán
`R@20` từ 0,833 lên **1,000**: re-rank ở đây *thật sự mở rộng* tập ứng viên chứ
không chỉ đổi thứ tự, nhờ pool sâu.

`329 test pass` · `ruff` sạch · `validate` 20/20 rule + 30/30 smoke.

### Nhánh CHẨN_ĐOÁN — đối xứng với nhánh thuốc

Mọi ca trượt ICD cùng một hình dạng: gold là mã `.9` *"không xác định"*, truy hồi
trả **mã cha** 3 ký tự.

```
mention "viêm phổi"
  J18    "Viêm phổi"                  → F1 = 1,00   ← thắng oan
  J18.9  "Viêm phổi, không xác định"  → F1 = 0,57   ← nhưng đây mới là gold
```

Mã `.9` bị vế precision phạt oan vì mang bổ ngữ mà mention không bao giờ chứa.
`canonical_term()` bóc bổ ngữ đó trước khi tính F1. Cộng thêm dìm mã khoảng
(`E10-E14` không bao giờ là đáp án).

**Pool phải sâu theo nhánh, không dùng chung một số:**

| | pool 20 | pool 60 |
|---|---|---|
| ICD (gold lâm sàng) | R@20 0,857 | **R@20 1,000** |
| thuốc (gold BTC) | **R@20 0,909** | R@20 0,818 |

Mã `.9` nằm ở **hạng 21–26** nên ICD cần pool sâu. Nhánh thuốc thì ngược — đáp
án vốn đã trong top-20, nới pool chỉ rước nhiễu.

### Luật cha/con — đã đo, và BỎ

Sau Track 0, 8 ca còn trượt đều là gold `.9` nằm **đúng hạng 2**, ngay dưới mã
cha. Cám dỗ hiển nhiên: "top-1 là cha của top-2 thì đảo chỗ". Đo:

| | THẮNG | THUA |
|---|---|---|
| gold lâm sàng (48) | 9 | **14** |
| probe (84) | 0 | **46** |

Probe dùng mention ở mức nhóm (`"đái tháo đường"`, `"suy thận"`) nên **mã cha**
mới là đáp án; gold lâm sàng dùng chẩn đoán xác định nên nghiêng về `.9`. Một
luật cứng không phục vụ được cả hai — đây là ranh giới thật của phương pháp
không-học, và cũng là chỗ **duy nhất** trong toàn bộ khảo sát mà một model có
thể có đất diễn: nó cần đọc *ngữ cảnh câu*, không phải *nghĩa của mention*.

`TestKhongCaiLuatChaCon` khoá kết quả âm này lại để không ai cài lại.

### Cổng chống hồi quy Lớp A — ĐẠT

Bốn ca đồng phân từng được nêu là "embedding sẽ làm hỏng":

| mention | trước | sau |
|---|---|---|
| `omeprazole` | 2 | **1** |
| `albuterol` | 2 | **1** |
| `salbutamol` | 2 | **1** |
| `heparin` | 2 | 2 |

3/4 cải thiện, 0 hồi quy. Khớp chuỗi thắng đúng chỗ hướng ngữ nghĩa sẽ thua.

### Ba điều học được khi cài thật

**① `has_strength` quyết định tầng đáp án — và `ml` không phải hàm lượng.**
Prior TTY cứng không thể đúng cho cả hai mention của cùng một hoạt chất:

```
"docusate sodium"               → 71722   PIN, hoạt chất
"docusate sodium 100 mg po bid" → 1099279 SCD, thuốc kê đơn
```

Nên prior chọn theo mention: có hàm lượng → SCD/SBD, không có → IN/PIN. Cài
prior cứng làm `docusate sodium` tụt 1 → 3; tách bảng thì hết.

`ml` cố ý **không** tính là hàm lượng — nó là thể tích liều, không nói hoạt chất
bao nhiêu.

**② `%` làm hỏng regex hàm lượng.** `\d\s*(…|%)\b` không khớp `"cream 2 %"`: `%`
không phải ký tự chữ nên `\b` phía sau không bao giờ đúng ở cuối chuỗi. Phải
tách `%` ra khỏi nhánh có `\b`. Unit test bắt được, không phải lúc chấm điểm.

**③ Test hợp đồng làm đúng việc của nó.** Thêm tham số `rerank` vào
`search_lexical` khiến `test_query_api.py` đỏ ngay — buộc phải khai báo thay đổi
API thay vì lặng lẽ nới bề mặt công khai.

### Ca còn trượt — không ca nào cần embedding

| mention | hạng | vì sao |
|---|---|---|
| `guaifenesin ml po q6h:prn` | — | mention **không có hàm lượng**, gold lại là SCD 800 mg cụ thể |
| `nystatin oral suspension 5 ml po qid:prn` | 13 | gold là **IN**, nhưng SCD `nystatin 100000 UNT/ML Oral Suspension` khớp mention **sát hơn cả gold** (F1 0,73 vs 0,33) |
| `aspirin 81 mg po daily` | 2 | đối thủ là `Delayed Release` cùng 81 mg; mention không nói gì về dạng giải phóng |

Không chỉnh prior để ép `nystatin` qua: đó là fit vào **n = 1** và sẽ phá
`docusate`. Ba ca này thuộc lớp *mức chi tiết của gold không suy ra được từ
mention* — giới hạn của bài toán, không phải của phương pháp.

### ⚠️ `rerank` mặc định TẮT

Giữ hợp đồng API §4.2 không đổi hành vi dưới chân code đã viết. **Pipeline giải
bài bắt buộc phải truyền `rerank=True`** — quên là mất 45 điểm R@1.

---

## 9ter. Cổng S1.0 — phán quyết

Cổng đặt ra ở §5: *"chạy lại eval **sau Track 0**; nếu ca trượt thuộc loại ngữ
nghĩa < 15% thì DỪNG S1"*. Giờ đã có `data/probe/gold` (48 mention chẩn đoán gán
tay, 0 lệch offset, 100% mã có trong KB) để trả lời.

**Phân loại 13 ca trượt ICD trước Track 0:**

| nguyên nhân | n | embedding cứu được? |
|---|---|---|
| gold là mã `.9`, truy hồi trả mã cha | 8 | ✗ — `canonical_term` |
| mã khoảng `E10-E14` chen lên | 2 | ✗ — prior mã khoảng |
| anh em ruột (`E78.4` trên `E78.5`) | 2 | ✗ — độ phủ token |
| tên đồng nghĩa (`M06` trên `M05`) | 1 | ~ |
| **ngữ nghĩa thuần** | **0** | — |

**0/13 — dưới ngưỡng 15%. Cổng ĐÓNG.**

Track 0 nâng chẩn đoán `R@1` 0,354 → 0,562 và `R@20` 0,833 → **1,000** mà không
dùng một tham số học nào. Điều S1 nhắm tới — *mention không chung token với tên
chuẩn* — **không xuất hiện lần nào** trong 48 mention gán tay này.

> Đây là lần thứ **ba** dữ liệu nói cùng một điều: nút thắt của bài này là *cấu
> trúc bộ mã*, không phải *hiểu ngôn ngữ*. Phase 5 (dense) đã trả giá một lần vì
> đoán ngược lại.

**Điều kiện để mở lại cổng:** một bộ mention có mention dân dã/viết tắt thật
(`"đi tiêu ra máu"`, `THA`, `ĐTĐ`) mà Track 0 vẫn trượt. Gold hiện tại là bệnh án
viết chuẩn nên không chứa lớp đó. Nếu tập test thật của BTC có nhiều văn bản
hỏi–đáp/blog như `1.txt`/`100.txt` mà PRD §7 mô tả, lớp đó sẽ xuất hiện — khi ấy
đo lại, đừng suy đoán trước.

---

## 10. Nguồn

- [BioELX: Cross-lingual BEL via Alias-based Retrieval and LLM Ranking](https://consensus.app/papers/details/da37d3b92e8a525ca004fd1434d48f1b/) (Wang et al., 2026) — retriever SapBERT huấn luyện trên alias tiếng Anh tổng quát hoá kém sang mention ngoài tiếng Anh; bổ sung alias đa ngữ là cách sửa
- [Learning Domain-Specialised Representations for Cross-Lingual BEL (XL-BEL)](https://consensus.app/papers/details/69c00a41f0d75b6abea5c1271e1b6cb0/) (Liu et al., ACL 2021) — 10 ngôn ngữ, **không có tiếng Việt**
- [Translating UMLS Concepts to Improve Medical Entity Linking in French](https://consensus.app/papers/details/d17b56a305095c44bf399fe973d3bbbc/) (Fierens et al., 2025) — tiền lệ gần nhất cho pivot ngôn ngữ
- [A study of entity-linking methods for normalizing Chinese diagnosis terms to ICD codes](https://consensus.app/papers/details/2cf7a9d91a1a5983b0c970fef836f8fa/) (Wang et al., JBI 2020) — coverage 97,9% nhờ synonym KB; mức tăng đến từ **re-ranker**
- [SapBERT](https://arxiv.org/abs/2010.11784) (Liu et al., NAACL 2021) — multi-similarity loss + online hard mining
- [ClinLinker](https://arxiv.org/html/2404.06367v1) · [BioLORD](https://arxiv.org/abs/2210.11892)

Số đo trong tài liệu này lấy từ `data/artifacts/kb.sqlite` (Phase 3,
`content_sha256` xem `manifest.json`) và benchmark chạy trực tiếp trên máy dev
ngày 2026-08-01.
