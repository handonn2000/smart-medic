"""Gắn mã chuẩn cho entity — nơi Track 0 của KB được đem ra dùng thật.

Đây là module ăn **0.4 điểm**, trọng số lớn nhất của đề. Nó mỏng có chủ đích:
toàn bộ phần khó đã nằm trong `kb.query` và đã được đo trên ba bộ gold.

    CHẨN_ĐOÁN → icd10     R@1 0,562 · R@20 1,000   (gold lâm sàng, 48 ca)
    THUỐC     → rxnorm    R@1 1,000                (gold lâm sàng, 66 ca)

★ HAI QUYẾT ĐỊNH THEO METRIC
─────────────────────────────
1. **`rerank=True` là bắt buộc.** Nó mặc định TẮT ở `search_lexical` để không
   đổi hành vi dưới chân code cũ. Quên bật là mất 45 điểm R@1 ở nhánh thuốc —
   đo được, không phải ước lượng.

2. **Trả ĐÚNG MỘT mã.** `candidates_score` dùng Jaccard nên mã thừa bị phạt
   ngang mã thiếu: đáp án `{K21.0}` mà đoán `{K21.0, K21.9}` chỉ được 0,5. Rải
   top-k là cách chắc chắn nhất để mất điểm.

   Đã cân nhắc *hedging* cha + con `.9` cho lớp ca lưỡng lự (§9bis của
   `s1-embedding-plan.md`): nó cho 0,5 chắc chắn thay vì 50/50 giữa 0 và 1.
   Cùng kỳ vọng, thấp phương sai hơn — nhưng gold hiện có nghiêng về mã cha ở
   probe và mã `.9` ở bệnh án, nên chưa đủ căn cứ chọn. Giữ một mã, ghi lại ở
   đây để không phải khảo sát lại.

Nhãn TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM / KẾT_QUẢ_XÉT_NGHIỆM **để rỗng** — đề bài quy
định vậy, và Jaccard cho rỗng-gặp-rỗng bằng 1,0 nên đó cũng là nước đi đúng.
"""

from __future__ import annotations

from smart_medic.kb.query import KBStore, search_lexical
from smart_medic.stages.scoring import Entity

VOCAB_OF_TYPE = {"CHẨN_ĐOÁN": "icd10", "THUỐC": "rxnorm"}

# Số mã trả về. Xem quyết định 2 ở docstring trước khi tăng.
TOP_CODES = 1


def link_entity(store: KBStore, entity: Entity, *, top_codes: int = TOP_CODES) -> Entity:
    """Gắn `candidates` cho một entity. Nhãn không được gán mã thì trả nguyên."""
    vocab = VOCAB_OF_TYPE.get(entity.type)
    if vocab is None or not entity.text.strip():
        return entity
    hits = search_lexical(store, entity.text, vocab=vocab, top_k=top_codes, rerank=True)
    entity.candidates = tuple(h.code for h in hits[:top_codes])
    return entity


def link_all(store: KBStore, entities: list[Entity], *, top_codes: int = TOP_CODES) -> list[Entity]:
    """Gắn mã cho cả danh sách. Có cache theo `(nhãn, chuỗi)` vì bệnh án lặp
    mention rất nhiều — `"tăng huyết áp"` xuất hiện 6 lần trong bộ gold."""
    cache: dict[tuple[str, str], tuple[str, ...]] = {}
    for e in entities:
        vocab = VOCAB_OF_TYPE.get(e.type)
        if vocab is None:
            continue
        key = (e.type, e.text.strip().lower())
        if key not in cache:
            link_entity(store, e, top_codes=top_codes)
            cache[key] = e.candidates
        else:
            e.candidates = cache[key]
    return entities
