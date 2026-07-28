# bench — hạ tầng đo lường

Không phụ thuộc gì ngoài thư viện chuẩn Python 3.10+. Chạy từ gốc repo.

```bash
python3 -m bench selftest
```

## Vì sao có gói này bên cạnh `smart_medic.score`

`score.py` trả về **một con số** để so hai lần nộp. Gói này trả lời câu hỏi
khác — *điểm đang mất ở đâu, và chênh lệch có thật không* — nên nó thêm bốn
thứ mà một script chấm điểm không có:

| | `smart_medic.score` | `bench` |
|---|---|---|
| điểm cuối | ✅ | ✅ |
| khoảng tin cậy / p-value | ❌ | ✅ bootstrap + hoán vị theo cặp |
| ghép tối ưu (Hungarian) | ❌ | ✅ để tách nhiễu do cách ghép |
| oracle ablation | ❌ | ✅ trần điểm từng module |
| ngưỡng tối ưu theo metric | ❌ | ✅ suy ra bằng giải tích |

## Lệnh

```bash
python3 -m bench selftest                                  # kiểm chứng chính benchmark
python3 -m bench score    --pred data/runs/v3 --pred data/runs/v4
python3 -m bench compare  --pred data/runs/v4 --pred data/runs/v3
python3 -m bench diagnose --pred data/runs/v4
python3 -m bench policy
python3 -m bench simulate
python3 -m bench corpus                                    # thẩm định tập nhãn sinh
python3 -m bench robust  --pred data/runs/v4               # chẩn đoán có bền qua các gold?
```

Gold mặc định `data/dev_gold_consensus` (20 file, 689 mention). Đổi bằng
`--gold DIR`. Mọi lệnh nhận `--json OUT` để ghi kết quả máy đọc được.

## Ba kết quả đã đo được nhờ gói này

**1. Chẩn đoán "nút thắt" KHÔNG bền qua cách dựng gold.** `bench robust` chạy
oracle ablation trên cả bốn biến thể gold của nhánh v4.1:

| gold | n | v4 | v4 prec | `+precision` | `+recall` | nút thắt |
|---|---:|---:|---:|---:|---:|---|
| consensus (giao 2 model) | 689 | 0,4192 | 64,5% | **+0,208** | +0,153 | PRECISION (1,4×) |
| sonnet5 | 932 | 0,5084 | 85,0% | +0,071 | **+0,211** | recall (3,0×) |
| opus5 | 978 | 0,5270 | 86,2% | +0,064 | **+0,230** | recall (3,6×) |
| prefill | 1003 | 0,5237 | 87,3% | +0,058 | **+0,242** | recall (4,2×) |

`consensus` là **phần giao** của hai model nên bỏ ~30% mention; những mention nó
bỏ chính là dự đoán **đúng** của v4, bị đếm thành "thừa" ⇒ precision tụt giả tạo
từ ~86% xuống 64,5% ⇒ oracle `+precision` phồng gấp ba. **Một bản trước của tài
liệu này đã kết luận sai "nút thắt đã đổi sang precision" vì chỉ chấm trên gold
đó.** Bài học: không kết luận nút thắt từ một gold LLM duy nhất — dùng
`bench robust`.

Điểm giao nằm giữa G=689 và G=857 (gold bầu ≥3/3 ghép theo IoU); chặn trên suy
từ leaderboard cho `G_dev ≲ 800`. Nghĩa là **bằng chứng hiện có không đủ để
chốt**, và cách gỡ là gán tay ~10 file chứ không phải chọn gold nào hợp ý.

**1b. Không có rò rỉ đo được** dù v4 train trên nhãn bạc của 94/100 file test.
Lợi thế v4 so với v3: +0,0999 trên holdout vs +0,0968 trên nhóm đã train
(chênh −0,003, dưới MDE). v3 — hệ chưa train gì — cũng tụt trên holdout, nên 6
file đó chỉ là khó hơn. Rủi ro thật của việc đó nằm ở **private test**, không ở
đo lường.

**2. Trả 2 mã candidates là nước đi bị chi phối.** Kết luận này **bền qua cả
bốn gold**: consensus có `|candidates| ∈ {0, 1}`; ba gold còn lại mỗi cái đúng
**1 mention trên ~1.000** có 2 mã. Tỉ lệ gold rỗng theo type cũng ổn định —
THUỐC 69–76%, CHẨN_ĐOÁN 8–15%. Khi `|G| ≤ 1`:
`E[J](k=2) ≤ (p₁+p₂)/2 < p₁ = E[J](k=1)`. Bảng `simulate` xác nhận: hồ sơ
"luôn trả 2 mã" mất **−0,012** so với chính nó khi chỉ trả 1 mã, dù độ phủ
giống hệt.

**3. Ngưỡng phát mention tối ưu không phải 0,5.** Suy từ `S = N/(G+P−M)`:

```
phát mention khi  p > S / (q̄ + S)
```

Tăng theo điểm hiện tại: S = 0,32 → ngưỡng 0,27; S = 0,42 → 0,34; S = 0,85 →
0,50. Ngưỡng tối ưu F1 luôn là 0,5 — dùng nó ở giai đoạn đầu là tự bỏ toàn bộ
mention có độ tin 27–50%.

## Thẩm định dữ liệu sinh (`bench corpus`)

`data/generated_medical_records/` có 314 tài liệu gán nhãn từ
`scripts/gen_sample_data.py`. Lệnh `corpus` trả lời câu hỏi *tập này dùng được
vào việc gì*, và câu trả lời khác nhau theo từng tập con:

| tập | file | span | Δ độ dài span | nhãn thiếu | THUỐC rỗng |
|---|---:|---:|---:|---:|---:|
| `dev_gold` (tham chiếu) | 20 | 689 | — | 15,2% (nền) | 76% |
| `gen/synthetic` | 194 | 5.353 | **−0,12** ✅ | 30,5% (+15,2) ❌ | 10% ❌ |
| `gen/translated` | 95 | 3.368 | **−1,11** ❌ | 9,0% ✅ | 9% ❌ |
| `gen/restyled` | 25 | 934 | **−1,20** ❌ | 6,1% ✅ | 9% ❌ |

**0 lỗi offset trên cả 9.655 span** — kiến trúc "code chọn thực thể trước, LLM
viết văn quanh chúng, offset tính lúc bóc dấu 〔 〕" làm đúng thứ khó nhất.

Ba kết luận vận hành:

1. **`synthetic` dùng làm tập chấm chính.** MDE giảm từ **±0,030** (20 file dev)
   xuống **±0,011** (194 file) — độ phân giải thống kê gấp gần 3 lần, và bảng
   `simulate` xếp hạng y hệt dev gold. Đây là thứ đắt nhất mà dự án đang thiếu.
2. **`translated`/`restyled` KHÔNG dùng để train biên span.** Chúng lệch −1,11 và
   −1,20 từ, gần như trùng khít với lỗi đang mất điểm của v4 (**−1,09 từ**).
   Train trên chúng là dạy lại chính lỗi cần sửa. Vẫn dùng được cho *phát hiện*
   (độ phủ nhãn tốt hơn cả gold) — tức là hai đầu loss khác nhau.
3. **Không tập nào dùng để hiệu chuẩn ngưỡng phát mã.** Bộ sinh gán mã cho gần
   như mọi thực thể nó trồng xuống (THUỐC rỗng 9–10%), trong khi gold thật để
   trống **76%**. Ngưỡng suy từ đây sẽ sai một bậc độ lớn.

## Cảnh báo về gold

`data/dev_gold_consensus` do LLM sinh rồi lấy đồng thuận, **không phải gold
BTC**. Ba khuyết tật, xếp theo mức nghiêm trọng:

1. **Cách hợp nhất làm đảo chiều chẩn đoán** (mục 1 ở trên). Nghiêm trọng nhất
   vì nó không lộ ra dưới dạng "số hơi lệch" mà dưới dạng **kết luận ngược**.
   Luôn chạy `bench robust` trước khi tin bất kỳ chẩn đoán nào.
2. **Nới tay ~8 điểm** so với leaderboard (v4.1 đo: cùng artifact cho 31,69 trên
   dev vs 23,53 thật). Đừng đọc mức tuyệt đối.
3. **Vòng lặp thiên kiến**: gold do LLM sinh, còn tầng neural của v4 được distill
   từ nhãn bạc LLM trên cùng các file — nên hai bên chia sẻ thiên kiến ở đúng chỗ
   ta đang đo (biên span, thế nào là một khái niệm). Bằng chứng: gold 3,45 từ/span,
   nhãn bạc 3,09, pred v4 2,36 — một dãy giảm đều, và gold thật của BTC có thể còn
   dài hơn 3,45.

Điều **không** phải khuyết tật: việc gold nằm trên `data/test`. Kiểm rò rỉ
(mục 1b) không thấy dấu hiệu ghi nhớ, và không có nguồn nhãn nào khác ở đúng
phân phối dữ liệu thật.

`data/gold_variants/` chứa cả bốn biến thể để chạy `bench robust`.

`--unmatched zero` là mặc định vì nhánh v4.1 đã quét 12 cách hiểu công thức và
chỉ cách này khớp leaderboard (lệch 8,2 so với 62,8 của `skip`). Vẫn nên đối
chiếu công bố chính thức của BTC.

## Kiến trúc

```
bench/
├── metric.py     công thức + phân rã  final ≈ q_pair × phủ
├── matching.py   ghép greedy (như BTC) và Hungarian (biên trên)
├── stats.py      bootstrap CI, kiểm định hoán vị theo cặp, MDE
├── decision.py   ngưỡng phát mention, E[Jaccard], chính sách theo type
├── diagnose.py   phân loại lỗi, oracle ablation, quét recall
├── degrade.py    hệ giả lập (common random numbers)
├── corpus.py     thẩm định một tập nhãn so với tham chiếu
└── cli.py        8 lệnh
```
