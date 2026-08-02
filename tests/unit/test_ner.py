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


class TestDauCumTrieuChung:
    """★ Đầu cụm chỉ triệu chứng thắng luật chương ICD.

    Chương R phủ phần lớn triệu chứng nhưng không phải tất cả: `"đau khớp"` mã
    ở `M25.5` (chương M), `"ngứa"` ở `L29` (chương L). Về mã thì đúng chỗ; về
    NHÃN của đề bài thì chúng là triệu chứng.
    """

    def test_nhan_dien_dau_cum(self):
        from smart_medic.stages.ner import head_is_symptom

        for phrase in ("đau khớp", "sưng đau khớp bàn tay", "ngứa", "khó thở", "co giật toàn thể"):
            assert head_is_symptom(phrase), phrase

    def test_ten_benh_khong_bi_nham(self):
        from smart_medic.stages.ner import head_is_symptom

        for phrase in ("viêm phổi", "đái tháo đường", "tăng huyết áp", "suy tim"):
            assert not head_is_symptom(phrase), phrase

    def test_ghi_de_nhan_chuong(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "đau khớp", TYPE_DIAGNOSIS)  # mã ở chương M
        assert e["đau khớp"] == TYPE_SYMPTOM

    def test_khong_dung_toi_ten_benh(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "viêm phổi", TYPE_DIAGNOSIS)
        assert e["viêm phổi"] == TYPE_DIAGNOSIS


class TestChanBoPhanCoThe:
    """Term nguồn của ICD bị CỤT sinh ra mục một từ là bộ phận cơ thể.

    `T35.3` có term tiếng Việt đúng là `"bụng"`, `J68` là `"khí"`. Để nguyên thì
    chúng khớp bừa VÀ cướp span của mention dài hơn.
    """

    def test_bo_phan_co_the_bi_chan(self):
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        for w in ("bụng", "khí", "thận", "khớp", "tim mạch", "nội tiết"):
            _add(e, w, TYPE_DIAGNOSIS)
        assert not e

    def test_khong_cuop_span_cua_trieu_chung(self):
        """`"đau bụng"` không được bị khớp thành `"bụng"`."""
        from smart_medic.stages.ner import _add

        e: dict[str, str] = {}
        _add(e, "bụng", TYPE_DIAGNOSIS)
        ents = detect("bệnh nhân đau bụng nhiều", Gazetteer(entries=e))
        assert ents == []


class TestChanManhCatVun:
    """★ Heuristic tách synonym theo dấu phẩy (D4) sinh ra mảnh vô nghĩa.

    Đo trên `data/test/`: chúng khớp văn xuôi thường xuyên và bịa ra chẩn đoán.
    """

    def test_nhan_dien_manh_vun(self):
        from smart_medic.stages.ner import is_fragment

        cases = [
            ("thiếu", "Dị tật thiếu, teo và/hoặc hẹp ống tai ngoài"),
            ("sắc", "Tấn công bằng vật sắc nhọn"),
            ("tại bệnh viện", "Trẻ sinh ra sống, một con, tại bệnh viện"),
            ("hiện tại", "Rách sụn chêm, vết rách hiện tại"),
        ]
        for term, pref in cases:
            assert is_fragment(term, pref, "authoritative"), term

    def test_ten_day_du_khong_bi_nham(self):
        from smart_medic.stages.ner import is_fragment

        assert not is_fragment("Viêm phổi", "Viêm phổi", "authoritative")
        assert not is_fragment(
            "Bệnh lý tăng huyết áp", "Bệnh tăng huyết áp vô căn", "authoritative"
        )

    def test_khong_ap_cho_tu_dong_nghia_curate(self):
        """★ E5 curate tay cũng là chuỗi con, nhưng do người chọn nên đáng tin."""
        from smart_medic.stages.ner import is_fragment

        assert not is_fragment(
            "tăng huyết áp vô căn", "Bệnh tăng huyết áp vô căn (nguyên phát)", "generated"
        )

    def test_thieu_pref_vi_thi_giu(self):
        from smart_medic.stages.ner import is_fragment

        assert not is_fragment("abc", None, "authoritative")


class TestChanNguyenNhanNgoaiSinh:
    def test_chuong_V_Y_bi_loai(self):
        """Chương XX là mã BỔ SUNG mô tả hoàn cảnh, không phải chẩn đoán.

        Không mã V–Y nào xuất hiện trong bất kỳ bộ gold nào của dự án.
        """
        from smart_medic.stages.ner import _CHAPTER_EXTERNAL

        for code in ("X99", "Y56.3", "V01", "W54"):
            assert _CHAPTER_EXTERNAL.match(code), code

    def test_ma_benh_that_khong_bi_loai(self):
        from smart_medic.stages.ner import _CHAPTER_EXTERNAL

        for code in ("I10", "E11.9", "J18.9", "Z38.0", "K21"):
            assert not _CHAPTER_EXTERNAL.match(code), code


class TestUnicodeToHop:
    """★ Lớp bug NGHIÊM TRỌNG: `[^\\W_]+` làm VỠ VỤN văn bản NFD.

    Ký tự tổ hợp thuộc category Mn nên không khớp `\\w`. Trên NFD, `"tiền"` bị
    cắt thành `["tie", "n"]` — mọi mention trong file NFD trở nên vô hình.

    Đo được: 20/100 file `data/test/` không ở dạng NFC, và `100.txt` còn TRỘN
    NFC với NFD ngay bên trong một cụm từ.
    """

    def test_token_khong_vo_tren_nfd(self):
        import unicodedata

        from smart_medic.stages.ner import _TOKEN

        nfd = unicodedata.normalize("NFD", "tiền sản giật")
        assert _TOKEN.findall(nfd) == [nfd.split()[0], nfd.split()[1], nfd.split()[2]]

    def test_khoa_tu_dien_duoc_nfc_hoa(self):
        """Khoá là BẢN SAO để so khớp; chuỗi tính offset không bị đụng."""
        import unicodedata

        nfd = unicodedata.normalize("NFD", "tiền sản giật")
        from smart_medic.stages.ner import _TOKEN

        assert norm_key(_TOKEN.findall(nfd)) == "tiền sản giật"

    def test_tim_duoc_mention_nfd(self):
        import unicodedata

        g = gaz(**{"tiền sản giật": TYPE_DIAGNOSIS})
        text = "nguy cơ " + unicodedata.normalize("NFD", "tiền sản giật") + " cao"
        ents = detect(text, g)
        assert len(ents) == 1
        assert text[ents[0].start : ents[0].end] == ents[0].text, "offset phải trỏ vào chuỗi GỐC"

    def test_offset_van_tinh_tren_chuoi_goc(self):
        """NFD dài hơn NFC — offset phải theo chuỗi thật, không theo bản chuẩn hoá."""
        import unicodedata

        nfd = unicodedata.normalize("NFD", "tiền sản giật")
        assert len(nfd) > len("tiền sản giật")
        for word, start, end in tokens_with_offset(nfd):
            assert nfd[start:end] == word


class TestThuocBiChe:
    """PRD §7.1 — token bị che là entity THUỐC riêng, `candidates` rỗng."""

    def test_nhan_dien_token_che(self):
        from smart_medic.stages.ner import detect_masked_drugs

        ents = detect_masked_drugs("Thuốc giảm đau chứa ******* hoặc **********", [])
        assert [e.type for e in ents] == [TYPE_DRUG, TYPE_DRUG]
        assert all(e.candidates == () for e in ents)

    def test_nuot_duoi_chu_cai(self):
        from smart_medic.stages.ner import detect_masked_drugs

        ents = detect_masked_drugs("sử dụng 2,5g ********************e có bao phim", [])
        assert ents[0].text.endswith("e")

    def test_khong_de_len_entity_da_co(self):
        from smart_medic.stages.ner import detect_masked_drugs
        from smart_medic.stages.scoring import Entity

        taken = [Entity("*******", TYPE_DRUG, 0, 7)]
        assert detect_masked_drugs("*******", taken) == []

    def test_khong_doan_bua_ma(self):
        """PRD §7.1: không suy được thì để rỗng — Jaccard phạt đoán sai."""
        from smart_medic.stages.ner import detect_masked_drugs

        for e in detect_masked_drugs("kem ****************** hai lần", []):
            assert e.candidates == ()
