"""Bộ chấm điểm nội bộ — WER, Jaccard, ghép span."""

from __future__ import annotations

import pytest

from smart_medic.stages.scoring import (
    Entity,
    Report,
    align,
    jaccard,
    score_document,
    text_score,
    wer,
)


def ent(text, typ="TRIỆU_CHỨNG", start=0, end=None, cand=(), asrt=()):
    return Entity(
        text=text,
        type=typ,
        start=start,
        end=end if end is not None else start + len(text),
        candidates=tuple(cand),
        assertions=tuple(asrt),
    )


class TestWER:
    def test_khop_hoan_toan(self):
        assert wer("ho đờm xanh", "ho đờm xanh") == 0.0

    def test_thieu_mot_tu(self):
        """Ví dụ của PRD §D: đáp án 3 từ, đoán 2 từ → WER = 1/3."""
        assert wer("ho đờm xanh", "ho đờm") == pytest.approx(1 / 3)

    def test_thua_tu_cung_bi_phat(self):
        assert wer("ho", "ho đờm xanh") == pytest.approx(2.0)

    def test_hai_ben_rong(self):
        assert wer("", "") == 0.0

    def test_khong_phan_biet_hoa_thuong(self):
        assert wer("Ho Đờm", "ho đờm") == 0.0

    def test_text_score_khong_am(self):
        """WER > 1 vẫn cho điểm 0, không kéo âm cả file."""
        assert text_score("ho", "ho đờm xanh vàng đặc") == 0.0


class TestJaccard:
    def test_ca_hai_rong_thi_bang_mot(self):
        """★ Quy ước PRD §6 — lý do 'mặc định rỗng' là nước đi an toàn."""
        assert jaccard((), ()) == 1.0

    def test_vi_du_prd(self):
        """Dự đoán {K21.0}, đáp án {K21.0, K21.9} → 0,5."""
        assert jaccard(("K21.0", "K21.9"), ("K21.0",)) == 0.5

    def test_khong_giao(self):
        assert jaccard(("A",), ("B",)) == 0.0

    def test_doan_thua_bi_phat(self):
        """Đoán bừa thêm mã kéo Jaccard xuống — phạt cả thiếu lẫn thừa."""
        assert jaccard(("K21.0",), ("K21.0", "J45.9")) == 0.5

    def test_mot_ben_rong_thi_bang_khong(self):
        assert jaccard(("A",), ()) == 0.0


class TestAlign:
    def test_ghep_theo_chong_lan(self):
        g = [ent("ho đờm xanh", start=10)]
        p = [ent("ho đờm", start=10)]
        matched, missed, spurious = align(g, p)
        assert len(matched) == 1
        assert not missed and not spurious

    def test_khong_chong_lan_thi_khong_ghep(self):
        matched, missed, spurious = align([ent("ho", start=0)], [ent("sốt", start=50)])
        assert not matched
        assert len(missed) == 1 and len(spurious) == 1

    def test_moi_entity_ghep_nhieu_nhat_mot_lan(self):
        g = [ent("ho đờm xanh", start=0)]
        p = [ent("ho", start=0), ent("đờm xanh", start=3)]
        matched, missed, spurious = align(g, p)
        assert len(matched) == 1
        assert len(spurious) == 1, "entity thừa phải bị tính là thừa"

    def test_uu_tien_cap_chong_lan_nhieu_nhat(self):
        g = [ent("đau thượng vị", start=0, end=13)]
        p = [ent("đau", start=0, end=3), ent("đau thượng vị", start=0, end=13)]
        matched, _missed, _sp = align(g, p)
        assert matched[0][1].text == "đau thượng vị"

    def test_tat_dinh_voi_thu_tu_dau_vao(self):
        g = [ent("a", start=0, end=5), ent("b", start=10, end=15)]
        p = [ent("b", start=10, end=15), ent("a", start=0, end=5)]
        m1, _, _ = align(g, p)
        m2, _, _ = align(g, list(reversed(p)))
        assert [(x.start, y.start) for x, y in m1] == [(x.start, y.start) for x, y in m2]


class TestScoreDocument:
    def test_hoan_hao(self):
        g = [ent("tăng huyết áp", "CHẨN_ĐOÁN", 0, cand=("I10",))]
        s = score_document(g, list(g))
        assert s.text == 1.0 and s.candidates == 1.0 and s.assertions == 1.0
        assert s.final == pytest.approx(1.0)

    def test_file_rong_ca_hai_ben(self):
        s = score_document([], [])
        assert s.final == pytest.approx(1.0)

    def test_bo_sot_entity_keo_diem_xuong(self):
        g = [ent("ho", start=0), ent("sốt", start=10)]
        s = score_document(g, [g[0]])
        assert s.text == pytest.approx(0.5)

    def test_entity_thua_cung_bi_phat(self):
        """★ Không phạt entity thừa thì rải bừa sẽ 'miễn phí'."""
        g = [ent("ho", start=0)]
        s = score_document(g, [g[0], ent("xxx", start=50)])
        assert s.text == pytest.approx(0.5)

    def test_sai_nhan_thi_mat_ca_candidate(self):
        g = [ent("tăng huyết áp", "CHẨN_ĐOÁN", 0, cand=("I10",))]
        p = [ent("tăng huyết áp", "TRIỆU_CHỨNG", 0, cand=("I10",))]
        s = score_document(g, p)
        assert s.text == 1.0, "span vẫn đúng"
        assert s.candidates == 0.0, "nhãn sai thì mã không được tính"

    def test_assertion_rong_khop_rong(self):
        g = [ent("ho", start=0)]
        s = score_document(g, [ent("ho", start=0)])
        assert s.assertions == 1.0


class TestReport:
    def test_trung_binh_tren_cac_file(self):
        r = Report(docs=[score_document([ent("ho", start=0)], [ent("ho", start=0)])])
        assert r.final == pytest.approx(1.0)
        assert r.f1 == pytest.approx(1.0)

    def test_pr_f1_khong_phu_thuoc_trong_so(self):
        g = [ent("ho", start=0), ent("sốt", start=10)]
        r = Report(docs=[score_document(g, [g[0]])])
        assert r.recall == 0.5
        assert r.precision == 1.0

    def test_type_accuracy_chi_tinh_tren_cap_ghep_duoc(self):
        g = [ent("ho", "TRIỆU_CHỨNG", 0)]
        p = [ent("ho", "CHẨN_ĐOÁN", 0)]
        r = Report(docs=[score_document(g, p)])
        assert r.recall == 1.0
        assert r.type_accuracy == 0.0

    def test_khong_co_file_thi_khong_no(self):
        assert Report().final == 0.0


class TestBangTheoNhanh:
    """Đại lượng đã lộ ra ưu tiên bị đảo ngược (`synth-corpus-plan-v2.md` §0.2).

    Ngữ nghĩa ở docstring module, mục "BẢNG THEO NHÁNH": recall đếm theo nhãn
    VÀNG, precision đếm theo nhãn DỰ ĐOÁN, và cả hai đo *phát hiện span* chứ
    không đo *phân loại* — phần phân loại tách riêng ở `type_accuracy`.
    """

    def test_recall_theo_nhan_vang(self):
        g = [
            ent("ho", "TRIỆU_CHỨNG", 0),
            ent("sốt", "TRIỆU_CHỨNG", 10),
            ent("viêm", "CHẨN_ĐOÁN", 20),
        ]
        r = Report(docs=[score_document(g, [g[0], g[2]])])
        bt = r.by_type()
        assert (bt["TRIỆU_CHỨNG"].gold, bt["TRIỆU_CHỨNG"].matched_gold) == (2, 1)
        assert bt["TRIỆU_CHỨNG"].recall == 0.5
        assert bt["CHẨN_ĐOÁN"].recall == 1.0

    def test_precision_theo_nhan_du_doan(self):
        g = [ent("ho", "TRIỆU_CHỨNG", 0)]
        p = [ent("ho", "TRIỆU_CHỨNG", 0), ent("bịa", "CHẨN_ĐOÁN", 30)]
        bt = Report(docs=[score_document(g, p)]).by_type()
        assert bt["TRIỆU_CHỨNG"].precision == 1.0
        assert (bt["CHẨN_ĐOÁN"].pred, bt["CHẨN_ĐOÁN"].precision) == (1, 0.0)

    def test_ghep_duoc_nhung_sai_nhan_van_tinh_la_phat_hien_dung(self):
        """★ Ranh giới dễ đọc nhầm nhất của bảng.

        Span khớp nhưng gán sai nhãn: recall của nhãn VÀNG = 1 và precision của
        nhãn DỰ ĐOÁN = 1 — vì span *đã được phát hiện*. Chỗ mất điểm nằm ở
        `type_accuracy`, đúng nơi nó thuộc về.
        """
        g = [ent("ho", "TRIỆU_CHỨNG", 0)]
        p = [ent("ho", "CHẨN_ĐOÁN", 0)]
        bt = Report(docs=[score_document(g, p)]).by_type()
        assert bt["TRIỆU_CHỨNG"].recall == 1.0
        assert bt["CHẨN_ĐOÁN"].precision == 1.0
        assert bt["TRIỆU_CHỨNG"].type_accuracy == 0.0

    def test_gop_tren_nhieu_file(self):
        g1 = [ent("ho", "TRIỆU_CHỨNG", 0)]
        g2 = [ent("sốt", "TRIỆU_CHỨNG", 0), ent("đau", "TRIỆU_CHỨNG", 10)]
        r = Report(docs=[score_document(g1, g1), score_document(g2, [g2[0]])])
        s = r.by_type()["TRIỆU_CHỨNG"]
        assert (s.gold, s.matched_gold, s.recall) == (3, 2, pytest.approx(2 / 3))

    def test_file_rong_hai_ben_khong_sinh_nhan_nao(self):
        assert Report(docs=[score_document([], [])]).by_type() == {}

    def test_as_dict_co_du_khoa(self):
        g = [ent("ho", "TRIỆU_CHỨNG", 0)]
        d = Report(docs=[score_document(g, g)]).by_type()["TRIỆU_CHỨNG"].as_dict()
        assert set(d) == {"gold", "pred", "matched", "recall", "precision", "f1", "type_accuracy"}
