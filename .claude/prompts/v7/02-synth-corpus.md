# Phase 2 — bộ sinh corpus

> **Nguồn chuẩn:** [`docs/synth-corpus-plan-v2.md`](../../../docs/synth-corpus-plan-v2.md) §8.
> Sửa ở tài liệu trước, rồi đồng bộ sang đây — đừng sửa một phía.
>
> Thời lượng: **3 ngày** · Tiền đề: **Phase 1 (cần lab_panels.v1.yaml)**

---

Bối cảnh: đọc docs/synth-corpus-plan-v2.md §2.2–§2.5, §3, §4 Phase 2, §5.
Đọc thêm: docs/synth-corpus-plan.md §2 (vì sao annotation-first) và §3.2
(phân bố văn bản thật) — hai mục đó của v1 vẫn đúng nguyên.

Nguyên tắc bất di bất dịch: GHI OFFSET LÚC CHÈN CHUỖI vào khung, không bao giờ
dùng txt.index(). Đây là lý do tồn tại của cả hướng annotation-first.

2a. Khung + bất biến — VIẾT TEST TRƯỚC.
    src/smart_medic/synth/{schema,render,export}.py
    Bốn bất biến, kiểm trên 100% tài liệu:
      1) text[start:end] == span.text
      2) span không chồng lấn
      3) candidates rỗng với TRIỆU_CHỨNG / TÊN_XN / KẾT_QUẢ_XN
      4) corpus chấm được bằng stages.scoring mà không sửa gì
    Dùng lại stages.solve.check_invariants — nó đã cài sẵn 1–3.
    Xuất đúng định dạng gold_real: text/NNN.txt + annotations/NNN.json.

2b. Bề mặt TẤT ĐỊNH — không gọi LLM.
    synth/surface/lab.py   ← nguồn chính, đọc lab_panels.v1.yaml của Phase 1
    synth/surface/drug.py  ← phụ, chỉ 10% tài liệu. Ba lớp bề mặt:
        - tên ATC tiếng Việt (data/knowledge_base/atc/ddd.csv, lọc `+` `*` `(`)
        - token bị che *** (độ dài trung vị 12 — đã đo trên data/test)
        - biệt dược Việt KHÔNG có mã → candidates rỗng LÀ đáp án đúng
    Xuất kèm: data/curated/drug_surface_atc.v1.jsonl, dose_forms_vi.v1.txt (71),
    drug_groups_vi.v1.txt (29). Hai file sau KHÔNG nạp vào KB.

2c. Bề mặt LLM — CHỈ CHẨN_ĐOÁN và TRIỆU_CHỨNG.
    Gọi MỘT LẦN, đóng băng ra data/curated/surface_forms.v1.jsonl + .sha256,
    commit vào git. Prompt phải đòi đích danh: cách nói dân dã, viết tắt, sai
    chính tả, vùng miền; CẤM trả về tên chuẩn trong KB.
    Hình dạng mong muốn cho K29.7 (Viêm dạ dày, không xác định):
      viêm bao tử · đau bao tử · viêm dạ dày · đau dạ dày · viêm bao tử mạn
    Dùng model KHÁC HỌ với model dùng ở pipeline (sai số không tương quan).

    HAI PHÉP ĐO bắt buộc ghi lại — cả hai đều KHÔNG làm dừng phase:
      (i)  hợp lý y khoa: duyệt tay 100 cặp (cách nói → mã) ngẫu nhiên, >= 80.
           Dưới ngưỡng → siết prompt, sinh lại ĐÚNG MỘT LẦN, lấy kết quả tốt hơn
           trong hai lần rồi đi tiếp.
      (ii) độ mới: >= 40% cách nói KHÔNG khớp term nào trong gazetteer KB.
           Đây là phép đo chống vòng lặp tự khen (v1 §3.1). Dưới 40% VẪN ĐI TIẾP,
           nhưng ghi vào phase2-corpus-stats.json — nó dự báo Phase 3 ít tác dụng,
           và Phase 5 cần con số này để diễn giải kết quả.

2d. Span âm + khuôn thật.
    synth/distractor.py — 6 lớp ở §2.5, chèn KHÔNG kèm nhãn.
      ⚠️ Lấy LỚP của bẫy (kiến thức chung về thể loại), KHÔNG copy thực thể cụ
      thể từ gold_real/README.md — đó là file cổng.
    synth/frames.py — khai thác 91 file data/test (loại 9 file của gold_real)
    làm khuôn: giữ khung câu, thay cụm y khoa bằng span sinh ra.
      Ràng buộc PRD §5: giữ 20 file làm holdout khung; KHÔNG copy nguyên câu có
      chứa khái niệm y tế; ghi rõ cách làm vào README nộp BTC.
      Nếu đánh giá là rủi ro → dùng gold_batch1 làm nguồn khung thay thế.

2e. Nhiễu + thống kê. Khớp §3.2 của v1 (đã kiểm lại, chính xác):
    NFD 20/100 · mask *** 30/100 · gạch đầu dòng 90/100 · mẫu NHÃN: 97/100 ·
    giọng hỏi–đáp 49/100 · độ dài trung vị 1838 ký tự.

CỔNG CHẶN — vi phạm = corpus hỏng, huấn luyện trên nó là học cái sai:
- 4 bất biến pass 100% tài liệu

Lưu ý KHÔNG phải cổng mà là MỘT BƯỚC trong render.py: khái niệm nào linking.py
không tra ra mã thì LỌC TỰ ĐỘNG khỏi corpus (đừng dạy model gán mã pipeline
không thể trả về — tự dựng trần điểm cho chính mình).

CỔNG ĐỊNH TUYẾN — không đạt thì ghi số vào phase2-corpus-stats.json và ĐI TIẾP:
- phân bố nhiễu khớp trong ±10 điểm phần trăm
- >= 15% span là span âm
- hai phép đo của 2c

Corpus không đạt cổng định tuyến VẪN đem huấn luyện ở Phase 3 — chỉ là kỳ vọng
thấp hơn, và Phase 5 biết điều đó khi đọc file thống kê.

Cấm: gọi LLM ở bất kỳ đâu ngoài 2c; dùng gold_real làm nguồn; báo cáo bất kỳ số
đo nào trên chính corpus sinh ra.
