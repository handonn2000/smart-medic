"""Xếp hạng lại ứng viên thuốc — độ phủ token NHÂN với TTY prior."""

from __future__ import annotations

import pytest

from smart_medic.kb.query.rerank import (
    DEFAULT_PRIOR,
    ICD_NORMAL_PRIOR,
    ICD_RANGE_PRIOR,
    TTY_PRIOR_BARE,
    TTY_PRIOR_DOSED,
    canonical_term,
    coverage_f1,
    has_strength,
    is_range_code,
    score_candidate,
    tokens,
)


class TestCoverageF1:
    def test_khop_hoan_toan(self):
        assert coverage_f1({"aspirin", "81", "mg"}, {"aspirin", "81", "mg"}) == 1.0

    def test_khong_chung_token(self):
        assert coverage_f1({"aspirin"}, {"ibuprofen"}) == 0.0

    def test_rong_thi_khong_no(self):
        assert coverage_f1(set(), {"a"}) == 0.0
        assert coverage_f1({"a"}, set()) == 0.0

    def test_phat_token_thua(self):
        """★ Vế precision — đây là thứ phân biệt `Oral Tablet` với
        `Delayed Release Oral Tablet` khi mention không nói gì về DR."""
        q = tokens("aspirin 81 mg")
        plain = coverage_f1(q, tokens("aspirin 81 mg Oral Tablet"))
        delayed = coverage_f1(q, tokens("aspirin 81 mg Delayed Release Oral Tablet"))
        assert plain > delayed


class TestHasStrength:
    @pytest.mark.parametrize(
        "text",
        ["aspirin 81 mg po daily", "senna 8.6 mg", "insulin 100 unt/ml", "cream 2 %"],
    )
    def test_co_ham_luong(self, text):
        assert has_strength(text)

    @pytest.mark.parametrize("text", ["docusate sodium", "omeprazole", "heparin"])
    def test_khong_co_ham_luong(self, text):
        assert not has_strength(text)

    def test_ml_khong_phai_ham_luong(self):
        """★ `ml` là THỂ TÍCH LIỀU, không phải lượng hoạt chất.

        Gold của BTC cho `nystatin oral suspension 5 ml po qid:prn` là `7597`
        — tức hoạt chất — đúng vì mention không nói hoạt chất bao nhiêu.
        """
        assert not has_strength("nystatin oral suspension 5 ml po qid:prn")


class TestPriorPhuThuocMention:
    """Cùng một hoạt chất, hai mention, hai tầng đáp án khác nhau.

    "docusate sodium"               → 71722   (PIN, hoạt chất)
    "docusate sodium 100 mg po bid" → 1099279 (SCD, thuốc kê đơn)
    """

    def test_co_ham_luong_thi_scd_thang_in(self):
        assert TTY_PRIOR_DOSED["SCD"] > TTY_PRIOR_DOSED["IN"]

    def test_khong_ham_luong_thi_in_thang_scd(self):
        assert TTY_PRIOR_BARE["IN"] > TTY_PRIOR_BARE["SCD"]

    def test_scdc_luon_bi_dim(self):
        """SCDC khớp chuỗi tốt nhất nhưng không kê được cho bệnh nhân."""
        for table in (TTY_PRIOR_DOSED, TTY_PRIOR_BARE):
            assert table["SCDC"] < table["SCD"]
            assert table["SCDC"] < DEFAULT_PRIOR


class TestScoreCandidate:
    def test_prior_triet_tieu_duoc_f1_hoan_hao(self):
        """★ BÀI HỌC CỐT LÕI: R2 và R3 phải NHÂN, không cộng.

        `aspirin 81 mg` khớp F1 = 1,0 với SCDC `aspirin 81 mg`, nhưng thua SCD
        `aspirin 81 mg Oral Tablet` (F1 = 0,75) nhờ prior. Nếu cộng hai điểm thì
        SCDC vẫn thắng — đo được R@1 tụt về 0,000.
        """
        q = tokens("aspirin 81 mg")
        scdc = score_candidate(q, [("aspirin 81 mg", "SCDC")], TTY_PRIOR_DOSED)
        scd = score_candidate(q, [("aspirin 81 mg Oral Tablet", "SCD")], TTY_PRIOR_DOSED)
        assert scd > scdc

    def test_lay_term_tot_nhat_cua_concept(self):
        q = tokens("aspirin 81 mg")
        terms = [("something else", "SCD"), ("aspirin 81 mg Oral Tablet", "SCD")]
        assert score_candidate(q, terms, TTY_PRIOR_DOSED) > 0.5

    def test_khong_co_term_thi_bang_khong(self):
        assert score_candidate({"aspirin"}, [], TTY_PRIOR_DOSED) == 0.0

    def test_tty_la_khoa_theo_TERM_khong_theo_concept(self):
        """Concept có cả SCD lẫn SCDC; term nào khớp thì prior của term đó."""
        q = tokens("aspirin 81 mg")
        mixed = score_candidate(
            q, [("aspirin 81 mg", "SCDC"), ("aspirin 81 mg Oral Tablet", "SCD")], TTY_PRIOR_DOSED
        )
        only_scdc = score_candidate(q, [("aspirin 81 mg", "SCDC")], TTY_PRIOR_DOSED)
        assert mixed > only_scdc


# ── Nhánh CHẨN_ĐOÁN ──────────────────────────────────────────────────────


class TestMaKhoang:
    @pytest.mark.parametrize("code", ["E10-E14", "J09-J18", "D55-D59"])
    def test_nhan_dien_ma_khoang(self, code):
        assert is_range_code(code)

    @pytest.mark.parametrize("code", ["E11", "E11.9", "K21.0", "I10"])
    def test_ma_that_khong_bi_nham(self, code):
        assert not is_range_code(code)

    def test_ma_khoang_bi_dim(self):
        """`E10-E14` là nhóm gom, không bao giờ là đáp án của đề."""
        assert ICD_RANGE_PRIOR < ICD_NORMAL_PRIOR


class TestCanonicalTerm:
    @pytest.mark.parametrize(
        ("src", "want"),
        [
            ("Viêm phổi, không xác định", "Viêm phổi"),
            ("Suy tim, không xác định", "Suy tim"),
            ("Nhiễm trùng đường tiết niệu, vị trí không xác định", "Nhiễm trùng đường tiết niệu"),
        ],
    )
    def test_bo_duoi_dinh_tinh(self, src, want):
        assert canonical_term(src) == want

    def test_khong_dung_toi_ten_thuong(self):
        src = "Bệnh tăng huyết áp vô căn (nguyên phát)"
        assert canonical_term(src) == src

    def test_cho_ma_9_canh_tranh_cong_bang_voi_ma_cha(self):
        """★ Đây là cơ chế duy nhất tạo ra mức tăng ở nhánh ICD.

        Giữ nguyên đuôi thì vế precision của F1 phạt oan mã `.9`: mention
        `"viêm phổi"` phủ 2/5 token của `"Viêm phổi, không xác định"` nhưng
        2/2 token của mã cha `"Viêm phổi"`.
        """
        q = tokens("viêm phổi")
        raw = coverage_f1(q, tokens("Viêm phổi, không xác định"))
        canon = coverage_f1(q, tokens(canonical_term("Viêm phổi, không xác định")))
        assert canon > raw
        assert canon == coverage_f1(q, tokens("Viêm phổi"))


class TestKhongCaiLuatChaCon:
    """★ KHOÁ KẾT QUẢ ÂM — đừng cài lại luật đã đo thấy hoà/có hại.

    Hai cám dỗ đã thử và bị bỏ, xem chú thích trong `rerank.py`:

    1. "ưu tiên mã con .9"  — gold chia 19/16, đổi ca này lấy ca kia
    2. phạt tên chứa "khác" + phạt chương R/Z — trên gold lâm sàng có vẻ tốt
       nhưng kéo probe 84 ca từ R@1 0,940 xuống 0,833, tức DƯỚI cả baseline

    Test này canh để chúng không lặng lẽ quay lại.
    """

    def test_khong_co_prior_theo_do_sau_ma(self):
        import smart_medic.kb.query.rerank as rr

        assert not hasattr(rr, "CHAPTER_PENALTY"), "phạt chương đã bị bỏ vì overfit"
        assert not hasattr(rr, "RESIDUAL_OTHER"), 'phạt "khác" đã bị bỏ vì overfit'

    def test_khac_khong_bi_boc_nhu_bo_ngu_ton_du(self):
        """`"khác"` KHÔNG được coi là bổ ngữ tồn dư để bóc.

        Từng thử bóc/phạt nó và đo thấy có hại. Giữ nguyên trong tên nghĩa là
        `"Tăng lipid máu khác"` mang thêm một token thừa, và vế precision của F1
        tự lo phần còn lại — không cần luật riêng.
        """
        assert canonical_term("Tăng lipid máu khác") == "Tăng lipid máu khác"
        q = tokens("tăng lipid máu")
        assert coverage_f1(q, tokens("Tăng lipid máu khác")) < coverage_f1(
            q, tokens("Tăng lipid máu")
        )
