"""Bộ đo Recall@k — kiểm bằng kết quả giả, không cần artifact."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from smart_medic.kb.evaluate import Case, Slice, load_probe, slices_of


def _case(rank, *, kind="disease", hard=False):
    return Case(mention="x", kind=kind, gold=("A00",), hard=hard, rank=rank)


class TestRecall:
    def test_recall_dem_dung_theo_nguong(self):
        s = Slice("t", [_case(1), _case(3), _case(11), _case(None)])
        assert s.recall_at(1) == 0.25
        assert s.recall_at(5) == 0.5
        assert s.recall_at(20) == 0.75

    def test_slice_rong_khong_chia_cho_khong(self):
        s = Slice("t", [])
        assert s.recall_at(5) == 0.0
        assert s.mrr() == 0.0

    def test_recall_don_dieu_tang_theo_k(self):
        s = Slice("t", [_case(1), _case(4), _case(18), _case(None)])
        assert s.recall_at(1) <= s.recall_at(5) <= s.recall_at(20)

    def test_truot_khong_duoc_tinh_la_trung(self):
        assert Slice("t", [_case(None), _case(None)]).recall_at(20) == 0.0


class TestMRR:
    def test_hang_1_cho_mrr_bang_1(self):
        assert Slice("t", [_case(1)]).mrr() == 1.0

    def test_nghich_dao_hang(self):
        assert Slice("t", [_case(2), _case(4)]).mrr() == pytest.approx(0.375)

    def test_truot_dong_gop_0(self):
        assert Slice("t", [_case(1), _case(None)]).mrr() == 0.5


class TestLatCat:
    def test_du_5_lat_cat(self):
        cases = [_case(1, kind="disease"), _case(2, kind="drug", hard=True)]
        assert [s.name for s in slices_of(cases)] == [
            "TỔNG THỂ",
            "chẩn đoán → ICD",
            "thuốc → RxNorm",
            "ca thường",
            "ca KHÓ",
        ]

    def test_lat_cat_khong_chong_lan_sai(self):
        cases = [_case(1, hard=False), _case(1, hard=True), _case(1, hard=True)]
        sl = {s.name: s for s in slices_of(cases)}
        assert len(sl["ca thường"].cases) + len(sl["ca KHÓ"].cases) == len(cases)

    def test_as_dict_co_du_khoa(self):
        d = Slice("t", [_case(1)]).as_dict()
        assert set(d) == {"n", "recall@1", "recall@5", "recall@20", "mrr"}


class TestLoadProbe:
    def test_doc_duoc_va_ep_kieu_ma(self, tmp_path):
        p = tmp_path / "probe.yaml"
        p.write_text(
            textwrap.dedent("""
            - {mention: "a", kind: disease, gold: [K21]}
            - {mention: "b", kind: drug, gold: [1191], hard: true}
            """),
            encoding="utf-8",
        )
        cases = load_probe(p)
        assert len(cases) == 2
        # mã RxNorm là số trong YAML nhưng phải thành str để so với `Concept.code`
        assert cases[1].gold == ("1191",)
        assert cases[1].hard is True

    def test_vocab_suy_ra_tu_kind(self, tmp_path):
        p = tmp_path / "probe.yaml"
        p.write_text('- {mention: "a", kind: drug, gold: ["1"]}\n', encoding="utf-8")
        assert load_probe(p)[0].vocab == "rxnorm"


class TestProbeSetThat:
    """Kiểm chính probe set trong repo — nó là dữ liệu được version-hoá."""

    PATH = pathlib.Path(__file__).resolve().parents[2] / "data/probe/retrieval_probe.yaml"

    @pytest.fixture(scope="class")
    def cases(self):
        if not self.PATH.is_file():
            pytest.skip("chưa có probe set")
        return load_probe(self.PATH)

    def test_du_so_luong(self, cases):
        assert len(cases) >= 120

    def test_phu_ca_hai_nhanh(self, cases):
        kinds = {c.kind for c in cases}
        assert kinds == {"disease", "drug"}

    def test_du_ca_kho(self, cases):
        assert sum(1 for c in cases if c.hard) >= 20

    def test_khong_co_mention_trung_lap(self, cases):
        mentions = [c.mention for c in cases]
        assert len(mentions) == len(set(mentions))

    def test_moi_ca_deu_co_gold(self, cases):
        assert all(c.gold for c in cases)
