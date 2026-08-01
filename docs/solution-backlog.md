# Backlog — pipeline giải bài

> Các hướng đã khảo sát nhưng **thuộc pipeline giải bài**, không thuộc KB pipeline.
> KB pipeline: xem [`kb-pipeline-plan.md`](kb-pipeline-plan.md).
>
> Mục đích của file này là **không đánh mất ý tưởng đã nghiên cứu** trong lúc tập trung xây KB. Mỗi mục ghi đủ bối cảnh để cầm lên làm mà không phải khảo sát lại.

---

## S1 — SNOMED làm máy sinh dữ liệu huấn luyện cho embedding

**Trạng thái:** đã khảo sát, chưa triển khai
**Điều kiện tiên quyết:** KB Phase 3 xong (cần ExtendedMap đã nạp)
**Tiềm năng:** cao — nhắm thẳng vào module chiếm 0.4 điểm

### Ý tưởng

PRD §6 đề xuất *"fine-tune embedding trên chính ICD10/RXNORM theo kiểu SapBERT (sinh cặp đồng nghĩa từ bảng mã) để may đo đúng kho của đề"*. Vấn đề của hướng đó: bảng mã ICD chỉ cho **một tên** mỗi mã, nên số cặp đồng nghĩa sinh được rất ít.

SNOMED giải quyết đúng chỗ thiếu đó. ExtendedMap cho **129.741 cặp `(concept SNOMED → mã ICD)`** dùng được, mỗi concept lại mang nhiều description. Gộp lại thành kho cặp đồng nghĩa cỡ lớn:

```
mọi synonym của các concept SNOMED cùng map về một mã ICD
        ⇒ đều là positive pair của nhau
        ⇒ dữ liệu contrastive learning kiểu SapBERT
```

### Vì sao đáng làm

Đây là công thức đã được kiểm chứng trên **đúng hình dạng bài toán này**: [ClinLinker](https://arxiv.org/html/2404.06367v1) làm entity linking tiếng Tây Ban Nha sang SNOMED bằng bi-encoder SapBERT truy hồi + cross-encoder re-rank, huấn luyện contrastive. Bài toán *tiếng Tây Ban Nha ↔ thuật ngữ tiếng Anh* đồng dạng với *tiếng Việt ↔ ICD* của ta.

Bằng chứng bổ trợ: embedding học từ đồ thị SNOMED cải thiện 5–6 lần ở tác vụ concept similarity so với embedding SOTA ([Snomed2Vec](https://arxiv.org/abs/1907.08650)); hướng dùng knowledge graph embedding cho post-coordination cũng đã được công bố ([JBI 2023](https://dl.acm.org/doi/10.1016/j.jbi.2023.104297)).

### Cạm bẫy phải tính trước

| Vấn đề | Xử lý |
|---|---|
| **Fan-in mã gom** — `T88.7` nhận 1.600 concept ⇒ 1.600 term thành "đồng nghĩa" của nhau, hoàn toàn sai | Dùng lại ngưỡng fan-in của KB §P3.2, ngưỡng chặt hơn (≤ 5) vì đây là dữ liệu huấn luyện |
| SNOMED chỉ có **tiếng Anh** | Cặp đồng nghĩa là Anh–Anh; vẫn phải bắc cầu Việt→Anh riêng |
| Reproducibility | Sinh dữ liệu một lần, đóng băng thành file có version; ghim seed + checkpoint |

### Việc cần làm khi cầm lên

1. Sinh cặp đồng nghĩa từ `closure` + `relations(maps_to)`, áp ngưỡng fan-in
2. Kiểm chất lượng bằng mắt trên ~100 cặp ngẫu nhiên trước khi huấn luyện
3. Fine-tune SapBERT bằng multi-similarity loss
4. Đo trên probe set (Phase 2.5) — so với SapBERT gốc chưa fine-tune

---

## S2 — Khớp thành phần bằng quan hệ định nghĩa SNOMED *(đã loại khỏi KB plan)*

**Trạng thái:** loại khỏi kế hoạch, giữ để tham khảo
**Lý do loại:** tốn công lớn, kết quả không chắc, bộ mã không được chấm trực tiếp

SNOMED có `finding site` (109.781 cạnh) và `associated morphology` (82.194 cạnh) cho phép phân rã khái niệm — "viêm phổi thuỳ" = viêm (morphology) + thuỳ phổi (site). Tiếng Việt y khoa ghép rất mạnh ("vàng da vàng mắt", "thiếu máu tan huyết") nên về lý thuyết rất hợp.

Rào cản: phải tự dựng bộ phân rã cụm từ tiếng Việt trước, và không có dữ liệu để kiểm chứng. Chỉ cầm lên nếu S1 đã xong và còn nhiều thời gian.

---

## S3 — Graph embedding trên đồ thị SNOMED *(đã loại khỏi KB plan)*

**Trạng thái:** loại khỏi kế hoạch, giữ để tham khảo

Có bằng chứng tốt (xem S1). Nhưng nó giải bài toán *"similarity giữa hai concept SNOMED"*, **không** giải bài toán *"mention tiếng Việt → concept"* — mà cái sau mới là chỗ ta đang tắc. Muốn dùng được thì vẫn phải bắc cầu Việt→SNOMED trước, tức là đã giải xong phần khó rồi.

Nếu quay lại, nên coi nó là **bước tinh chỉnh sau** khi S1 đã cho một retriever hoạt động được, không phải bước đầu.

---

## Ghi chú nguồn

Bài báo y sinh trích từ PubMed, DOI dẫn trong `kb-pipeline-plan.md` §P3.4–P3.5. Nguồn khác: [ClinLinker](https://arxiv.org/html/2404.06367v1) · [Snomed2Vec](https://arxiv.org/abs/1907.08650) · [KG embeddings cho post-coordination](https://dl.acm.org/doi/10.1016/j.jbi.2023.104297) · [Snowstorm](https://github.com/IHTSDO/snowstorm) · [SNOMED ECL v2.1](https://confluence.ihtsdotools.org/display/slpg/snomed+ct+expression+constraint+language)
