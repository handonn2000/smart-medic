"""Heuristic tách synonym theo dấu phẩy (quyết định D4).

Nguyên tắc: thà bỏ sót còn hơn cắt nhầm — tên bệnh sai làm hỏng cả retrieval,
trong khi bỏ sót một synonym chỉ mất một chút recall.
"""

from __future__ import annotations

import pytest

from smart_medic.kb.normalize.synonyms import split_synonyms, was_split


class TestTachDuoc:
    def test_ca_that_trong_icd10_csv(self):
        got = split_synonyms("U lao não và tủy sống, Áp xe lao não và tủy sống")
        assert got == ["U lao não và tủy sống", "Áp xe lao não và tủy sống"]

    def test_ba_manh(self):
        got = split_synonyms("Lao ở khớp háng, Lao khớp gối, Lao cột sống")
        assert len(got) == 3
        assert "Lao cột sống" in got

    def test_was_split_bao_dung(self):
        assert was_split("Lao ở khớp háng, Lao khớp gối")


class TestKhongTach:
    @pytest.mark.parametrize(
        "name",
        [
            "Bệnh trào ngược dạ dày - thực quản, không đặc hiệu",
            "Sự có mặt của dụng cụ cấy ghép tim, không đặc hiệu",
            "Viêm phổi, chưa xác định",
            "Lao phổi, có xác nhận vi khuẩn",
            "Bệnh sốt virus, kèm biến chứng",
        ],
    )
    def test_manh_bo_nghia_khong_duoc_tach(self, name):
        assert split_synonyms(name) == [name]

    def test_khong_co_dau_phay(self):
        assert split_synonyms("Thiếu men G6PD") == ["Thiếu men G6PD"]

    def test_manh_qua_ngan_thi_khong_tach(self):
        assert split_synonyms("Lao phổi, ho") == ["Lao phổi, ho"]

    def test_was_split_bao_dung_khi_khong_tach(self):
        assert not was_split("Bệnh trào ngược dạ dày, không đặc hiệu")


class TestBienTheDauVao:
    def test_gop_khoang_trang(self):
        assert split_synonyms("  Lao khớp gối  ,  Lao cột sống  ") == [
            "Lao khớp gối",
            "Lao cột sống",
        ]

    def test_chuoi_rong(self):
        assert split_synonyms("") == [""]
