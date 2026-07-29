# ADR 0003 — Dùng LLM API closed-source cho khâu sinh dữ liệu

- **Trạng thái:** ĐÃ QUYẾT
- **Ngày:** 2026-07-29
- **Ảnh hưởng:** Phase 1 (dữ liệu), và ranh giới build-time/runtime của cả pipeline

## Bối cảnh

Quy chế Vòng 1 nêu: khi dùng LLM/agent, thí sinh **chỉ được self-host model** và **không được
dùng API model closed-source**; model self-host **tối đa 9B tham số**. Đồng thời BTC yêu cầu
nộp *"data nhóm sử dụng"*.

Kho nhãn bạc hiện có (543 file, `data/generated_medical_records/`) được sinh bằng **GPT-4o**.
Câu hỏi: điều khoản trên áp cho *lời giải* hay cho *toàn bộ pipeline kể cả khâu sinh dữ liệu*?

## Quyết định

**Hợp lệ.** Ranh giới là **build-time vs runtime**:

- ✅ **Được phép:** dùng LLM API closed-source để *sinh dữ liệu huấn luyện*, gán nhãn bạc,
  sinh từ đồng nghĩa, chưng cất tri thức sang model nhỏ. Đây là khâu build-time, kết quả là
  *dữ liệu tĩnh* được đóng gói nộp.
- ❌ **Không được phép:** bất kỳ lời gọi API nào trong **pipeline suy luận**. Toàn bộ model
  chạy lúc inference phải self-host và **tổng dưới 9B tham số**.

## Hệ quả

1. **Kho 543 file bạc giữ nguyên**, không phải làm lại.
2. **Distillation teacher mạnh → student nhỏ mở lại hoàn toàn.** Đây là hướng có nhiều bằng
   chứng nhất trong văn liệu cho chế độ không có nhãn, và trước đó phải đánh dấu rủi ro.
3. Prompt-LF ở P1.2 dùng được model mạnh thay vì bị giới hạn ≤9B.
4. **P1.3 (chiếu NER tiếng Anh qua marker `〔 〕`) vẫn nên làm** — nhưng lý do đổi. Giá trị
   của nó là **sai số không tương quan** với gazetteer và với LLM, chứ không phải vì nó
   tránh được LLM. Trong một label model, nguồn có sai số độc lập là tài nguyên khan hiếm nhất.
5. **Vẫn phải nộp dữ liệu đã sinh.** Nộp *data*, không phải khả năng sinh lại data. Đóng gói
   kèm **prompt và config** để BTC audit được nguồn gốc.

## Rủi ro cần canh

**Rò rỉ API vào runtime.** Đây là chế độ hỏng thực tế nhất: một agent thêm lời gọi API vào
`pipeline.py` vì "nó cho kết quả tốt hơn", và không ai phát hiện cho tới vòng chấm source code.

Phòng thủ:
- `src/smart_medic/pipeline.py` và mọi thứ nó import **không được** phụ thuộc thư viện HTTP
  client của nhà cung cấp LLM. Thêm test khẳng định điều này.
- Mọi lời gọi API sống trong `scripts/` (build-time), không bao giờ trong `src/smart_medic/`
  đường suy luận.
- `configs/models.yaml` liệt kê *mọi* model runtime kèm số tham số, và assert tổng &lt; 9B lúc
  khởi động.
