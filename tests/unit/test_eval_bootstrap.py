"""Paired bootstrap — tất định, và ghép cặp đúng chỗ.

Cổng §5 quy tắc 8 dựa hết vào module này, nên nó phải sai to chứ không được sai
âm thầm: một CI trông đẹp mà ghép lệch file thì không ai phát hiện bằng mắt.
"""

from __future__ import annotations

import pytest

from smart_medic.eval.bootstrap import (
    B_DEFAULT,
    SEED,
    _percentile,
    ci_mean,
    ci_paired_delta,
)


class TestTatDinh:
    def test_cung_seed_cho_cung_ket_qua(self):
        vals = [0.1, 0.5, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6]
        a = ci_mean(vals, b=500)
        b = ci_mean(vals, b=500)
        assert (a.lo, a.hi, a.point) == (b.lo, b.hi, b.point)

    def test_seed_khac_cho_ket_qua_khac(self):
        """Nếu đổi seed mà số không đổi thì bootstrap không thực sự chạy."""
        vals = [0.1, 0.5, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6]
        assert ci_mean(vals, b=500, seed=1).lo != ci_mean(vals, b=500, seed=2).lo

    def test_mac_dinh_ghim_cung(self):
        assert (SEED, B_DEFAULT) == (20260802, 10_000)


class TestCIMean:
    def test_diem_uoc_luong_la_trung_binh_mau_goc(self):
        vals = [0.2, 0.4, 0.6]
        assert ci_mean(vals, b=100).point == pytest.approx(0.4)

    def test_khoang_bao_diem_uoc_luong(self):
        vals = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        ci = ci_mean(vals, b=2000)
        assert ci.lo <= ci.point <= ci.hi

    def test_moi_gia_tri_bang_nhau_thi_khoang_suy_bien(self):
        ci = ci_mean([0.5] * 9, b=200)
        assert (ci.lo, ci.point, ci.hi) == (0.5, 0.5, 0.5)

    def test_rong(self):
        ci = ci_mean([], b=100)
        assert (ci.lo, ci.point, ci.hi) == (0.0, 0.0, 0.0)


class TestPairedDelta:
    def test_hai_dang_giong_het_nhau_cho_delta_0_tuyet_doi(self):
        """★ Đây là phép thử quan trọng nhất của tính PAIRED.

        Hai hệ giống hệt nhau thì Δ phải bằng 0 ở **mọi** lần lấy mẫu, nên khoảng
        suy biến về [0, 0]. Nếu lấy mẫu độc lập cho hai vế, khoảng sẽ rộng ra —
        và cổng "CI phải loại trừ 0" sẽ mất hết ý nghĩa.
        """
        vals = [0.1, 0.9, 0.3, 0.7, 0.5]
        ci = ci_paired_delta(vals, list(vals), b=500)
        assert (ci.lo, ci.point, ci.hi) == (0.0, 0.0, 0.0)
        assert not ci.excludes_zero

    def test_cai_thien_deu_thi_khoang_loai_tru_0(self):
        base = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        new = [v + 0.05 for v in base]
        ci = ci_paired_delta(base, new, b=2000)
        assert ci.point == pytest.approx(0.05)
        assert ci.excludes_zero

    def test_tut_deu_cung_loai_tru_0_nhung_am(self):
        base = [0.5] * 9
        new = [0.4] * 9
        ci = ci_paired_delta(base, new, b=500)
        assert ci.point == pytest.approx(-0.1)
        assert ci.excludes_zero and ci.hi < 0

    def test_cai_thien_lom_dom_thi_khong_loai_tru_0(self):
        """Tăng ở vài file, giảm ở vài file → đúng thứ CI phải bắt được."""
        base = [0.5] * 9
        new = [0.9, 0.1, 0.9, 0.1, 0.5, 0.9, 0.1, 0.5, 0.5]
        assert not ci_paired_delta(base, new, b=2000).excludes_zero

    def test_lech_do_dai_thi_no(self):
        with pytest.raises(ValueError, match="khác độ dài"):
            ci_paired_delta([0.1, 0.2], [0.1], b=10)


class TestPercentile:
    def test_bien(self):
        v = [0.0, 1.0]
        assert _percentile(v, 0.0) == 0.0
        assert _percentile(v, 1.0) == 1.0
        assert _percentile(v, 0.5) == pytest.approx(0.5)

    def test_mot_phan_tu(self):
        assert _percentile([0.42], 0.975) == 0.42

    def test_rong(self):
        assert _percentile([], 0.5) == 0.0
