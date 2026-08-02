"""Bộ dựng tài liệu — offset ghi LÚC CHÈN, đúng cả khi nhiễu đổi độ dài chuỗi."""

from __future__ import annotations

import unicodedata

import pytest

from smart_medic.synth.schema import (
    TYPE_DIAGNOSIS,
    TYPE_DRUG,
    TYPE_RESULT,
    TYPE_SYMPTOM,
    TYPE_TEST,
    Concept,
    DocBuilder,
)


class TestOffsetTheoKienTao:
    def test_span_cat_lai_dung_chinh_no(self):
        b = DocBuilder()
        b.plain("Chẩn đoán: ")
        b.span("viêm phổi", TYPE_DIAGNOSIS, codes=("J18.9",))
        b.plain("\nTiền sử: ")
        b.span("hen suyễn", TYPE_DIAGNOSIS, codes=("J45",))
        doc = b.build("1")
        for s in doc.spans:
            assert doc.text[s.start : s.end] == s.text

    def test_NFD_doi_do_dai_ma_offset_van_dung(self):
        """★ Bất biến ĐẮT NHẤT của cả module.

        NFD tách `"ề"` thành hai code point. Áp nó SAU khi đã ghi offset thì mọi
        span phía sau lệch — im lặng, đúng lớp bug mà kiến trúc này diệt.
        """
        b = DocBuilder()
        b.plain("Sản khoa: ")
        b.span("tiền sản giật", TYPE_DIAGNOSIS, codes=("O14",))
        b.plain(" và ")
        b.span("phù chân", TYPE_SYMPTOM)
        doc = b.build("1", transform=lambda s: unicodedata.normalize("NFD", s))
        assert unicodedata.normalize("NFC", doc.text) != doc.text, "phải thật sự là NFD"
        for s in doc.spans:
            assert doc.text[s.start : s.end] == s.text

    def test_khong_dung_index_nen_cum_lap_lai_van_dung(self):
        """Cùng một chuỗi xuất hiện 3 lần — `txt.index()` sẽ trả về lần đầu cả 3."""
        b = DocBuilder()
        for _ in range(3):
            b.span("sốt", TYPE_SYMPTOM)
            b.plain(", ")
        doc = b.build("1")
        assert [s.start for s in doc.spans] == [0, 5, 10]
        for s in doc.spans:
            assert doc.text[s.start : s.end] == "sốt"


class TestRangBuocDeBai:
    def test_nhan_khong_duoc_gan_ma(self):
        b = DocBuilder()
        for t in (TYPE_SYMPTOM, TYPE_TEST, TYPE_RESULT):
            with pytest.raises(ValueError, match="candidates"):
                b.span("x", t, codes=("J18.9",))

    def test_nhan_khong_duoc_gan_assertion(self):
        b = DocBuilder()
        for t in (TYPE_TEST, TYPE_RESULT):
            with pytest.raises(ValueError, match="assertions"):
                b.span("x", t, assertions=("isNegated",))

    def test_nhan_la_thi_no(self):
        with pytest.raises(ValueError, match="nhãn lạ"):
            DocBuilder().span("x", "BỆNH_VIỆN")

    def test_span_rong_bi_chan(self):
        """★ Bug thật ở `100.txt`: span [507,508] là một dấu cách."""
        for bad in ("", "   ", "\n"):
            with pytest.raises(ValueError, match="rỗng"):
                DocBuilder().span(bad, TYPE_SYMPTOM)

    def test_concept_kiem_ma_ngay_luc_dung(self):
        with pytest.raises(ValueError, match="không được có mã"):
            Concept(TYPE_SYMPTOM, ("sốt",), ("R50.9",))


class TestCumGayNhieu:
    def test_khong_sinh_span_nao(self):
        b = DocBuilder()
        b.span("sốt", TYPE_SYMPTOM)
        b.plain(", ")
        b.distractor("máy thở")
        doc = b.build("1")
        assert [s.text for s in doc.spans] == ["sốt"]
        assert doc.distractors == [(5, 12)]
        ds, de = doc.distractors[0]
        assert doc.text[ds:de] == "máy thở"

    def test_vi_tri_cum_nhieu_dung_ca_khi_NFD(self):
        b = DocBuilder()
        b.distractor("vùng thượng vị")
        doc = b.build("1", transform=lambda s: unicodedata.normalize("NFD", s))
        ds, de = doc.distractors[0]
        assert doc.text[ds:de] == unicodedata.normalize("NFD", "vùng thượng vị")


class TestToDict:
    def test_dung_dinh_dang_de_bai(self):
        b = DocBuilder()
        b.span("amlodipine 10 mg", TYPE_DRUG, codes=("308135",), assertions=("isHistorical",))
        d = b.build("1").spans[0].to_dict()
        assert set(d) == {"text", "type", "candidates", "assertions", "position"}
        assert d["position"] == [0, 16]
