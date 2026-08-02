"""Bốn bất biến của corpus + phân bố nhiễu + tính tái lập."""

from __future__ import annotations

import pytest

from smart_medic.synth import export, noise, render, stats
from smart_medic.synth.schema import TYPES_WITH_CANDIDATES


@pytest.fixture(scope="module")
def docs():
    """20 tài liệu là đủ cho bất biến; phân bố nhiễu cần mẫu lớn hơn (xem cổng)."""
    return render.generate(20, seed=7)


class TestBonBatBien:
    def test_tat_ca_pass(self, docs):
        for d in docs:
            export.verify(d)  # dùng lại `solve.check_invariants` của bài nộp

    def test_1_span_cat_lai_dung(self, docs):
        for d in docs:
            for s in d.spans:
                assert d.text[s.start : s.end] == s.text, (d.name, s)

    def test_2_khong_chong_lan(self, docs):
        for d in docs:
            ordered = sorted(d.spans, key=lambda s: (s.start, s.end))
            for a, b in zip(ordered, ordered[1:], strict=False):
                assert a.end <= b.start, (d.name, a, b)

    def test_3_nhan_cam_thi_candidates_rong(self, docs):
        for d in docs:
            for s in d.spans:
                if s.type not in TYPES_WITH_CANDIDATES:
                    assert s.candidates == (), (d.name, s)

    def test_4_cham_duoc_bang_scoring(self, docs):
        from smart_medic.stages.scoring import Entity, score_document

        for d in docs:
            ents = [
                Entity(s.text, s.type, s.start, s.end, s.candidates, s.assertions) for s in d.spans
            ]
            assert score_document(ents, ents).final == pytest.approx(1.0)


class TestSpanAm:
    def test_khong_span_nao_phu_len_cum_gay_nhieu(self, docs):
        """Lý do tồn tại của span âm: dạy model KHI NÀO KHÔNG BẮN."""
        for d in docs:
            for ds, de in d.distractors:
                for s in d.spans:
                    assert not (s.start < de and s.end > ds), (d.name, s)

    def test_co_du_mat_do(self, docs):
        st = stats.measure(docs)
        assert st["distractor_share"]["value"] >= 0.10


class TestTaiLap:
    def test_cung_seed_cho_corpus_y_het(self):
        a = render.generate(5, seed=42)
        b = render.generate(5, seed=42)
        assert [d.text for d in a] == [d.text for d in b]
        assert [[s.to_dict() for s in d.spans] for d in a] == [
            [s.to_dict() for s in d.spans] for d in b
        ]

    def test_seed_khac_cho_corpus_khac(self):
        assert render.generate(3, seed=1)[0].text != render.generate(3, seed=2)[0].text


class TestNhieuTheoTaiLieu:
    def test_che_thuoc_la_tinh_chat_TAI_LIEU(self):
        """★ Rút theo mention thì 83% tài liệu dính mask — lệch +52,6 điểm."""
        import random

        rng = random.Random(0)
        drawn = [noise.DocNoise.draw(rng).mask_drugs for _ in range(2000)]
        assert 0.25 <= sum(drawn) / len(drawn) <= 0.35

    def test_transform_chi_ap_khi_bat_NFD(self):
        on = noise.DocNoise(nfd=True, bullets=True, labels=True, qa_voice=True, mask_drugs=True)
        off = noise.DocNoise(nfd=False, bullets=True, labels=True, qa_voice=True, mask_drugs=True)
        assert on.transform("tiền") != "tiền"
        assert off.transform("tiền") == "tiền"
