"""Enrichment — ba quy tắc bất biến (§P3.3) và thuật toán bao đóng."""

from __future__ import annotations

import json
import sqlite3
import textwrap

import pytest

from smart_medic.kb.enrich import closure
from smart_medic.kb.enrich.base import EnrichBatch
from smart_medic.kb.enrich.curated import CuratedSynonyms
from smart_medic.kb.enrich.icd10cm_rollup import cm_to_who, cm_to_who_candidates
from smart_medic.kb.enrich.snomed_terms import semantic_tag
from smart_medic.kb.schema.version import read_ddl


class TestBatBienEnrichment:
    def test_khong_duoc_sinh_dong_authoritative(self):
        b = EnrichBatch()
        with pytest.raises(ValueError, match="authoritative"):
            b.add_term(
                vocab="icd10",
                code="A00",
                source="s",
                term="x",
                lang="vi",
                term_type="t",
                tier="authoritative",
            )

    def test_derived_bat_buoc_co_evidence(self):
        b = EnrichBatch()
        with pytest.raises(ValueError, match="evidence"):
            b.add_term(
                vocab="icd10",
                code="A00",
                source="s",
                term="x",
                lang="vi",
                term_type="t",
                tier="derived",
            )

    def test_generated_khong_can_evidence(self):
        b = EnrichBatch()
        b.add_term(
            vocab="icd10",
            code="A00",
            source="s",
            term="x",
            lang="vi",
            term_type="t",
            tier="generated",
        )
        assert len(b.terms) == 1

    def test_evidence_duoc_serialize_thanh_json(self):
        b = EnrichBatch()
        b.add_term(
            vocab="icd10",
            code="A00",
            source="s",
            term="x",
            lang="vi",
            term_type="t",
            tier="derived",
            evidence={"via": "test", "fan_in": 3},
        )
        assert json.loads(b.terms[0]["evidence"])["fan_in"] == 3

    def test_term_rong_bi_bo(self):
        b = EnrichBatch()
        b.add_term(
            vocab="icd10",
            code="A00",
            source="s",
            term="   ",
            lang="vi",
            term_type="t",
            tier="generated",
        )
        assert b.terms == []

    def test_norm_va_ascii_duoc_tinh_san(self):
        b = EnrichBatch()
        b.add_term(
            vocab="icd10",
            code="A00",
            source="s",
            term="Đái Tháo Đường",
            lang="vi",
            term_type="t",
            tier="generated",
        )
        assert b.terms[0]["norm_term"] == "đái tháo đường"
        assert b.terms[0]["ascii_term"] == "dai thao duong"


class TestCmToWho:
    @pytest.mark.parametrize(
        ("cm", "cands"),
        [
            ("K2100", ["K21.00", "K21.0", "K21"]),
            ("K219", ["K21.9", "K21"]),
            ("A000", ["A00.0", "A00"]),
            ("A15", ["A15"]),
        ],
    )
    def test_ung_vien_xep_tu_dac_hieu_nhat(self, cm, cands):
        assert cm_to_who_candidates(cm) == cands

    def test_chon_ung_vien_dac_hieu_nhat_CO_THAT(self):
        """`K21.00` không tồn tại trong WHO → phải rơi về `K21.0`."""
        assert cm_to_who("K2100", {"K21", "K21.0", "K21.9"}) == "K21.0"

    def test_roi_ve_ma_3_ky_tu_khi_khong_co_ma_con(self):
        assert cm_to_who("K2100", {"K21"}) == "K21"

    def test_khong_co_ung_vien_nao_thi_none(self):
        assert cm_to_who("K2100", {"J18"}) is None

    def test_ma_khong_hop_le_tra_none(self):
        assert cm_to_who("XX") is None


class TestSemanticTag:
    @pytest.mark.parametrize(
        ("fsn", "tag"),
        [
            ("Pneumonia (disorder)", "disorder"),
            ("Cough (finding)", "finding"),
            ("Appendectomy (procedure)", "procedure"),
            ("Aspirin (substance)", "substance"),
        ],
    )
    def test_trich_the(self, fsn, tag):
        assert semantic_tag(fsn) == tag

    def test_khong_co_the_thi_bao_unknown(self):
        """Không im lặng bỏ qua — H2 yêu cầu đánh dấu tường minh."""
        assert semantic_tag("Tên không có thẻ") == "unknown"


class TestCurated:
    def test_bo_qua_ma_khong_co_trong_kb_va_bao_cao(self, tmp_path):
        p = tmp_path / "syn.yaml"
        p.write_text(
            textwrap.dedent("""
            - {vocab: icd10, code: K21, synonyms: ["GERD"]}
            - {vocab: icd10, code: ZZ99, synonyms: ["không tồn tại"]}
            """),
            encoding="utf-8",
        )
        e = CuratedSynonyms(p)
        batch = e.enrich({"icd10": {"K21"}})
        assert [t["term"] for t in batch.terms] == ["GERD"]
        assert e.skipped == [("icd10", "ZZ99")]

    def test_tier_la_generated(self, tmp_path):
        p = tmp_path / "syn.yaml"
        p.write_text('- {vocab: icd10, code: K21, synonyms: ["GERD"]}\n', encoding="utf-8")
        batch = CuratedSynonyms(p).enrich({"icd10": {"K21"}})
        assert batch.terms[0]["tier"] == "generated"


class TestClosure:
    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(read_ddl())
        for i in range(1, 7):
            conn.execute(
                "INSERT INTO concepts VALUES (?,'icd10',?,'disease',NULL,NULL,1)", (i, f"C{i}")
            )
        yield conn
        conn.close()

    def _isa(self, conn, pairs):
        conn.executemany(
            "INSERT INTO relations (src_concept, rel, dst_concept, tier) VALUES (?,'isa',?,'authoritative')",
            pairs,
        )

    def test_chuoi_thang(self, db):
        self._isa(db, [(3, 2), (2, 1)])  # C3 → C2 → C1
        rows = {(a, d, k) for a, d, k in closure.compute(db)}
        assert (2, 3, 1) in rows
        assert (1, 2, 1) in rows
        assert (1, 3, 2) in rows  # tổ tiên gián tiếp, khoảng cách 2

    def test_khong_co_tu_to_tien(self, db):
        self._isa(db, [(2, 1)])
        assert all(a != d for a, d, _ in closure.compute(db))

    def test_da_ke_thua_lay_duong_ngan_nhat(self, db):
        # C4 có hai cha C2, C3; cả hai cùng thuộc C1 → C1 cách C4 đúng 2
        self._isa(db, [(4, 2), (4, 3), (2, 1), (3, 1)])
        d = {(a, desc): dist for a, desc, dist in closure.compute(db)}
        assert d[(1, 4)] == 2

    def test_bo_qua_chu_trinh_thay_vi_treo(self, db):
        """Dữ liệu chuẩn không nên có chu trình, nhưng gặp thì phải không treo."""
        self._isa(db, [(1, 2), (2, 1)])
        assert closure.compute(db) == []

    def test_khong_co_canh_isa_thi_rong(self, db):
        assert closure.compute(db) == []

    def test_build_ghi_vao_bang(self, db):
        self._isa(db, [(3, 2), (2, 1)])
        n = closure.build(db)
        assert n == db.execute("SELECT count(*) FROM closure").fetchone()[0] == 3

    def test_build_xoa_du_lieu_cu(self, db):
        self._isa(db, [(2, 1)])
        closure.build(db)
        closure.build(db)
        assert db.execute("SELECT count(*) FROM closure").fetchone()[0] == 1
