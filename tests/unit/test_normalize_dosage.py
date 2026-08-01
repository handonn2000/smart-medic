"""Hàm lượng & đơn vị — gồm bẫy dấu phẩy thập phân kiểu Việt."""

from __future__ import annotations

import pytest

from smart_medic.kb.normalize.dosage import normalize_dosage, normalize_units, vn_decimal_to_dot


class TestDauPhayThapPhan:
    def test_so_thap_phan_kieu_viet(self):
        """Kết quả xét nghiệm trong đề ghi `WBC: 14,43`."""
        assert vn_decimal_to_dot("WBC: 14,43") == "WBC: 14.43"

    @pytest.mark.parametrize(
        ("src", "want"),
        [("76,4", "76.4"), ("12,8", "12.8"), ("0,5", "0.5")],
    )
    def test_cac_gia_tri_that_trong_de(self, src, want):
        assert vn_decimal_to_dot(src) == want

    def test_khong_dung_den_phan_tach_hang_nghin(self):
        """`1,000` ở nguồn tiếng Anh là một nghìn — đổi là SAI."""
        assert vn_decimal_to_dot("1,000 mg") == "1,000 mg"
        assert vn_decimal_to_dot("12,345") == "12,345"

    def test_khong_dung_den_dau_phay_ngan_cach_tu(self):
        assert vn_decimal_to_dot("ho, sốt, đau bụng") == "ho, sốt, đau bụng"


class TestNormalizeUnits:
    def test_chen_khoang_trang_va_ha_chu_thuong(self):
        assert normalize_units("Aspirin 81MG Oral Tablet") == "Aspirin 81 mg Oral Tablet"

    def test_don_vi_da_dung_thi_giu(self):
        assert normalize_units("aspirin 81 mg Oral Tablet") == "aspirin 81 mg Oral Tablet"

    def test_gop_khoang_trang_thua(self):
        assert normalize_units("Capsaicin   0.38   MG") == "Capsaicin 0.38 mg"


class TestNormalizeDosage:
    def test_nguon_tieng_anh_khong_doi_dau_phay(self):
        assert normalize_dosage("aspirin 1,000 mg", lang="en") == "aspirin 1,000 mg"

    def test_nguon_tieng_viet_doi_dau_phay(self):
        assert normalize_dosage("bạch cầu 14,43", lang="vi") == "bạch cầu 14.43"

    def test_mac_dinh_la_tieng_anh(self):
        """RxNorm là nguồn lớn nhất dùng hàm này nên mặc định phải là 'en'."""
        assert normalize_dosage("1,000 mg") == "1,000 mg"
