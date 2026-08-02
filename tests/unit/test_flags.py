"""Cờ bật/tắt thành phần — cơ chế thay cho "dừng phase" (§4.0)."""

from __future__ import annotations

import pytest

from smart_medic.stages.flags import DEFAULTS, _coerce_bool, flag, load_flags, weight


class TestEpKieu:
    """★ Hỏng-im-lặng: Python coi mọi chuỗi khác rỗng là True, kể cả `"false"`."""

    @pytest.mark.parametrize("raw", ["false", "FALSE", "no", "off", "0", ""])
    def test_chuoi_phu_dinh_ra_false(self, raw):
        assert _coerce_bool(raw, "x") is False

    @pytest.mark.parametrize("raw", ["true", "TRUE", "yes", "on", "1"])
    def test_chuoi_khang_dinh_ra_true(self, raw):
        assert _coerce_bool(raw, "x") is True

    def test_bool_that_di_thang(self):
        assert _coerce_bool(True, "x") is True

    def test_kieu_la_thi_no_chu_khong_doan(self):
        with pytest.raises(ValueError, match="phải là bool"):
            _coerce_bool(["true"], "labtest_extended")


class TestFlag:
    def test_override_thang_moi_thu(self, monkeypatch):
        monkeypatch.setenv("SMK_LABTEST_EXTENDED", "false")
        assert flag("labtest_extended", override=True) is True

    def test_bien_moi_truong_thang_file(self, monkeypatch):
        monkeypatch.setenv("SMK_LABTEST_EXTENDED", "false")
        assert flag("labtest_extended") is False
        monkeypatch.setenv("SMK_LABTEST_EXTENDED", "true")
        assert flag("labtest_extended") is True

    def test_co_la_khong_biet_thi_false(self):
        assert flag("khong_ton_tai") is False


class TestLoadFlags:
    def test_thieu_file_thi_ve_mac_dinh(self, tmp_path):
        assert load_flags(tmp_path / "khong-co.yaml") == DEFAULTS

    def test_mac_dinh_bang_hanh_vi_truoc_phase_1(self):
        """Xoá file cấu hình đi thì repo vẫn chạy, và chạy như trước Phase 1."""
        assert DEFAULTS["labtest_extended"] is False
        assert DEFAULTS["tagger"] is False
        assert DEFAULTS["arbiter_model_weight"] == 0.0

    def test_file_thuc_te_bat_labtest(self):
        """Cổng định tuyến Phase 1 đã pass nên cờ phải đang BẬT."""
        assert load_flags()["labtest_extended"] is True

    def test_weight_doc_ra_so(self):
        assert isinstance(weight("arbiter_model_weight"), float)
