"""Chuẩn hoá chuỗi — gồm hai bẫy đã được cảnh báo trong kế hoạch."""

from __future__ import annotations

import unicodedata

import pytest

from smart_medic.kb.normalize.text import (
    fix_hyphen_wrap,
    normalize_pair,
    normalize_term,
    to_ascii,
    to_nfc,
)


class TestNFC:
    def test_dang_to_hop_thanh_dung_san(self):
        nfd = unicodedata.normalize("NFD", "Thiếu máu")
        assert nfd != "Thiếu máu"  # tiền đề: hai dạng khác nhau về byte
        assert to_nfc(nfd) == "Thiếu máu"

    def test_idempotent(self):
        s = to_nfc("Bệnh trào ngược dạ dày")
        assert to_nfc(s) == s

    def test_do_dai_on_dinh_sau_nfc(self):
        """Offset ký tự phải tính trên chuỗi đã NFC (PRD §8)."""
        assert len(to_nfc(unicodedata.normalize("NFD", "vàng da"))) == len("vàng da")


class TestNormalizeTerm:
    def test_ha_chu_thuong_va_gop_khoang_trang(self):
        assert normalize_term("  Bệnh   TRÀO   ngược  ") == "bệnh trào ngược"

    def test_go_dau_cau_hai_dau(self):
        assert normalize_term("- Sốt Pappataci.") == "sốt pappataci"

    def test_giu_dau_ngoac_vuong_trong_long_chuoi(self):
        got = normalize_term("Thiếu men glucose-6-phosphate dehydrogenase [G6PD]")
        assert "[g6pd]" in got

    def test_giu_dau_tieng_viet(self):
        assert normalize_term("Vàng da") == "vàng da"


class TestToAscii:
    def test_bay_chu_d_gach_ngang(self):
        """`đ` không phải ký tự tổ hợp — NFD không tách được.

        Bỏ bước map tường minh thì "đau đầu" thành "đau đâu".
        """
        assert to_ascii("đau đầu") == "dau dau"

    def test_d_hoa(self):
        assert to_ascii("Đau Đầu") == "Dau Dau"

    @pytest.mark.parametrize(
        ("src", "want"),
        [
            ("vàng da vàng mắt", "vang da vang mat"),
            ("thiếu máu tan huyết", "thieu mau tan huyet"),
            ("trào ngược dạ dày – thực quản", "trao nguoc da day – thuc quan"),
            ("tiền sản giật", "tien san giat"),
            ("ợ hơi", "o hoi"),
            ("ho đờm xanh", "ho dom xanh"),
        ],
    )
    def test_bo_dau_tieng_viet(self, src, want):
        assert to_ascii(src) == want

    def test_khong_dung_den_chu_khong_dau(self):
        assert to_ascii("aspirin 81 mg") == "aspirin 81 mg"

    def test_khong_lam_mat_ky_tu(self):
        """Bỏ dấu không được nuốt chữ — độ dài phải giữ nguyên."""
        s = "Bệnh nhân bị vàng da, đau thượng vị"
        assert len(to_ascii(s)) == len(s)


class TestNormalizePair:
    def test_tra_ve_dung_hai_cot(self):
        norm, ascii_ = normalize_pair("  Thiếu men G6PD  ")
        assert norm == "thiếu men g6pd"
        assert ascii_ == "thieu men g6pd"

    def test_ascii_luon_la_ban_bo_dau_cua_norm(self):
        for s in ["Vàng da sơ sinh", "Đái tháo đường", "suy thận cấp"]:
            norm, ascii_ = normalize_pair(s)
            assert ascii_ == to_ascii(norm)


class TestFixHyphenWrap:
    """PDF ngắt dòng giữa từ ngay sau dấu gạch nối."""

    def test_noi_lai_tu_bi_ngat(self):
        assert (
            fix_hyphen_wrap("Anaemia due to glucose-6- phosphate dehydrogenase")
            == "Anaemia due to glucose-6-phosphate dehydrogenase"
        )

    def test_khong_dung_den_gach_noi_dung_nghia(self):
        """Tiếng Việt dùng ` - ` có khoảng trắng hai bên — phải giữ nguyên."""
        s = "Bệnh trào ngược dạ dày - thực quản"
        assert fix_hyphen_wrap(s) == s

    def test_gach_noi_khong_khoang_trang_giu_nguyen(self):
        s = "Non-Hodgkin lymphoma"
        assert fix_hyphen_wrap(s) == s

    def test_nhieu_lan_trong_mot_chuoi(self):
        got = fix_hyphen_wrap("alpha-1- antitrypsin và beta-2- microglobulin")
        assert got == "alpha-1-antitrypsin và beta-2-microglobulin"

    def test_khong_doi_khi_khong_co_gi_de_sua(self):
        s = "Thiếu men G6PD"
        assert fix_hyphen_wrap(s) == s
