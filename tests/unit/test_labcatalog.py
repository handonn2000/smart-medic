"""Danh mục xét nghiệm đóng băng — thứ duy nhất phân biệt được hai khối
giống hệt nhau về cú pháp (xem docstring `labcatalog`)."""

from __future__ import annotations

import pytest

from smart_medic.stages.labcatalog import abbr_has_context, load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class TestNapDanhMuc:
    def test_co_du_ba_thanh_phan(self, cat):
        assert len(cat.names) > 100
        assert len(cat.abbrs) > 50
        assert cat.prose_separators and cat.result_stop_phrases

    def test_co_cache(self, cat):
        assert load_catalog() is cat


class TestLeadingTestName:
    """Trả PHẦN KHỚP, không phải cả chuỗi — gold chỉ khoanh `"Troponin I/T"`."""

    @pytest.mark.parametrize(
        "raw,want",
        [
            ("Troponin I/T ↑ (chẩn đoán nhồi máu)", "Troponin I/T"),
            ("CK-MB ↑", "CK-MB"),
            ("HBsAg (+)", "HBsAg"),
            ("Điện tâm đồ (ECG)", "Điện tâm đồ"),
        ],
    )
    def test_bat_dung_phan_dau(self, cat, raw, want):
        assert cat.leading_test_name(raw) == want

    def test_dai_truoc_ngan_sau(self, cat):
        """★ Không sắp theo độ dài thì `Troponin` nuốt mất `Troponin I/T`."""
        assert cat.leading_test_name("Troponin I/T") == "Troponin I/T"

    @pytest.mark.parametrize(
        "raw", ["ST chênh lên / chênh xuống", "Đánh giá chức năng thất trái", "đau bụng"]
    )
    def test_khong_phai_xet_nghiem_thi_None(self, cat, raw):
        assert cat.leading_test_name(raw) is None


class TestResultVocab:
    @pytest.mark.parametrize(
        "raw", ["dương tính", "(+)", "(-)", "chưa phát hiện bất thường", "nguyên vẹn", "đang chờ"]
    )
    def test_bat_duoc_ket_qua_khong_phai_so(self, cat, raw):
        m = cat.result_re.match(raw)
        assert m and m.group(0) == raw

    def test_dau_cum_xu_huong_chay_toi_ranh_gioi(self, cat):
        m = cat.result_re.match("tăng men gan nhẹ")
        assert m and m.group(0) == "tăng men gan nhẹ"

    def test_so_tran_khong_phai_tu_vung(self, cat):
        assert cat.result_re.match("1.0") is None


class TestAbbrContext:
    """`N`, `K`, `HA` khớp trần thì bắn khắp nơi — phải có dấu hiệu đi kèm."""

    @pytest.mark.parametrize("tail", [": dương tính", " (+)", " 5,38", ":89"])
    def test_dau_hieu_khong_the_nham(self, tail):
        assert abbr_has_context(tail, 0)

    @pytest.mark.parametrize("tail", [" không sốt", " bệnh nặng", " và ho"])
    def test_van_xuoi_thuong_thi_khong(self, tail):
        assert not abbr_has_context(tail, 0)
