# L4b · `linking/` — mã chuẩn · 10,00 ĐIỂM (biên thực 1,0–3,0)

**Đọc trước khi làm bất cứ việc gì trong layer này.**

Trọng số danh nghĩa của `candidates` là 0,4 — **đó là cái bẫy lớn nhất của đề bài**.
Mẫu số official là `Σ_k (|gold(k)| + 1)`, cộng `+1` cho **mọi** entity đã ghép kể cả 3
loại không bao giờ có mã. Với 67% entity thuộc 3 loại đó, tỷ số trần bị ép xuống
**0,2501** ⇒ toàn nhánh chỉ đáng **10,00 điểm**.

Và cận trên của việc *cải thiện* nó còn hẹp hơn: đi từ 30% mã sai xuống 10% mã sai đáng
**2,00 điểm** (đo lại 30/07: sai 10% = −0,96 · 30% = −2,96).

⇒ **Đừng rút người từ `extract/` sang đây. Ngân sách layer này ≤ 1,5 ngày-người.**

## Hợp đồng

```python
linking.retrieve(spans, doc)  -> dict[Span, list[Cand]]
linking.verify_edges(cands)   -> dict[Cand, Verdict]   # vector 6 bit + hành động
# Verdict.action ∈ {keep, remap→X, lift→IN, drop, abstain}
```

## Bốn quyết định đã đo

1. **Chỉ mục ICD là ma trận dense PHẲNG vét cạn, 45 MB. ĐỪNG xây ANN.** 14.678 chuỗi ⇒
   một GEMM, < 1 ms, **recall 100%**, 0 siêu tham số. HNSW/DiskANN/ScaNN ở quy mô này chỉ
   thêm siêu tham số và mất recall.
2. **Thuốc: TF-IDF char-ngram thắng dense 1,4 điểm.** Tên thuốc là bài toán chuỗi, không
   phải bài toán ngữ nghĩa.
3. **Hợp nhất bảng xếp hạng bằng CombMNZ, KHÔNG dùng RRF.** RRF vứt bỏ độ lớn điểm.
4. **Loại theo `RXNSTY` T200, KHÔNG whitelist T109/T121.** Đo được: 220/220 RxCUI gold ở
   mức IN, 218/220 có T109|T121 — nhưng **hai ngoại lệ là thật**: 9863 sodium chloride
   (T197) và 11124 vancomycin (T116/T195). Whitelist loại oan chúng.

## Chi tiết RRF phải biết trước khi nạp

| Việc | Số | Ghi chú |
|---|---|---|
| Lọc bỏ `inactive_ingredient_of` **TRƯỚC** khi nạp `RXNREL` | 1.673.734 cạnh | nhiễu thuần |
| `tradename_of` | 118.543 | dùng được |
| `has_active_moiety` | 266.440 | dùng được |
| `has_active_ingredient` | 288.367 | dùng được |
| `consists_of` | 116.818 | **quyết định doublet thuốc phối hợp** |
| `isa` / `inverse_isa` | 292.028 | thang bậc |
| `RXNATOMARCHIVE.RRF` — `MERGED_TO_RXCUI` | 373.484 dòng khác rỗng | mã đã rút, vd 360047 → 2178097 |
| ICD tiếng Việt (`ICD10.csv`) | 13.189 mã · 36.689 tên | **được phép trả mã 3 ký tự** (I48.0 → I48) |
| ICD tiếng Anh (`icd10cm-codes-2027.txt`) | 74.879 mã · khớp 5.460 | **chỉ LÀM GIÀU theo mã** |

⚠ `ICD10.csv` (tiếng Việt) và `icd10cm-codes-2027.txt` (ICD-10-CM Mỹ) **không thay thế được
cho nhau**: chỉ **41,4%** mã của bảng tiếng Việt tồn tại trong bảng tiếng Anh (7.729 mã như
`A00`, `A01`, `A03` không có), và đầu vào của bài toán là **văn bản tiếng Việt**. Bảng tiếng
Anh là nguồn làm giàu nhãn, nối **theo mã**.

**Đường dẫn:** `data/knowledge_base/` là thư mục **phẳng**. Đọc qua
[`scripts/kb_sources.py`](../../../scripts/kb_sources.py) — nó là nơi duy nhất định nghĩa
đường dẫn và cách parse RRF. Bảng `RXNORM.csv` của ban tổ chức đã bị bỏ; `RXNCONSO.RRF` thay
nó (cùng 18 cột, cùng thứ tự — CSV đó chính là RXNCONSO đã chuyển định dạng).

## `target_tty` là THAM SỐ, không hard-code

[ADR 0001](../../../docs/decisions/0001-drug-tty.md) bản 3 **tạm chốt `IN`** cho gold
annotation (gold của đội 100% IN, 220/220 RxCUI ở mức IN). Lựa chọn khi *nộp* còn chờ
Probe B. Mức ảnh hưởng đo được chỉ **~1,1 điểm/100** (18,6% span thuốc có hàm lượng).

⇒ `configs/pipeline.yaml: linking.target_tty` chạy được cả `IN` lẫn `SCD` bằng một cờ.
**Đừng tinh chỉnh ngưỡng nhánh thuốc trước khi Probe B trả lời.**

## File

| File | Vai trò | Trạng thái | Phase |
|---|---|---|---|
| `icd.py` | dense phẳng 45 MB + gazetteer làm giàu (5.460 nhãn EN + 302 nhãn khối) | ⬜ | P5 |
| `rxnorm.py` | thang bậc RXNREL, `target_tty` tham số hoá | ⬜ | P5 |
| `edge_verify.py` | 6 luật → vector 6 bit vi phạm → hành động + abstain | ⬜ | P5 |
| `retrieve.py` · `rerank.py` | CombMNZ (LambdaMART chỉ nếu còn thời gian) | ⬜ | P5 |
| `redaction.py` | `*****` — **chỉ cắt danh sách ứng viên** | ⬜ | P5 |

`extract/aho.py` dùng lại chỉ mục gazetteer của layer này — build một lần, hai chỗ đọc.

## Cái bẫy của layer này

| Bẫy | Bằng chứng |
|---|---|
| Whitelist semantic type | loại oan 9863 NaCl (T197), 11124 vancomycin (T116/T195) ⇒ dùng T200 để **loại** |
| Tin `*****` để quyết định mã | 30/100 file test có `*****` (99 token); **dương tính giả đã xác định**: `1.txt` khớp "glucose", `18.txt` khớp "lipase" — không phải thuốc bị che ⇒ chỉ dùng để CẮT ứng viên |
| Bỏ trống khi không chắc | q₀ đo trên gold = 0,0521 (CĐ) · 0,0588 (thuốc). Bản cũ ước 0,209 từ silver — **sai 4×** ⇒ gần như không bao giờ bỏ trống |
| Thêm mã "cho chắc" | miễn phí dưới công thức `official` (0,00), nhưng mất 6,72 / 10,84 / 12,23 dưới `plain` với 1/4/9 mã rác ⇒ **giữ "đúng 1 mã hoặc 0"** tới khi Probe B trả lời |
| Lấp toàn bộ vùng trắng ICD | đã loại — không hoàn vốn |
| Xây thêm tầng biến đổi dữ liệu | co ngót đệ quy đã xảy ra: retention chuỗi bề mặt `translated → restyled` chỉ 63,5%; mã CĐ 158 → 136, RxCUI 288 → 223 |

## Nghiệm thu

- `candidates_score` ≥ 0,20 (rỗng hết = 0,0000; trần = 0,2501).
- `code_accuracy` từ `diagnostics()` ≥ 0,80 trên entity codeable có mã.
- **0** mã trong bài nộp không tồn tại trong KB đóng gói kèm.
- Tỷ lệ bỏ trống ≤ 0,06 (gold: 0,0547).
- CHẨN_ĐOÁN trả đúng 1 mã trong ≥ 94% trường hợp có mã.
- Tổng thời gian layer ≤ 1,5 ngày-người. Vượt là **sai ưu tiên**, không phải làm kỹ.
