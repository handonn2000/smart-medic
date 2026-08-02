"""Tagger: suy biến an toàn khi thiếu torch, và ghép cửa sổ.

Không test nào ở đây cần torch — toàn bộ phần dễ sai nằm ở `stages/bio.py`, và
đó là điều kiện để Phase 6 đóng gói được image runtime không có torch.
"""

from __future__ import annotations

from smart_medic.stages import tagger
from smart_medic.stages.scoring import Entity


class TestSuyBienAnToan:
    """★ PRD §5: BTC cài lại không được thì BỊ LOẠI. Thiếu torch phải chạy tiếp."""

    def test_tat_co_thi_tra_rong(self):
        assert tagger.detect("viêm phổi", enabled=False) == []

    def test_bat_co_ma_thieu_checkpoint_van_khong_nem(self):
        assert tagger.detect("viêm phổi", enabled=True) == []

    def test_load_nem_TaggerUnavailable_khi_thieu_checkpoint(self, tmp_path):
        import pytest

        with pytest.raises(tagger.TaggerUnavailable):
            tagger.load(tmp_path / "khong-co")

    def test_khong_import_torch_o_top_level(self):
        """Đọc CÂY CÚ PHÁP: `import torch` phải nằm trong hàm, không ở mức module.

        Bản đầu của test này quét chuỗi trong mã nguồn và **đỏ vì chính docstring
        của module** — nơi giải thích tại sao torch phải nạp lười. Quét chuỗi
        không phân biệt được mã với văn xuôi; `ast` thì có.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(tagger))
        top_level = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
        names = {
            (n.module or "") if isinstance(n, ast.ImportFrom) else n.names[0].name
            for n in top_level
        }
        assert not {n for n in names if n.split(".")[0] in {"torch", "transformers"}}


class TestGhepCuaSo:
    def test_bo_span_trung_giua_hai_cua_so(self):
        a = Entity("sốt", "TRIỆU_CHỨNG", 0, 3)
        b = Entity("sốt", "TRIỆU_CHỨNG", 0, 3)
        assert len(tagger._merge([a, b])) == 1

    def test_span_dai_thang_span_ngan_chong_lan(self):
        short = Entity("sốt", "TRIỆU_CHỨNG", 0, 3)
        long = Entity("sốt cao", "TRIỆU_CHỨNG", 0, 7)
        got = tagger._merge([short, long])
        assert [e.text for e in got] == ["sốt cao"]

    def test_span_roi_nhau_giu_ca_hai(self):
        got = tagger._merge([Entity("sốt", "TRIỆU_CHỨNG", 0, 3), Entity("ho", "TRIỆU_CHỨNG", 5, 7)])
        assert len(got) == 2

    def test_ket_qua_sap_theo_vi_tri(self):
        got = tagger._merge([Entity("ho", "TRIỆU_CHỨNG", 5, 7), Entity("sốt", "TRIỆU_CHỨNG", 0, 3)])
        assert [e.start for e in got] == [0, 5]

    def test_tat_dinh(self):
        spans = [Entity("a", "TRIỆU_CHỨNG", 0, 1), Entity("b", "CHẨN_ĐOÁN", 0, 1)]
        assert tagger._merge(spans) == tagger._merge(list(reversed(spans)))


class TestNguongTinCay:
    def test_duoi_nguong_thi_ep_ve_O(self):
        row = [0.0] + [-0.5] * 10  # nhãn thực thể tốt nhất chỉ hơn O 0,5 nat
        assert tagger._suppress(row, threshold=1.0)[0] > row[0]

    def test_vuot_nguong_thi_giu_nguyen(self):
        row = [-5.0, 0.0] + [-9.0] * 9
        assert tagger._suppress(row, threshold=1.0) == row
