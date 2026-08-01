"""Hợp đồng API đọc — bề mặt công khai giữa KB và downstream.

`STUBBED` là **cổng theo phase**: khi một hàm được implement, test này đỏ và
buộc phải cập nhật danh sách. Nhờ vậy không thể lặng lẽ để hàm ở trạng thái
nửa vời, và cũng không thể quên rằng nó đã xong.
"""

from __future__ import annotations

import inspect

import pytest

from smart_medic.kb import query

PUBLIC_API = {
    "lookup": ("store", "vocab", "code"),
    "search_lexical": (
        "store",
        "text",
        "vocab",
        "lang",
        "entity_kind",
        "tiers",
        "max_fan_in",
        "top_k",
        # Cộng thêm, mặc định False ⇒ code cũ không đổi hành vi.
        "rerank",
    ),
    "search_dense": ("store", "text", "vocab", "top_k"),
    "neighbors": ("store", "concept_id", "rel", "direction"),
    "ancestors": ("store", "concept_id", "max_dist"),
    "is_ancestor": ("store", "ancestor_id", "descendant_id"),
    "lca": ("store", "a", "b"),
    "similarity": ("store", "a", "b", "method"),
}

# Cập nhật sau mỗi phase — test đỏ nếu quên.
#   Phase 0: tất cả
#   Phase 1: bỏ lookup / search_lexical / neighbors
#   Phase 3: bỏ ancestors / is_ancestor / lca / similarity  (bảng `closure`)
#   Phase 5: bỏ search_dense  (kb.faiss) → không còn stub nào
STUBBED: set[str] = set()
IMPLEMENTED = set(PUBLIC_API) - STUBBED


@pytest.mark.parametrize("name", sorted(PUBLIC_API))
def test_ham_ton_tai_va_duoc_export(name):
    assert name in query.__all__
    assert callable(getattr(query, name))


@pytest.mark.parametrize("name", sorted(PUBLIC_API))
def test_chu_ky_ham_dung_hop_dong(name):
    got = tuple(inspect.signature(getattr(query, name)).parameters)
    assert got == PUBLIC_API[name]


def _call_with_dummies(fn):
    """Gọi hàm với None cho mọi tham số, tôn trọng keyword-only."""
    sig = inspect.signature(fn)
    args, kwargs = [], {}
    for pname, p in sig.parameters.items():
        if p.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[pname] = None
        else:
            args.append(None)
    return fn(*args, **kwargs)


@pytest.mark.parametrize("name", sorted(STUBBED))
def test_ham_chua_implement_bao_loi_ro_rang(name):
    """Stub phải raise NotImplementedError ngay, trước khi chạm tới store."""
    with pytest.raises(NotImplementedError):
        _call_with_dummies(getattr(query, name))


def test_dataclass_duoc_export():
    for cls in ("Concept", "Term", "Candidate", "KBStore"):
        assert cls in query.__all__
