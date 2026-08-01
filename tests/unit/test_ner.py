"""NER từ điển — dựng khoá, khớp dài nhất, luật giá trị xét nghiệm."""

from __future__ import annotations

import pytest

from smart_medic.stages.ner import (
    MIN_TERM_CHARS,
    SHORT_ALLOW,
    STOP_PHRASES,
    TYPE_DIAGNOSIS,
    TYPE_DRUG,
    TYPE_RESULT,
    TYPE_SYMPTOM,
    Gazetteer,
    annotate,
    detect,
    norm_key,
    surface_forms,
    tokens_with_offset,
)


def gaz(**entries) -> Gazetteer:
    return Gazetteer(entries=dict(entries))


class TestTokensWithOffset:
    def test_giu_dung_vi_tri_goc(self):
        text = "Bệnh nhân ho đờm"
        toks = tokens_with_offset(text)
        for word, start, end in toks:
            assert text[start:end] == word

    def test_khong_chuan_hoa_chuoi_nguon(self):
        """★ Offset là thiêng — xem `textio.py`."""
        text = "  ho\r\nsốt "
        for word, start, end in tokens_with_offset(text):
            assert text[start:end] == word


class TestSurfaceForms:
    def test_bo_duoi_dinh_tinh(self):
        assert "tăng lipid máu" in surface_forms("Tăng lipid máu, không xác định")

    def test_bo_tien_to_loai_chung(self):
        """KB có `"Bệnh lý tăng huyết áp"` nhưng bệnh án viết `"tăng huyết áp"`."""
        assert "tăng huyết áp" in surface_forms("Bệnh lý tăng huyết áp")

    def test_khong_sinh_tu_don_khi_boc_tien_to(self):
        """★ Bóc còn một từ thì là bộ phận cơ thể, không phải tên bệnh."""
        assert surface_forms("Bệnh gan") == ["bệnh gan"]
        assert surface_forms("Rối loạn nội tiết") == ["rối loạn nội tiết"]

    def test_ten_thuong_khong_bi_dung_toi(self):
        assert surface_forms("Viêm phổi") == ["viêm phổi"]

    def test_khong_trung_lap(self):
        assert len(surface_forms("Viêm phổi")) == len(set(surface_forms("Viêm phổi")))


class TestDungKhoaTuDien:
    def test_chan_term_qua_ngan(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "K", TYPE_DIAGNOSIS)
        assert "k" not in e, f"term < {MIN_TERM_CHARS} ký tự phải bị chặn"

    def test_trieu_chung_ngan_van_duoc_giu(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "ho", TYPE_SYMPTOM)
        assert e.get("ho") == TYPE_SYMPTOM

    def test_dau_khong_nam_trong_short_allow(self):
        """`"đau"` một mình quá chung — đo được 7 entity thừa."""
        assert "đau" not in SHORT_ALLOW

    def test_chan_tu_doi_thuong(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        for w in ("nhẹ", "trung bình", "thuốc"):
            _add(e, w, TYPE_DIAGNOSIS)
        assert not e
        assert {"nhẹ", "trung bình", "thuốc"} <= STOP_PHRASES

    def test_chan_doan_thang_khi_trung_khoa(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "viêm phổi", TYPE_DIAGNOSIS)
        _add(e, "viêm phổi", TYPE_DRUG)
        assert e["viêm phổi"] == TYPE_DIAGNOSIS


class TestDetect:
    def test_khop_don_gian(self):
        ents = detect("bệnh nhân bị viêm phổi", gaz(**{"viêm phổi": TYPE_DIAGNOSIS}))
        assert len(ents) == 1
        assert (ents[0].text, ents[0].type) == ("viêm phổi", TYPE_DIAGNOSIS)

    def test_uu_tien_khop_dai_nhat(self):
        """`"đái tháo đường type 2"` phải thắng `"đái tháo đường"`."""
        g = gaz(**{"đái tháo đường": TYPE_DIAGNOSIS, "đái tháo đường type 2": TYPE_DIAGNOSIS})
        ents = detect("chẩn đoán đái tháo đường type 2 đã lâu", g)
        assert [e.text for e in ents] == ["đái tháo đường type 2"]

    def test_khong_chong_lan(self):
        g = gaz(**{"đau": TYPE_SYMPTOM, "đau ngực": TYPE_SYMPTOM})
        ents = detect("đau ngực nhiều", g)
        spans = [(e.start, e.end) for e in ents]
        for a, b in zip(spans, spans[1:], strict=False):
            assert a[1] <= b[0]

    def test_offset_tro_dung_vao_van_ban(self):
        text = "tiền sử: viêm phổi nặng"
        ents = detect(text, gaz(**{"viêm phổi": TYPE_DIAGNOSIS}))
        e = ents[0]
        assert text[e.start : e.end] == e.text

    def test_tu_dien_rong_thi_khong_no(self):
        assert detect("bất kỳ văn bản nào", gaz()) == []

    def test_khong_phan_biet_hoa_thuong(self):
        ents = detect("Viêm Phổi", gaz(**{"viêm phổi": TYPE_DIAGNOSIS}))
        assert len(ents) == 1
        assert ents[0].text == "Viêm Phổi", "giữ nguyên văn bản gốc, không hạ chữ"


class TestGiaTriXetNghiem:
    @pytest.mark.parametrize(
        ("text", "want"),
        [("đường huyết: 11.2 mmol/L", "11.2 mmol/L"), ("spo2: 92%", "92%")],
    )
    def test_bat_so_kem_don_vi(self, text, want):
        ents = [e for e in annotate(text, gaz()) if e.type == TYPE_RESULT]
        assert want in [e.text for e in ents]

    def test_bo_qua_so_khong_co_don_vi(self):
        """Số thứ tự mục và tuổi không phải kết quả xét nghiệm."""
        ents = [e for e in annotate("1. Bệnh nhân nữ 64 tuổi", gaz()) if e.type == TYPE_RESULT]
        assert ents == []

    def test_khong_de_len_entity_da_co(self):
        g = gaz(**{"aspirin": TYPE_DRUG})
        ents = annotate("aspirin 81 mg", g)
        spans = sorted((e.start, e.end) for e in ents)
        for a, b in zip(spans, spans[1:], strict=False):
            assert a[1] <= b[0]


class TestNormKey:
    def test_hop_nhat_khoang_trang_va_ha_chu(self):
        assert norm_key(["Viêm", "PHỔI"]) == "viêm phổi"
