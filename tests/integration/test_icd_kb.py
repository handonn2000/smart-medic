"""Kiểm tra artifact ICD đã build.

Đánh dấu `slow` vì cần `data/artifacts/kb.sqlite` — CI không có nguồn thô 9 GB
nên bỏ qua ở đó, còn ở máy dev thì đây là lưới an toàn cuối cùng.
"""

from __future__ import annotations

import sqlite3

import pytest

from smart_medic.kb import config
from smart_medic.kb.query import KBStore, lookup, neighbors, search_lexical

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def store():
    if not config.KB_SQLITE.is_file():
        pytest.skip("chưa có artifact — chạy `smk kb build --source icd`")
    with KBStore() as s:
        yield s


class TestLookup:
    def test_ma_co_thuc(self, store):
        c = lookup(store, "icd10", "K21.0")
        assert c is not None
        assert "trào ngược" in (c.pref_vi or "").lower()

    def test_co_ca_ten_tieng_anh(self, store):
        """Giá trị riêng của PDF so với ICD10.csv — mở đường cho embedding tiếng Anh."""
        c = lookup(store, "icd10", "D55.0")
        assert c.pref_en and "glucose-6-phosphate" in c.pref_en.lower()

    def test_ma_khong_ton_tai(self, store):
        assert lookup(store, "icd10", "ZZ99.9") is None

    def test_ma_mo_rong_cua_byt(self, store):
        """1.101 mã chỉ có ở ICD10.csv — bằng chứng hai nguồn bổ sung nhau."""
        assert lookup(store, "icd10", "A17.83") is not None


class TestSearchLexical:
    def test_mention_rut_gon_van_tim_duoc(self, store):
        """Điểm yếu 2 của PRD: "Thiếu men G6PD" ≠ tên ICD chuẩn dài."""
        hits = search_lexical(store, "Thiếu men G6PD", vocab="icd10", top_k=10)
        assert any(h.code.startswith("D55") for h in hits)

    def test_go_khong_dau(self, store):
        hits = search_lexical(store, "thieu men g6pd", vocab="icd10", top_k=10)
        assert any(h.code.startswith("D55") for h in hits)

    def test_loc_theo_entity_kind(self, store):
        hits = search_lexical(
            store, "trào ngược dạ dày", vocab="icd10", entity_kind="disease", top_k=10
        )
        assert hits and all(h.concept.entity_kind == "disease" for h in hits)

    def test_moi_concept_chi_xuat_hien_mot_lan(self, store):
        hits = search_lexical(store, "viêm phổi", vocab="icd10", top_k=20)
        ids = [h.concept.concept_id for h in hits]
        assert len(ids) == len(set(ids))

    def test_score_giam_dan(self, store):
        hits = search_lexical(store, "tăng huyết áp", vocab="icd10", top_k=10)
        assert hits == sorted(hits, key=lambda h: -h.score)

    def test_truy_van_rong_tra_rong(self, store):
        assert search_lexical(store, "   ", vocab="icd10") == []


class TestPhanCap:
    def test_ma_con_isa_ma_cha(self, store):
        child = lookup(store, "icd10", "K21.0")
        parents = neighbors(store, child.concept_id, rel="isa", direction="out")
        assert any(p.code == "K21" for p in parents)

    def test_chieu_nguoc_lai(self, store):
        parent = lookup(store, "icd10", "K21")
        children = neighbors(store, parent.concept_id, rel="isa", direction="in")
        assert {c.code for c in children} >= {"K21.0", "K21.9"}

    def test_direction_khong_hop_le(self, store):
        with pytest.raises(ValueError):
            neighbors(store, 1, direction="sideways")


class TestToanVen:
    def test_so_ma_benh_khop_hai_nguon(self, store):
        n = store.conn.execute(
            "SELECT count(*) FROM concepts WHERE vocab='icd10' AND entity_kind='disease'"
        ).fetchone()[0]
        assert n == 16944  # 15.843 từ PDF + 1.101 chỉ có ở ICD10.csv

    def test_khong_con_ky_hieu_dagger_asterisk(self, store):
        n = store.conn.execute(
            "SELECT count(*) FROM concepts WHERE code LIKE '%†%' OR code LIKE '%*%'"
        ).fetchone()[0]
        assert n == 0

    def test_quan_he_manifests_as_duoc_trich(self, store):
        """`A06.4† "Amoebic liver abscess (K77.0*)"` → cạnh A06.4 → K77.0."""
        n = store.conn.execute(
            "SELECT count(*) FROM relations WHERE rel='manifests_as'"
        ).fetchone()[0]
        assert n > 0

    def test_artifact_chi_doc(self, store):
        with pytest.raises(sqlite3.OperationalError):
            store.conn.execute("DELETE FROM concepts")
