"""Gán `concept_id` TẤT ĐỊNH.

★ Đây là bất biến quan trọng nhất của toàn kiến trúc.

`concept_id` là khoá join giữa SQLite và FAISS. Nếu nó đổi giữa hai lần build,
mọi FAISS index đã dựng sẽ trỏ nhầm concept **mà không báo lỗi** — dạng hỏng
âm thầm, không có triệu chứng, chỉ biểu hiện thành điểm số tụt không rõ lý do.

Quy tắc: id = thứ tự sau khi sort `(vocab, code)` theo codepoint, đánh số từ 1.
Sort theo codepoint không phụ thuộc locale nên tái lập được trên mọi máy.
Gán theo thứ tự insert là SAI.
"""

from __future__ import annotations

from collections.abc import Iterable

# Khi cùng một mã xuất hiện với nhiều `entity_kind` (mã 3 ký tự vừa là nhóm
# vừa là mã bệnh, ví dụ K21), giữ loại cụ thể hơn.
ENTITY_KIND_PRIORITY = {
    "disease": 0,
    "drug": 0,
    "clinical_finding": 0,
    "icd_group": 10,
    "unknown": 99,
}


def assign_ids(keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """`{(vocab, code): concept_id}` — tất định, đánh số từ 1."""
    return {key: i for i, key in enumerate(sorted(set(keys)), start=1)}


def pick_entity_kind(kinds: Iterable[str]) -> str:
    """Chọn `entity_kind` khi một mã đến từ nhiều nguồn với nhãn khác nhau."""
    ordered = sorted(set(kinds), key=lambda k: (ENTITY_KIND_PRIORITY.get(k, 50), k))
    return ordered[0] if ordered else "unknown"


def first_non_null(values: Iterable[str | None]) -> str | None:
    """Giá trị không rỗng đầu tiên theo thứ tự đã cho (thứ tự nguồn ổn định)."""
    for v in values:
        if v:
            return v
    return None
