"""Weighted interval scheduling — tối ưu TOÀN CỤC và TẤT ĐỊNH."""

from __future__ import annotations

import random

import pytest

from smart_medic.stages.arbiter import Proposal, select


def p(start, end, weight, typ="THUỐC", proposer="r", text=None):
    return Proposal(start, end, typ, text or f"[{start},{end})", weight, proposer)


def spans(ents):
    return [(e.start, e.end) for e in ents]


class TestToiUu:
    def test_chon_span_nang_hon_khi_chong_lan(self):
        assert spans(select([p(0, 10, 1.0), p(5, 8, 5.0)])) == [(5, 8)]

    def test_giu_ca_hai_khi_khong_chong_lan(self):
        assert spans(select([p(0, 5, 1.0), p(6, 9, 1.0)])) == [(0, 5), (6, 9)]

    def test_ke_nhau_KHONG_phai_chong_lan(self):
        """Khớp đúng định nghĩa của `solve.check_invariants`: `a.end > b.start`."""
        assert spans(select([p(0, 5, 1.0), p(5, 9, 1.0)])) == [(0, 5), (5, 9)]

    def test_hai_span_nhe_thang_mot_span_nang(self):
        """★ Đây là chỗ greedy `taken` SAI mà quy hoạch động đúng.

        Greedy lấy span nặng nhất trước (6.0) rồi loại cả hai span nhẹ. Tối ưu
        toàn cục là lấy hai span nhẹ: 4 + 4 = 8 > 6.
        """
        got = select([p(0, 4, 4.0), p(5, 9, 4.0), p(2, 7, 6.0)])
        assert spans(got) == [(0, 4), (5, 9)]

    def test_toi_uu_tren_chuoi_dai(self):
        """So với vét cạn trên 12 khoảng ngẫu nhiên."""
        from itertools import combinations

        rng = random.Random(3)
        items = [
            p(s, s + rng.randint(1, 5), round(rng.uniform(0.1, 3.0), 2))
            for s in rng.sample(range(0, 40), 12)
        ]
        got = sum(i.weight for i in items if (i.start, i.end) in set(spans(select(items))))
        best = 0.0
        for r in range(len(items) + 1):
            for combo in combinations(items, r):
                ordered = sorted(combo, key=lambda x: x.start)
                if all(a.end <= b.start for a, b in zip(ordered, ordered[1:], strict=False)):
                    best = max(best, sum(x.weight for x in combo))
        assert got == pytest.approx(best)


class TestTatDinh:
    """★ Không tất định thì `smk eval compare` mất ý nghĩa — Δ đo được có thể chỉ
    là thứ tự duyệt đổi, không phải hệ thống đổi."""

    def test_dao_thu_tu_dau_vao_cho_cung_ket_qua(self):
        items = [p(0, 5, 1.0, proposer="a"), p(3, 8, 1.0, proposer="b"), p(9, 12, 2.0)]
        rng = random.Random(0)
        base = spans(select(items))
        for _ in range(20):
            shuffled = items[:]
            rng.shuffle(shuffled)
            assert spans(select(shuffled)) == base

    def test_hoa_diem_van_tat_dinh(self):
        """Hai đề xuất TRÙNG KHỚP hoàn toàn trừ tên proposer."""
        a = p(0, 5, 1.0, proposer="model")
        b = p(0, 5, 1.0, proposer="rule")
        assert select([a, b])[0].text == select([b, a])[0].text

    def test_goi_lai_nhieu_lan_cho_cung_ket_qua(self):
        items = [p(0, 5, 1.0), p(2, 9, 1.5), p(8, 11, 0.5)]
        assert spans(select(items)) == spans(select(items))


class TestBienDangSuyBien:
    def test_rong(self):
        assert select([]) == []

    def test_mot_span(self):
        assert spans(select([p(0, 3, 1.0)])) == [(0, 3)]

    def test_trong_so_0_van_duoc_chon_neu_khong_canh_tranh(self):
        assert spans(select([p(0, 3, 0.0)])) == [(0, 3)]

    def test_trong_so_am_bi_bo_qua(self):
        """Trọng số âm = proposer nói 'đừng lấy'. Không được ép vào nghiệm."""
        assert spans(select([p(0, 3, -1.0), p(5, 8, 1.0)])) == [(5, 8)]


class TestGiuNguyenDuLieu:
    def test_mang_theo_candidates_va_assertions(self):
        pr = Proposal(0, 5, "CHẨN_ĐOÁN", "viêm phổi", 1.0, "r", ("J18.9",), ("isHistorical",))
        e = select([pr])[0]
        assert e.candidates == ("J18.9",) and e.assertions == ("isHistorical",)

    def test_ket_qua_sap_theo_vi_tri(self):
        got = select([p(9, 12, 1.0), p(0, 5, 1.0), p(6, 8, 1.0)])
        assert spans(got) == [(0, 5), (6, 8), (9, 12)]


class TestTrongSoDaDo:
    """Trọng số = precision ĐO ĐƯỢC trên `gold_batch1`, không phải đặt tay."""

    def test_moi_cap_deu_co_so_do(self):
        from smart_medic.stages import proposers

        for (proposer, typ), w in proposers.WEIGHTS.items():
            assert 0.0 < w <= 1.0, (proposer, typ, w)

    def test_so_do_lat_nguoc_gia_dinh_ke_hoach(self):
        """★ Prompt Phase 4 đoán 'TRIỆU_CHỨNG: model thắng luật'. Đo ra NGƯỢC LẠI.

        Khoá con số vào test để ai đổi trọng số thì phải đối diện với số đo, chứ
        không lặng lẽ chỉnh về theo trực giác.
        """
        from smart_medic.stages.proposers import MODEL, RULE_GAZETTEER, WEIGHTS

        assert WEIGHTS[(RULE_GAZETTEER, "TRIỆU_CHỨNG")] > WEIGHTS[(MODEL, "TRIỆU_CHỨNG")]
        assert WEIGHTS[(MODEL, "CHẨN_ĐOÁN")] > WEIGHTS[(RULE_GAZETTEER, "CHẨN_ĐOÁN")]
        assert WEIGHTS[(RULE_GAZETTEER, "THUỐC")] > WEIGHTS[(MODEL, "THUỐC")]

    def test_proposer_chua_do_khong_thang_proposer_da_do(self):
        from smart_medic.stages.proposers import DEFAULT_WEIGHT, WEIGHTS

        assert min(WEIGHTS.values()) >= DEFAULT_WEIGHT

    def test_thuoc_bi_che_co_trong_so_cao_nhat(self):
        """`***` không proposer nào khác chạm tới; đừng để span dài nuốt mất."""
        from smart_medic.stages.proposers import MASKED_WEIGHT, WEIGHTS

        assert max(WEIGHTS.values()) < MASKED_WEIGHT


class TestSuyBienVePipelineLuat:
    def test_trong_so_model_0_thi_khong_goi_tagger(self, monkeypatch):
        """An toàn theo kiến tạo: Phase 4 không thể làm hỏng thứ đang có."""
        from smart_medic.stages import proposers

        called = []
        monkeypatch.setattr(proposers.tagger, "detect", lambda *a, **k: called.append(1) or [])
        monkeypatch.setenv("SMK_ARBITER_MODEL_WEIGHT", "0")

        class FakeGaz:
            max_ngram = 1
            entries: dict = {}

            def lookup(self, key):
                return None

        proposers.propose("sốt cao", None, FakeGaz(), model_weight=0.0)
        assert called == []


class TestRerankBatBuoc:
    """★ `rerank` mặc định TẮT ở `search_lexical`. Quên bật = mất 45 điểm R@1
    nhánh thuốc — đo được, không phải ước lượng. Khoá cứng bằng test hồi quy."""

    def test_link_entity_luon_goi_voi_rerank_True(self, monkeypatch):
        from smart_medic.stages import linking
        from smart_medic.stages.scoring import Entity

        seen = {}
        monkeypatch.setattr(linking, "search_lexical", lambda *a, **kw: seen.update(kw) or [])
        linking.link_entity(None, Entity("aspirin", "THUỐC", 0, 7))
        assert seen.get("rerank") is True

    def test_van_bat_rerank_khi_di_qua_link_all(self, monkeypatch):
        from smart_medic.stages import linking
        from smart_medic.stages.scoring import Entity

        seen = {}
        monkeypatch.setattr(linking, "search_lexical", lambda *a, **kw: seen.update(kw) or [])
        linking.link_all(None, [Entity("viêm phổi", "CHẨN_ĐOÁN", 0, 9)])
        assert seen.get("rerank") is True
