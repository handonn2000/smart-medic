"""Dense index — trọng tâm là bất biến chống LỆCH `concept_id`.

FAISS trả về id kiểu int. Nếu artifact .sqlite được build lại và id đổi, mọi
truy vấn dense sẽ trỏ nhầm concept **mà không báo lỗi**. Đó là failure mode
nguy hiểm nhất của cả kiến trúc (§8) vì nó không có triệu chứng — chỉ biểu hiện
thành điểm số tụt không rõ lý do.
"""

from __future__ import annotations

import json

import pytest

from smart_medic.kb import config

pytestmark = pytest.mark.slow

faiss = pytest.importorskip("faiss", reason="cần extra `dense`")


@pytest.fixture(scope="module")
def dense_mod():
    from smart_medic.kb import dense

    if not config.KB_FAISS.is_file():
        pytest.skip("chưa có dense index — chạy `smk kb dense`")
    return dense


@pytest.fixture(scope="module")
def store():
    from smart_medic.kb.query import KBStore

    if not config.KB_SQLITE.is_file():
        pytest.skip("chưa có artifact")
    with KBStore() as s:
        yield s


class TestDongBoVoiArtifact:
    def test_index_va_sqlite_cung_schema_version(self, dense_mod):
        from smart_medic.kb.schema.version import SCHEMA_VERSION

        _, meta = dense_mod.load_index()
        assert meta.schema_version == SCHEMA_VERSION

    def test_so_vector_khop_so_concept_active(self, dense_mod, store):
        _, meta = dense_mod.load_index()
        n = store.conn.execute(
            "SELECT count(*) FROM concepts WHERE is_active = 1 "
            "AND coalesce(pref_vi, pref_en) IS NOT NULL"
        ).fetchone()[0]
        assert meta.n_vectors == n

    def test_gan_voi_dung_artifact(self, dense_mod):
        """Canh theo NỘI DUNG, không theo byte.

        Cùng một KB build ở hai môi trường SQLite khác nhau cho hai file khác
        byte nhưng concept_id giống hệt — index vẫn phải dùng được.
        """
        from smart_medic.kb.load import manifest

        _, meta = dense_mod.load_index()
        assert meta.content_sha256 == manifest.read()["content_sha256"]


class TestPhatHienLechId:
    """★ Cổng quan trọng nhất của Phase 5."""

    def test_artifact_khac_thi_TU_CHOI(self, dense_mod, tmp_path, monkeypatch):
        """Giả lập artifact bị build lại: đổi sha trong meta → phải nổ."""
        import shutil

        idx = tmp_path / "kb.faiss"
        shutil.copyfile(config.KB_FAISS, idx)
        meta = json.loads(dense_mod.meta_path(config.KB_FAISS).read_text(encoding="utf-8"))
        meta["content_sha256"] = "0" * 64
        dense_mod.meta_path(idx).write_text(json.dumps(meta), encoding="utf-8")

        with pytest.raises(dense_mod.IndexOutOfSync, match="NỘI DUNG"):
            dense_mod.load_index(idx)

    def test_schema_khac_thi_TU_CHOI(self, dense_mod, tmp_path):
        import shutil

        idx = tmp_path / "kb.faiss"
        shutil.copyfile(config.KB_FAISS, idx)
        meta = json.loads(dense_mod.meta_path(config.KB_FAISS).read_text(encoding="utf-8"))
        meta["schema_version"] = "0.0.1"
        dense_mod.meta_path(idx).write_text(json.dumps(meta), encoding="utf-8")

        with pytest.raises(dense_mod.IndexOutOfSync, match="schema"):
            dense_mod.load_index(idx)

    def test_thieu_index_thi_bao_ro_cach_sua(self, dense_mod, tmp_path):
        with pytest.raises(FileNotFoundError, match="smk kb dense"):
            dense_mod.load_index(tmp_path / "khong-co.faiss")


class TestSearchDense:
    def test_tra_ve_concept_dung_kieu(self, store):
        from smart_medic.kb.query import search_dense

        hits = search_dense(store, "trào ngược dạ dày", vocab="icd10", top_k=5)
        assert hits and all(h.concept.vocab == "icd10" for h in hits)

    def test_loc_theo_vocab(self, store):
        from smart_medic.kb.query import search_dense

        hits = search_dense(store, "aspirin", vocab="rxnorm", top_k=10)
        assert hits and all(h.concept.vocab == "rxnorm" for h in hits)

    def test_score_giam_dan(self, store):
        from smart_medic.kb.query import search_dense

        hits = search_dense(store, "viêm phổi", vocab="icd10", top_k=10)
        assert hits == sorted(hits, key=lambda h: -h.score)

    def test_bat_duoc_ca_khong_chung_token(self, store):
        """Giá trị riêng của dense: mention KHÔNG chia sẻ token với tên chuẩn.

        "ung thư" vs tên chuẩn "U ác tính, vị trí không xác định" — không token
        nào chung, nên BM25 thuần trượt (baseline Phase 2 xác nhận).
        """
        from smart_medic.kb.query import search_dense

        hits = search_dense(store, "ung thư", vocab="icd10", top_k=20)
        assert hits, "dense không trả về gì cho ca không chung token"
