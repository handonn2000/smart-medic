# Phase 3 — tagger

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **2 ngày** · Tiền đề: **Phase 2**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.7 (hai dòng về offset), §4 Phase 3.

Việc: huấn luyện token classification BIO 5 nhãn trên corpus data/synth/v1.

- Base: xlm-roberta-base, GHIM REVISION cụ thể trong config (không dùng "main").
  Lý do chọn: ViMedNER cho thấy XLM-R nhìn chung vượt PhoBERT/ViHealthBERT trên
  NER y khoa tiếng Việt, và nó chạy syllable-level nên KHÔNG cần VnCoreNLP —
  bước mà làm sai là nguồn lỗi phổ biến.

- ƯU TIÊN SỐ MỘT LÀ OFFSET, không phải F1:
  * dùng offset_mapping của fast tokenizer để ánh xạ subword → ký tự;
  * giải mã BIO CÓ RÀNG BUỘC: cấm I-X sau O, cấm I-X sau B-Y (Y != X);
  * tests/unit/test_tagger_offsets.py phải có ca: đầu vào NFC, đầu vào NFD, và
    đầu vào TRỘN CẢ HAI trong cùng một cụm (đây là hiện tượng thật ở 100.txt:
    cùng chuỗi "tiền sản giật" chỗ dài 16 ký tự chỗ 13).

- Split: dev TỔNG HỢP từ data/synth/v1/splits.json cho early stopping.
  TUYỆT ĐỐI KHÔNG dùng gold_real để chọn epoch, ngưỡng, hay bất kỳ siêu tham số
  nào — nó là cổng (quy tắc 7).

- calibrate.py: chọn ngưỡng tin cậy trên dev tổng hợp, ghi ra file config.

- Tái lập: ghim seed; ghim revision base model; ghi sha256 của corpus vào
  metadata checkpoint; xuất ra data/artifacts/tagger/v1/.

- Phần cứng: M3 Pro / MPS, cỡ BERT-base ~187 mẫu/s → vài phút mỗi epoch.

- stages/tagger.py (inference): KHÔNG import torch ở top-level. Thiếu torch thì
  trả danh sách rỗng và pipeline chạy tiếp bằng proposer luật.

CỔNG CHẶN: 0 span lệch offset khi chạy trên toàn bộ 100 file data/test (gồm 20
file không NFC). Lệch offset là bug đi thẳng vào bài nộp — không thương lượng,
không nới.

CỔNG ĐỊNH TUYẾN: F1 span trên dev TỔNG HỢP >= 0.80 (đã nới từ 0.90) → tagger: true.
Dưới ngưỡng VẪN ĐI TIẾP Phase 4: arbiter sẽ tự cho model trọng số thấp, và
Phase 5 có thể đặt arbiter_model_weight: 0.0. Không dừng, không huấn luyện lại
quá 2 lần.

KHÔNG đo gold_real ở phase này. Không được nhìn vào nó.
