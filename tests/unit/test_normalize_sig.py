"""Bóc token chỉ dẫn dùng thuốc (sig) khỏi mention."""

from __future__ import annotations

import pytest

from smart_medic.kb.normalize.sig import is_sig_token, strip_sig, strip_sig_if_drug


class TestIsSigToken:
    @pytest.mark.parametrize(
        "token", ["po", "PO", "bid", "q6h", "Q12H", "qhs", "prn", "daily", "iv", "ud"]
    )
    def test_nhan_dien_token_sig(self, token):
        assert is_sig_token(token)

    @pytest.mark.parametrize(
        "token", ["aspirin", "mg", "81", "oral", "tablet", "ml", "succinate", "xl"]
    )
    def test_khong_nham_token_dinh_danh(self, token):
        """Hàm lượng, dạng bào chế, tên hoạt chất KHÔNG được coi là sig."""
        assert not is_sig_token(token)


class TestStripSig:
    @pytest.mark.parametrize(
        ("src", "want"),
        [
            ("aspirin 81 mg po daily", "aspirin 81 mg"),
            ("acetaminophen 325-650 mg po q6h:prn", "acetaminophen 325-650 mg"),
            ("nystatin oral suspension 5 ml po qid:prn", "nystatin oral suspension 5 ml"),
            ("metoprolol succinate xl 50 mg po daily", "metoprolol succinate xl 50 mg"),
            ("clonazepam 1.5 mg po qhs", "clonazepam 1.5 mg"),
            ("senna 8.6 mg po bid:prn", "senna 8.6 mg"),
        ],
    )
    def test_bo_sig_giu_dinh_danh(self, src, want):
        assert strip_sig(src) == want

    def test_khong_co_sig_thi_giu_nguyen(self):
        assert strip_sig("Thiếu men G6PD") == "Thiếu men G6PD"

    def test_chi_toan_sig_thi_rong(self):
        assert strip_sig("po bid prn") == ""

    def test_ham_thuan_khong_doi_dau_vao(self):
        src = "aspirin 81 mg po daily"
        strip_sig(src)
        assert src == "aspirin 81 mg po daily"


class TestChiApDungChoThuoc:
    """★ Cố ý KHÔNG áp cho ICD: `os`/`od`/`pr` có thể trùng âm tiết tiếng Việt."""

    def test_icd_khong_bi_dung_toi(self):
        assert strip_sig_if_drug("viêm phổi", "icd10") == "viêm phổi"

    def test_vocab_none_khong_bi_dung_toi(self):
        assert strip_sig_if_drug("aspirin 81 mg po daily", None) == "aspirin 81 mg po daily"

    def test_rxnorm_thi_boc(self):
        assert strip_sig_if_drug("aspirin 81 mg po daily", "rxnorm") == "aspirin 81 mg"

    def test_boc_het_thi_tra_lai_nguyen_van(self):
        """Thà truy vấn nhiễu còn hơn truy vấn rỗng."""
        assert strip_sig_if_drug("po bid", "rxnorm") == "po bid"
