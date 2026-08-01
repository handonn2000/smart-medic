"""Bất biến của image `runtime`: truy vấn được mà KHÔNG cần nguồn thô 9 GB.

Đây là điều kiện để chia sẻ KB cho đồng đội/BTC bằng cách chỉ gửi artifact.
Test này chạy native nên bắt được hồi quy ngay cả khi không có Docker daemon —
nếu một hàm trong `query/` lỡ chạm tới `config.ICD_PDF` thì nó đỏ ở đây.
"""

from __future__ import annotations

import importlib

import pytest

from smart_medic.kb import config

pytestmark = pytest.mark.slow


@pytest.fixture
def kb_khong_nguon_tho(monkeypatch, tmp_path):
    """Trỏ RAW_DIR vào thư mục rỗng — mô phỏng đúng image runtime."""
    if not config.KB_SQLITE.is_file():
        pytest.skip("chưa có artifact — chạy `smk kb build`")
    artifact = config.KB_SQLITE
    monkeypatch.setenv("SMK_RAW_DIR", str(tmp_path / "rong"))
    importlib.reload(config)
    from smart_medic.kb.query import KBStore

    with KBStore(artifact) as s:
        yield s
    monkeypatch.delenv("SMK_RAW_DIR")
    importlib.reload(config)


def test_nguon_tho_that_su_khong_ton_tai(kb_khong_nguon_tho):
    importlib.reload(config)
    assert not config.ICD_PDF.exists()
    assert not config.RXNORM_RRF.exists()


def test_lookup_van_chay(kb_khong_nguon_tho):
    from smart_medic.kb.query import lookup

    assert lookup(kb_khong_nguon_tho, "icd10", "K21.0") is not None
    assert lookup(kb_khong_nguon_tho, "rxnorm", "243670") is not None


def test_search_van_chay(kb_khong_nguon_tho):
    from smart_medic.kb.query import search_lexical

    hits = search_lexical(kb_khong_nguon_tho, "thiếu men G6PD", vocab="icd10", top_k=5)
    assert any(h.code.startswith("D55") for h in hits)


def test_phan_cap_van_chay(kb_khong_nguon_tho):
    from smart_medic.kb.query import ancestors, is_ancestor, lookup, similarity

    child = lookup(kb_khong_nguon_tho, "icd10", "K21.0")
    parent = lookup(kb_khong_nguon_tho, "icd10", "K21")
    anc = ancestors(kb_khong_nguon_tho, child.concept_id)
    assert "K21" in {a.code for a in anc}
    assert is_ancestor(kb_khong_nguon_tho, parent.concept_id, child.concept_id)
    assert not is_ancestor(kb_khong_nguon_tho, child.concept_id, parent.concept_id)

    sib = lookup(kb_khong_nguon_tho, "icd10", "K21.9")
    s = similarity(kb_khong_nguon_tho, child.concept_id, sib.concept_id)
    assert 0.0 < s < 1.0
    assert similarity(kb_khong_nguon_tho, child.concept_id, child.concept_id) == 1.0


def test_query_khong_import_module_build():
    """`query/` không được kéo theo pymupdf/pyarrow — image runtime không có chúng."""
    import subprocess
    import sys

    code = (
        "import sys; import smart_medic.kb.query; "
        "bad = [m for m in ('fitz', 'pymupdf', 'pyarrow') if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"query kéo theo dependency chỉ có ở builder: {r.stdout.strip()}"
