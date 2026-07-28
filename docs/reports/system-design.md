# System Design — Smart Medic

**Ngày:** 25/07/2026 · **Trạng thái:** đề xuất, chưa triển khai
**Căn cứ:** [`2026-07-25-phan-tich-du-lieu.md`](./2026-07-25-phan-tich-du-lieu.md) · [`ke-hoach-v0-v3.md`](./ke-hoach-v0-v3.md)

---

## 1. Yêu cầu

### 1.1 Chức năng

| # | Yêu cầu |
|---|---|
| FR1 | Đọc `.txt` UTF-8 free-form tiếng Việt → xuất `.json` là list concept |
| FR2 | Phát hiện span kèm `[start, end]` **chính xác trên chuỗi thô** |
| FR3 | Phân loại vào 5 type |
| FR4 | Suy luận 3 assertion (`isNegated`, `isFamily`, `isHistorical`) |
| FR5 | Ánh xạ `CHẨN_ĐOÁN`→ICD-10, `THUỐC`→RxNorm |
| FR6 | Đóng gói `output.zip` đúng cấu trúc BTC quy định |

### 1.2 Phi chức năng — xếp theo mức chi phối kiến trúc

| # | Yêu cầu | Vì sao ở vị trí này |
|---|---|---|
| **NFR1** | **Reproducible** — BTC chạy lại được từ máy sạch trên private test | **Ràng buộc cứng nhất.** Không cài lại được = **bị loại**. Đây là mất trắng, không phải mất điểm. Nó chi phối kiến trúc mạnh hơn cả độ chính xác |
| NFR2 | Chạy **offline hoàn toàn** ở chế độ nộp bài | Hệ quả trực tiếp của NFR1. API đóng không tái lập được ở máy BTC |
| NFR3 | **Determinism** — cùng input cho cùng output | Không có determinism thì không đo được cải tiến, và BTC chạy ra số khác ta |
| NFR4 | **Degradation, không crash** | Một file lỗi không được làm hỏng 99 file còn lại |
| NFR5 | **Provenance** — mọi mã truy được về một dòng cụ thể trong KB | Chống LLM bịa mã; là công cụ debug chính khi không có nhãn vàng |
| NFR6 | Throughput | **Không phải bài toán scale**: 100 file × ~2k ký tự. Nhưng private test có thể lớn hơn → thiết kế tuyến tính, có resume |

### 1.3 Ràng buộc

- **0 nhãn train** → zero-shot. Không có supervised learning ở v0–v2.
- Đội nhỏ, thời gian giới hạn → ưu tiên thứ chắc chắn hơn thứ tối ưu.
- **Công thức `candidates_score` chưa chốt** → không hard-code theo metric; mọi lựa chọn phụ thuộc metric phải là **config**, không phải code.
- **KB có nguy cơ lệch phiên bản** (mã `360047` retire 2019) → tầng ánh xạ mã phải đảo chiều được mà không build lại index.

> **Nguyên tắc chi phối toàn bộ thiết kế:** *reproducibility > accuracy*. Bất cứ khi nào hai thứ này xung đột, chọn reproducibility.

---

## 2. Kiến trúc tổng thể

```
┌─ Entrypoints ──────────────────────────────────────────────────┐
│  build_kb.py   infer.py   score.py   package.py   annotate.py   │
├─ Orchestration ────────────────────────────────────────────────┤
│  Pipeline — DAG cố định, mỗi stage là pure function             │
├─ Stages ───────────────────────────────────────────────────────┤
│  Extract → Locate → TypeGate → Assert → Link → Filter → Emit    │
├─ Providers — interface + nhiều implementation ─────────────────┤
│  Extractor · Retriever · Reranker · Resolver                    │
├─ Knowledge Base — artifact build-time, bất biến lúc chạy ──────┤
│  icd10_concepts · icd10_aliases · rxnorm_concepts ·             │
│  rxnorm_aliases · rxnorm_remap                                  │
├─ Foundation ───────────────────────────────────────────────────┤
│  textref (NFC + offset map) · schema · sectionmap · provenance  │
└────────────────────────────────────────────────────────────────┘
```

**Quyết định kiến trúc #1: `textref` là tầng nền, không phải utility.** Toàn bộ hệ thống phụ thuộc vào nó. Lỗi offset là lỗi *im lặng* — không throw exception, chỉ âm thầm mất điểm, và 20/100 file có mìn NFD sẵn. Đặt nó ở tầng nền với test riêng là quyết định có chủ đích.

**Quyết định kiến trúc #2: Provider pattern cho mọi thứ có thể thay.** `Extractor` có 3 implementation qua các vòng (gazetteer → LLM → encoder offline). Nếu lời gọi LLM nằm rải trong pipeline thì v3 phải viết lại pipeline. Nằm sau interface thì v3 chỉ đổi một dòng config.

---

## 3. Data contract

### 3.1 Kiểu cốt lõi

```python
@dataclass(frozen=True)
class TextRef:
    raw:  str          # nguyên bản — MỌI position tính trên đây
    norm: str          # NFC + casefold — MỌI so khớp làm trên đây
    n2r:  list[int]    # offset norm → offset raw (bắt đầu)
    n2r_end: list[int] # offset norm → offset raw (kết thúc)

@dataclass(frozen=True)
class Span:
    start: int
    end:   int
    text:  str         # BẤT BIẾN: text == textref.raw[start:end]

@dataclass
class Mention:
    span:        Span
    type:        ConceptType
    assertions:  frozenset[Assertion]   # mặc định: frozenset()
    candidates:  tuple[str, ...]        # mặc định: ()
    provenance:  Provenance             # KHÔNG xuất ra JSON
```

### 3.2 Bất biến trung tâm

```
raw[span.start : span.end] == span.text
```

Kiểm ở **ranh giới mỗi stage**, không chỉ ở cuối pipeline. Lý do: bug offset không ném exception, nó chỉ làm điểm thấp. Nếu chỉ kiểm ở cuối thì biết là sai nhưng không biết stage nào làm sai.

### 3.3 Contract từng stage

| Stage | Vào | Ra | Khi lỗi |
|---|---|---|---|
| `Extract` | `TextRef` | `list[RawSpan]` (text + type gợi ý) | retry → fallback gazetteer |
| `Locate` | `TextRef`, `RawSpan` | `Span \| None` | `None` → **loại mention** |
| `TypeGate` | `Span`, ngữ cảnh | `ConceptType` | không lỗi được |
| `Assert` | `TextRef`, `Span`, `SectionMap` | `frozenset[Assertion]` | trả `frozenset()` |
| `Link` | `DiagnosisMention \| DrugMention` | `list[Candidate]` | trả `[]` |
| `Filter` | `list[Candidate]` | `tuple[str, ...]` | trả `()` |
| `Emit` | `list[Mention]` | JSON | không được lỗi |

**Chính sách lỗi: suy giảm, không sập.** Mỗi stage có giá trị mặc định an toàn.

> **Điểm may mắn cần khai thác:** metric quy ước `J = 1` khi cả gold và pred đều rỗng, và `candidates` rỗng an toàn hơn đoán bừa. Nghĩa là **"giá trị mặc định an toàn" trùng với "giá trị điểm cao"**. Thiết kế phòng thủ và tối ưu điểm số đồng thuận — hiếm khi được như vậy, nên tận dụng triệt để.

---

## 4. Thiết kế chi tiết từng module

### 4.1 `textref` — tầng nền

Vấn đề: 20/100 file lưu ở NFD (dấu thanh là ký tự tổ hợp riêng). LLM trả về NFC. `str.find()` thất bại dù mắt thường thấy chuỗi có trong văn bản. File 14: raw 2.672 ký tự vs NFC 2.538 — lệch 134.

**Thuật toán xây offset map** (gom ký tự cơ sở với các dấu tổ hợp theo sau):

```python
def build(raw: str) -> TextRef:
    groups, i = [], 0
    while i < len(raw):
        j = i + 1
        while j < len(raw) and unicodedata.combining(raw[j]):
            j += 1
        groups.append((i, j)); i = j

    parts, n2r, n2r_end = [], [], []
    for a, b in groups:
        piece = unicodedata.normalize('NFC', raw[a:b]).casefold()
        parts.append(piece)
        for _ in piece:              # 1 group -> ≥1 ký tự norm
            n2r.append(a); n2r_end.append(b)
    return TextRef(raw, ''.join(parts), n2r, n2r_end)
```

Tra ngược: `start_raw = n2r[start_norm]`, `end_raw = n2r_end[end_norm - 1]`.

Đây là mẩu code quan trọng nhất của v0. Nó phải có test suite riêng, chạy trên đủ cả 20 file NFD.

### 4.2 `Extract` — provider

```python
class Extractor(Protocol):
    def extract(self, t: TextRef) -> list[RawSpan]: ...
```

| Implementation | Vòng | Offline | Ghi chú |
|---|---|---|---|
| `GazetteerExtractor` | v0 | ✅ | Quét tên ICD nguyên văn. Baseline hồi quy vĩnh viễn |
| `LLMExtractor` | v1 | ❌ | Prompt few-shot phủ đủ 4 thể loại |
| `EncoderExtractor` | v3 | ✅ | XLM-R token-classification, distill từ nhãn bạc |
| `EnsembleExtractor` | v2+ | tùy | Hợp span từ nhiều nguồn, khử trùng lặp |

**Ba luật cứng cho `LLMExtractor`:**

1. **LLM không được trả `position`.** LLM trả chuỗi span; `Locate` tự định vị. Span không định vị được thì **loại bỏ** (đã đo: 1/472 do LLM diễn giải thay vì trích).
2. **Budget ≥ 32k token** + hàm sửa JSON cắt tới object hoàn chỉnh cuối. Có tiền lệ 2/10 file hỏng vì `stop_reason=max_tokens`. Model reasoning tiêu token cho suy luận nội bộ — phải để dư.
3. **Cache theo khóa `(sha256(raw), prompt_version, model_id, params)`.** Đây là hạ tầng đa dụng nhất trong hệ: nó cho **determinism** (NFR3), cho **resume** khi chạy dở, cho **chi phí** (không gọi lại), và cho **audit** (biết chính xác model trả cái gì).

**Chunking:** file dài nhất 4.481 ký tự — vừa một lời gọi, v0–v2 không cần chunk. Nhưng private test có thể khác → thiết kế sẵn chunk-có-chồng-lấn + khử trùng lặp span ở biên, để tắt mặc định.

### 4.3 `Locate`

- Longest-match, không chồng lấn, có kiểm tra ranh giới ký tự alphanumeric hai đầu.
- **Con trỏ đẩy qua hết độ dài match**, không phải `+1` — nếu không, nhiều token `*****` giống nhau sẽ sinh span chồng lấn (lỗi đã gặp).
- Span lặp lại: mention thứ *n* khớp lần xuất hiện thứ *n*.
- So khớp trên `norm`, trả offset trên `raw`.

### 4.4 `TypeGate` — nơi giải quyết vấn đề chương R

Đây là điều chỉnh kiến trúc quan trọng nhất so với hướng tiếp cận ban đầu.

```
        ┌──────────────┐
Span ──▶│  TypeGate    │
        └──────┬───────┘
               │
    ┌──────────┼──────────┬──────────────┐
    ▼          ▼          ▼              ▼
CHẨN_ĐOÁN   THUỐC   TRIỆU_CHỨNG   TÊN_XN · KẾT_QUẢ_XN
    │          │          │              │
    ▼          ▼          └──────┬───────┘
  ICD-10   RxNorm                ▼
                          candidates = ()  ← cưỡng chế bằng kiểu
```

**Cưỡng chế bằng hệ thống kiểu, không bằng quy ước.** Hàm `link()` chỉ nhận `DiagnosisMention` hoặc `DrugMention`. Ba type còn lại không có đường nào chạm tới KB — không phải vì lập trình viên nhớ, mà vì kiểu không cho.

Lý do: 27% mention khớp gazetteer nguyên văn rơi vào chương R (`khó thở`→R06.0, `đau đầu`→R51). Nếu gazetteer chạy trước typing, những mention này sẽ được gán mã — và schema bắt `candidates` của `TRIỆU_CHỨNG` phải rỗng.

### 4.5 `Assert`

**`SectionMap` dựng trước.** Parse tiêu đề mục → cây khoảng. Đo được: 58 file có mục "tiền sử", 55 "tiền sử bệnh", 23 "bệnh sử", 22 "thuốc trước khi nhập viện".

| Assertion | Luật | Mặc định |
|---|---|---|
| `isHistorical` | Concept nằm trong phạm vi mục tiền sử → bật. Cue cục bộ chỉ là tín hiệu phụ | tắt |
| `isNegated` | Cue **có ranh giới từ** + không thuộc 8 cụm cố định (`không được`, `không đặc hiệu`, `không rõ`…) + phạm vi phủ định kết thúc ở dấu câu/liên từ (kiểu ConText) | tắt |
| `isFamily` | **Tắt mặc định ở v1**, sau feature flag | tắt |

**Vì sao `isFamily` tắt:** cue `"ông "` xuất hiện 644 lần nhưng 630 (98%) là mảnh của chữ `"kh-ông"`. Sau khi sửa ranh giới từ chỉ còn 80 cue/36 file, và soi tay thì phần lớn vẫn là bẫy (cơ chế di truyền, lời khuyên, `"bà ấy"` = chính bệnh nhân, người nhà là người quan sát). Bằng chứng cho thấy `isFamily` thật gần như bằng 0 — bật nó lên là rủi ro thuần túy.

### 4.6 `Link` — hai nhánh tách biệt

**Nhánh CHẨN_ĐOÁN → ICD-10 (Việt→Việt)**

```
mention
   │
   ├─▶ [1] Gazetteer exact (longest-match trên norm)
   │        └─ trúng → mã, confidence=1.0, BỎ QUA ngưỡng     ← 94/100 file
   │
   └─▶ [2] không trúng → BM25(vi) ─┐
                                   ├─▶ RRF ─▶ top-k ─▶ rerank ─▶ ngưỡng ─▶ 1–2 mã
           embedding đa ngữ ───────┘
```

Căn cứ định lượng: Recall@1 chỉ ~51% nhưng Recall@5 = 94,9% → **retrieval lo recall, rerank lo precision**. Đây là kiến trúc bắt buộc, không phải sở thích.

**Nhánh THUỐC → RxNorm (Anh→Anh)**

```
mention ─▶ parse (hoạt chất, hàm lượng, đơn vị, dạng bào chế, đường dùng)
              │
              ├─ token bị che ***** ─▶ Resolver co-reference toàn văn bản
              │                          ├─ có neo → tên thuốc
              │                          └─ không neo → candidates = ()   ← 13/30 file
              ▼
        ràng buộc TTY ∈ {SCD, SBD}
              │
              ├─▶ khớp chuẩn hóa (hoạt chất + hàm lượng) → SCD
              └─▶ không khớp → embedding tiếng Anh (SapBERT) → rerank → ngưỡng
                          │
                          ▼
                    tầng remap (§4.8)
```

Căn cứ `TTY=SCD`: 5/6 mã trong ví dụ của đề là SCD (`308135` = *amlodipine 10 MG Oral Tablet* …).

**Ràng buộc TTY làm luôn việc của bộ lọc chất phân tích XN.** SCD bắt buộc có hàm lượng + dạng bào chế, nên `glucose` trơ trọi trong bảng xét nghiệm không khớp được gì. Đây là lý do không cần dựa vào semantic type — đã thử, `glucose` và `prothrombin` mang nhãn *Pharmacologic Substance* y hệt `aspirin`, không tách được.

### 4.7 `Filter` — bộ lọc precision

Jaccard phạt **cả thừa lẫn thiếu**, nên đây là stage quyết định điểm `candidates` (0.4):

1. Mã từ gazetteer exact → giữ thẳng, không qua ngưỡng.
2. Mã từ retrieval → chỉ giữ khi điểm rerank vượt `THRESH`.
3. Gộp mention trùng (cùng chuỗi, cùng type) → một bộ mã.
4. Trần **2 mã**; trả 2 chỉ khi thực sự lưỡng lự (`K21.0`/`K21.9`).

Bằng chứng cần bộ lọc này: pipeline cũ gán mã cho 97,6% chẩn đoán trong khi Recall@1 chỉ ~51% → khoảng một nửa số mã đang sai.

### 4.8 Tầng remap — thiết kế cho điều chưa biết

Rủi ro: `360047` trong ví dụ của đề đã hết hiệu lực 07/2019 → `2178097`. Cả `RXNORM.csv` lẫn `RXNCONSO.RRF` trong repo đều **không có** `360047`. Không nguồn nào tái tạo được đáp án mẫu.

```yaml
rxnorm_output_mode: current   # current | legacy | both
```

| Mode | Trả về | Dùng khi |
|---|---|---|
| `current` | mã của bản trong repo | BTC xác nhận dùng bản mới |
| `legacy` | tra ngược `RXNCUI.RRF`, trả mã cũ | BTC xác nhận dùng bản cũ |
| `both` | cả hai | BTC không trả lời, và công thức metric cho thấy trả 2 mã có lợi |

**Đây là config, không phải code.** Vì câu trả lời nằm ở BTC chứ không ở ta. Thiết kế cho phép đảo chiều trong một dòng YAML, không phải build lại index.

---

## 5. Data model — Knowledge Base

KB là **artifact build-time, bất biến lúc chạy**. Sinh bởi `build_kb.py`, không sửa trong pipeline.

```
data/kb/
├── icd10_concepts.parquet
│     code · canonical_name · chapter · is_symptom_chapter · valid · has_dagger · source_row
├── icd10_aliases.parquet
│     alias_norm · alias_nodiac · code · alias_type · risk_short · n_tokens
├── rxnorm_concepts.parquet
│     rxcui · tty · str · is_current
├── rxnorm_aliases.parquet
│     alias_norm · rxcui · tty · weight · ingredient · strength · unit · dose_form
├── rxnorm_remap.parquet
│     old_rxcui · new_rxcui · retired_release
└── MANIFEST.json
      nguồn · sha256 · số dòng · version · thời điểm build · git sha
```

### 5.1 Làm sạch lúc build

| Nguồn | Phép xử lý |
|---|---|
| `ICD10.csv` | `skiprows=4`, `utf-8-sig` · lọc `Hiệu lực=Có` (bỏ 955) · xử lý 2.120 mã hậu tố `*`/`†` · bỏ dòng rác (`test`→`D15.098`) · cờ `risk_short` cho 42 tên ≤6 ký tự · cờ `is_symptom_chapter` cho chương R · sinh alias bằng cách cắt đuôi `", không đặc hiệu"` / `", khác"` |
| `RXNCONSO.RRF` | `SAB=RXNORM` + `SUPPRESS=N` → 202.495 dòng · ưu tiên `SCD`/`SBD` · gom `SY`/`TMSY`/`PSN` về cùng RXCUI làm alias · `IN`/`PIN`/`BN` chỉ dùng làm neo co-reference |
| `RXNCUI.RRF` | 30.269 dòng → bảng remap: 22.330 mã đã đổi, 7.939 mã xóa hẳn |

### 5.2 Luật normalize — điểm dễ hỏng nhất

> **Hàm normalize phải là một mẩu code duy nhất, dùng chung lúc build KB và lúc query.** Tách đôi là sinh skew: alias trong index chuẩn hóa kiểu A, mention lúc chạy chuẩn hóa kiểu B, không bao giờ khớp và **rất khó phát hiện** vì không có exception nào được ném.

Cưỡng chế bằng thiết kế: `build_kb.py` import đúng hàm mà pipeline dùng, và `MANIFEST.json` ghi `normalizer_version`. Pipeline từ chối chạy nếu `normalizer_version` của KB khác của code.

Nhưng **hai nhánh cần hai implementation** (cùng interface):

| | ICD (Việt) | RxNorm (Anh) |
|---|---|---|
| Bước | NFC → casefold → gộp `–`/`-` → co khoảng trắng | casefold → chuẩn đơn vị (`MG`↔`mg`, `MG/ML`) → chuẩn dạng bào chế (`tab`→`tablet`) → tách hoạt chất/hàm lượng |
| Trường phụ | `alias_nodiac` (bỏ dấu) cho fuzzy fallback | `ingredient` + `strength` tách riêng để khớp bộ phận |

---

## 6. Chế độ hỏng & cách xử lý

| Hỏng gì | Phát hiện bằng | Xử lý | Kết quả xấu nhất |
|---|---|---|---|
| LLM cắt cụt JSON | `stop_reason` + parse fail | sửa JSON → retry budget cao hơn → fallback gazetteer cho file đó | file vẫn có output |
| LLM diễn giải thay vì trích | `Locate` trả `None` | loại mention, ghi log | mất 1 mention |
| LLM bịa mã | Provenance rỗng | **chặn cứng**: mã không truy được về dòng KB thì bị loại | không bao giờ xuất mã bịa |
| Offset lệch NFC | assert bất biến ở ranh giới stage | loại mention + báo lỗi | phát hiện được, không âm thầm |
| KB thiếu / sai version | check `MANIFEST.json` lúc khởi động | **fail loud ngay lúc start**, không phải lúc chạy | dừng sớm, rõ nguyên nhân |
| Mất mạng | timeout | chuyển `GazetteerExtractor` | vẫn ra `output.zip` hợp lệ |
| Lỗi decode | `utf-8` strict | fail loud | không đoán encoding |

**Luật bất di bất dịch: không bao giờ xuất file không hợp lệ.** Trường hợp xấu nhất cho một file là `[]` — vẫn đúng schema, vẫn nộp được.

---

## 7. Hiệu năng & mở rộng

**Đây không phải bài toán scale** — 100 file × ~2k ký tự. Nhưng ba thứ đáng thiết kế trước:

| Khía cạnh | Quyết định | Lý do |
|---|---|---|
| Wall-clock | Lời gọi LLM chiếm ~toàn bộ. Chạy song song có giới hạn (bounded concurrency ~5) + cache | Cache làm lần chạy thứ hai gần như tức thì |
| Vector index | **numpy brute-force, không FAISS** | ICD 13.189 mã · RxNorm SCD 17.552 — quá nhỏ để cần FAISS. **Bớt một dependency quan trọng hơn vài ms** (NFR1). Chỉ thêm FAISS khi đo được là chậm thật |
| Resume | Ghi output từng file + cache theo hash | Chạy dở giữa chừng thì chạy tiếp, không làm lại |

**Nếu private test lớn hơn nhiều:** batch LLM API, ghi output theo luồng, và lúc đó mới cần queue. Thiết kế hiện tại tuyến tính theo số file nên mở rộng được mà không đổi kiến trúc.

---

## 8. Observability

Không có nhãn vàng → **provenance là công cụ debug chính**.

Mỗi `Mention` mang theo:

```python
@dataclass
class Provenance:
    extractor:    str          # "llm:claude@v3" | "gazetteer"
    locate_method: str         # "exact" | "nfc" | "nth_occurrence"
    link_path:    str          # "gazetteer_exact" | "bm25+emb→rerank"
    kb_rows:      list[str]    # id dòng KB đã dùng
    scores:       dict[str, float]
    assertion_evidence: dict[str, str]   # cue nào, ở vị trí nào
```

`infer.py --explain` đổ provenance ra file cạnh output.

**Run manifest** ghi cạnh `output.zip` — đây *chính là* artifact reproducibility:

```json
{
  "git_sha": "…", "kb_manifest_sha": "…", "normalizer_version": 3,
  "extractor": "llm:…", "prompt_version": 7, "seed": 42,
  "rxnorm_output_mode": "current", "thresholds": {"THRESH": 0.5, "alpha": 0.7},
  "timestamp": "…", "n_files": 100, "n_mentions": 2771
}
```

---

## 9. Phân tích trade-off

| # | Quyết định | Phương án khác | Vì sao chọn | Đánh đổi |
|---|---|---|---|---|
| 1 | LLM cho extraction ở v1 | Rule/gazetteer thuần | Recall cao hơn hẳn ở văn bản dân dã, đa thể loại | Hại NFR1 → bù bằng interface + cache + fallback offline + lộ trình distill v3 |
| 2 | numpy brute-force | FAISS | Bớt dependency > vài ms ở quy mô 13k–18k vector | Sẽ phải đổi nếu KB lớn gấp 50 lần |
| 3 | ~~Parquet~~ → **CSV.gz** cho KB | Parquet | **Sửa lúc triển khai:** parquet cần `pyarrow`. NFR1 nói bớt dependency thắng, và KB nén lại chỉ 3,6 MB nên tốc độ không thành vấn đề. CSV.gz dùng `csv`+`gzip` của thư viện chuẩn | Load chậm hơn parquet ~2× ở quy mô này — không đáng kể |
| 4 | Package phân tầng | Một script | Sẽ lặp qua 4 vòng; script đơn sẽ mục ở v2 | Chi phí khởi tạo cao hơn ở v0 |
| 5 | Cache theo hash | Không cache | Cho determinism + resume + chi phí + audit, một mũi tên 4 đích | Phải quản lý invalidation qua `prompt_version` |
| 6 | Remap là **config** | Chọn cứng một chiều | Câu trả lời nằm ở BTC, không ở ta | Thêm một nhánh code phải test |
| 7 | `isFamily` tắt mặc định | Bật với luật cue | Bằng chứng đo được: gần như bằng 0 trong corpus, cue nhiễu 98% | Mất điểm nếu private test khác hẳn — chấp nhận, vì Jaccard phạt over-predict |
| 8 | KB build bằng script + commit artifact | Chỉ commit script | BTC phải chạy được ngay, không phụ thuộc tải dữ liệu | Repo nặng hơn |
| 9 | Cưỡng chế type-gate bằng hệ thống kiểu | Kiểm tra runtime | Lỗi này im lặng và tốn 0.4 trọng số | Code dài dòng hơn |

---

## 10. Sẽ xem lại khi nào

| Điều kiện | Phải xem lại |
|---|---|
| Private test lớn hơn 10× | Batch API, ghi luồng, queue. Kiến trúc tuyến tính hiện tại vẫn đúng nhưng orchestration phải đổi |
| BTC chốt công thức `candidates_score` | `Filter` và số mã trả về — hiện đang thiết kế thủ, có thể tối ưu sát hơn |
| BTC trả lời về bản RxNorm | Chốt `rxnorm_output_mode`, gỡ bớt nhánh |
| Xuất hiện nhãn vàng | Chuyển từ zero-shot sang supervised; dev set 20 file thành train set; toàn bộ `Extractor` đổi implementation |
| Thêm loại concept | `ConceptType` thành registry thay vì enum cứng; `TypeGate` thành bảng luật |
| Cần thêm bộ chuẩn (SNOMED, LOINC) | Lúc đó mới cần trục trung gian kiểu UMLS CUI. **Hiện tại không cần** — chẩn đoán và thuốc không bao giờ gặp nhau |
