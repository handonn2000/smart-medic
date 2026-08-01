"""Mã ICD — dagger/asterisk, định dạng, phân cấp, tham chiếu chéo."""

from __future__ import annotations

import pytest

from smart_medic.kb.normalize.codes import (
    is_disease_code,
    is_range_code,
    parent_code,
    split_crossref,
    strip_marker,
)


class TestStripMarker:
    @pytest.mark.parametrize(
        ("src", "code", "flag"),
        [
            ("A06.4†", "A06.4", "dagger"),
            ("K77.0*", "K77.0", "asterisk"),
            ("A17†", "A17", "dagger"),
            ("K21.0", "K21.0", None),
            ("  D55.0  ", "D55.0", None),
        ],
    )
    def test_tach_ky_hieu(self, src, code, flag):
        assert strip_marker(src) == (code, flag)


class TestIsDiseaseCode:
    @pytest.mark.parametrize("code", ["A00", "K21", "K21.0", "D55.0", "A06.81", "U83.1"])
    def test_ma_hop_le(self, code):
        assert is_disease_code(code)

    @pytest.mark.parametrize(
        "code", ["A00-B99", "K2100", "a00", "A0", "A000.0", "", "A06.4†", "K21."]
    )
    def test_ma_khong_hop_le(self, code):
        assert not is_disease_code(code)

    def test_ma_mo_rong_5_ky_tu_cua_byt(self):
        """BYT mở rộng WHO thêm một cấp: A06.81, A17.83 — phải chấp nhận."""
        for c in ["A06.81", "A17.83", "A18.02"]:
            assert is_disease_code(c)


class TestIsRangeCode:
    @pytest.mark.parametrize("code", ["A00-B99", "A92-A99", "U82-U85"])
    def test_ma_khoang(self, code):
        assert is_range_code(code)

    @pytest.mark.parametrize("code", ["A00", "K21.0", "A00-B9"])
    def test_khong_phai_ma_khoang(self, code):
        assert not is_range_code(code)


class TestParentCode:
    @pytest.mark.parametrize(
        ("child", "parent"),
        [
            ("A17.83", "A17.8"),
            ("A17.8", "A17"),
            ("A17", None),
            ("K21.0", "K21"),
            ("K21", None),
        ],
    )
    def test_leo_mot_bac(self, child, parent):
        assert parent_code(child) == parent

    def test_leo_toi_goc(self):
        c, chain = "A06.81", []
        while (c := parent_code(c)) is not None:
            chain.append(c)
        assert chain == ["A06.8", "A06"]


class TestSplitCrossref:
    def test_tach_tham_chieu_asterisk(self):
        assert split_crossref("Amoebic liver abscess (K77.0*)") == (
            "Amoebic liver abscess",
            ["K77.0"],
        )

    def test_ten_tieng_viet(self):
        name, refs = split_crossref("Áp xe phổi do amíp (J99.8*)")
        assert name == "Áp xe phổi do amíp"
        assert refs == ["J99.8"]

    def test_khong_co_tham_chieu_thi_giu_nguyen(self):
        assert split_crossref("Bệnh sốt do bọ ve Colorado") == (
            "Bệnh sốt do bọ ve Colorado",
            [],
        )

    def test_khong_an_nham_ngoac_thuong(self):
        """Ngoặc không có dấu `*` là phần của tên, không phải tham chiếu."""
        name, refs = split_crossref("Thiếu men glucose-6-phosphate [G6PD] (bẩm sinh)")
        assert refs == []
        assert "(bẩm sinh)" in name

    def test_nhieu_tham_chieu(self):
        name, refs = split_crossref("Lao (G05.0*) và biến chứng (G63.0*)")
        assert refs == ["G05.0", "G63.0"]
        assert "*" not in name
