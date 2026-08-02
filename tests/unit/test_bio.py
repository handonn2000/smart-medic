"""BIO: ánh xạ subword↔ký tự và giải mã có ràng buộc. KHÔNG cần torch."""

from __future__ import annotations

import unicodedata

import pytest

from smart_medic.stages.bio import (
    IGNORE_ID,
    LABEL_TO_ID,
    LABELS,
    O_ID,
    is_legal,
    spans_to_tags,
    tags_to_spans,
    transition_mask,
    viterbi,
)
from smart_medic.stages.scoring import Entity


def ent(text, typ, start):
    return Entity(text=text, type=typ, start=start, end=start + len(text))


class TestBangNhan:
    def test_11_nhan_va_O_dung_dau(self):
        assert len(LABELS) == 11
        assert LABELS[0] == "O" and O_ID == 0

    def test_thu_tu_co_dinh(self):
        """★ Checkpoint lưu CHỈ SỐ nhãn. Đổi thứ tự = hỏng âm thầm mọi weights,
        cùng loại bẫy với `concept_id` của KB."""
        assert LABELS[:5] == (
            "O",
            "B-TRIỆU_CHỨNG",
            "I-TRIỆU_CHỨNG",
            "B-TÊN_XÉT_NGHIỆM",
            "I-TÊN_XÉT_NGHIỆM",
        )


class TestRangBuocChuyenTrangThai:
    def test_I_khong_duoc_mo_dau(self):
        assert not is_legal("O", "I-THUỐC")

    def test_I_khong_noi_vao_nhan_khac(self):
        assert not is_legal("B-THUỐC", "I-CHẨN_ĐOÁN")

    def test_I_noi_vao_dung_nhan_thi_duoc(self):
        assert is_legal("B-THUỐC", "I-THUỐC")
        assert is_legal("I-THUỐC", "I-THUỐC")

    def test_B_luon_duoc(self):
        for a in LABELS:
            assert is_legal(a, "B-THUỐC")

    def test_mask_doi_xung_dung_kich_thuoc(self):
        m = transition_mask()
        assert len(m) == len(m[0]) == len(LABELS)


class TestViterbi:
    def _scores(self, seq):
        """Điểm one-hot: nhãn mong muốn 10.0, còn lại 0.0."""
        return [[10.0 if LABELS[i] == want else 0.0 for i in range(len(LABELS))] for want in seq]

    def test_chuoi_hop_le_thi_giu_nguyen(self):
        want = ["O", "B-THUỐC", "I-THUỐC", "O"]
        got = [LABELS[i] for i in viterbi(self._scores(want))]
        assert got == want

    def test_chuoi_BAT_HOP_LE_bi_sua(self):
        """★ Argmax trần cho `O I-THUỐC` — `I-` mở đầu, không hợp lệ."""
        got = [LABELS[i] for i in viterbi(self._scores(["O", "I-THUỐC", "I-THUỐC"]))]
        assert got[0] == "O"
        assert got[1] != "I-THUỐC", "phải bị chặn"
        assert all(is_legal(a, b) for a, b in zip(got, got[1:], strict=False))

    def test_noi_sang_nhan_khac_bi_chan(self):
        got = [LABELS[i] for i in viterbi(self._scores(["B-THUỐC", "I-CHẨN_ĐOÁN"]))]
        assert all(is_legal(a, b) for a, b in zip(got, got[1:], strict=False))

    def test_rong(self):
        assert viterbi([]) == []

    def test_tat_dinh(self):
        s = self._scores(["O", "B-THUỐC", "I-THUỐC"])
        assert viterbi(s) == viterbi(s)


class TestSpansToTags:
    def test_token_dac_biet_bi_bo_qua(self):
        tags = spans_to_tags([(0, 0), (0, 3), (0, 0)], [])
        assert tags[0] == tags[2] == IGNORE_ID
        assert tags[1] == O_ID

    def test_B_roi_I(self):
        offs = [(0, 4), (5, 8), (9, 13)]
        tags = spans_to_tags(offs, [ent("tiền sản giật", "CHẨN_ĐOÁN", 0)])
        assert [LABELS[t] for t in tags] == ["B-CHẨN_ĐOÁN", "I-CHẨN_ĐOÁN", "I-CHẨN_ĐOÁN"]

    def test_token_cat_giua_span_van_duoc_gan(self):
        """Subword hay cắt giữa từ; đòi CHỨA TRỌN thì mất nhãn."""
        tags = spans_to_tags([(0, 2), (2, 5)], [ent("iề", "TRIỆU_CHỨNG", 1)])
        assert all(t != O_ID for t in tags)


class TestTagsToSpans:
    def test_cat_lai_tu_TEXT_chu_khong_ghep_token(self):
        """★ Token của XLM-R BỊ CHUẨN HOÁ: đầu vào NFD cho token `▁tiên`, không
        phải `▁tiền`. Ghép lại từ token là phá bất biến 1 của bài nộp."""
        text = unicodedata.normalize("NFD", "tiền sản giật")
        offs = [(0, 0), (0, len(text))]
        tags = [IGNORE_ID, LABEL_TO_ID["B-CHẨN_ĐOÁN"]]
        got = tags_to_spans(text, offs, tags)
        assert got[0].text == text[got[0].start : got[0].end]

    def test_gom_B_va_I_thanh_mot_span(self):
        text = "tiền sản giật"
        offs = [(0, 4), (5, 8), (9, 13)]
        tags = [LABEL_TO_ID["B-CHẨN_ĐOÁN"], LABEL_TO_ID["I-CHẨN_ĐOÁN"], LABEL_TO_ID["I-CHẨN_ĐOÁN"]]
        got = tags_to_spans(text, offs, tags)
        assert len(got) == 1 and got[0].text == "tiền sản giật"

    def test_B_moi_mo_span_moi(self):
        text = "sốt ho"
        offs = [(0, 3), (4, 6)]
        tags = [LABEL_TO_ID["B-TRIỆU_CHỨNG"], LABEL_TO_ID["B-TRIỆU_CHỨNG"]]
        assert [e.text for e in tags_to_spans(text, offs, tags)] == ["sốt", "ho"]

    def test_khoang_trang_hai_dau_bi_tia_bang_CHI_SO(self):
        """`strip()` không cho biết đã bỏ bao nhiêu ký tự ⇒ mất `start` đúng."""
        text = "  sốt  "
        got = tags_to_spans(text, [(0, len(text))], [LABEL_TO_ID["B-TRIỆU_CHỨNG"]])
        assert got[0].text == "sốt"
        assert text[got[0].start : got[0].end] == "sốt"

    def test_span_toan_khoang_trang_bi_loai(self):
        assert tags_to_spans("   ", [(0, 3)], [LABEL_TO_ID["B-TRIỆU_CHỨNG"]]) == []


class TestVongTron:
    @pytest.mark.parametrize("form", ["NFC", "NFD"])
    def test_ma_hoa_roi_giai_ma_ra_lai_chinh_no(self, form):
        """★ Bản đầu của chính test này dùng `text.index("tiền")` và NÉM
        `ValueError` ở nhánh NFD — chuỗi literal trong mã nguồn là NFC nên không
        tìm thấy trong văn bản NFD.

        Giữ lại ghi chú vì đó đúng là lớp bug mà cả kiến trúc `synth/` + `bio.py`
        tồn tại để diệt, và nó vừa tự chứng minh mình trên một file test dài 3
        dòng. Ở đường chạy thật, `txt.index()` sẽ không ném — nó sẽ trả về vị trí
        SAI hoặc bỏ sót, im lặng.
        """
        text = unicodedata.normalize(form, "Chẩn đoán: tiền sản giật nặng")
        i = text.index(unicodedata.normalize(form, "tiền"))
        spans = [Entity(text=text[i:], type="CHẨN_ĐOÁN", start=i, end=len(text))]
        offs = [(0, 0), (0, i), (i, len(text)), (0, 0)]
        back = tags_to_spans(text, offs, spans_to_tags(offs, spans))
        assert len(back) == 1
        assert text[back[0].start : back[0].end] == back[0].text
