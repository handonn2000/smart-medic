"""Chạy đầu-cuối và năm bất biến của định dạng nộp bài."""

from __future__ import annotations

import json
import zipfile

import pytest

from smart_medic.stages.scoring import Entity
from smart_medic.stages.solve import (
    OutputInvariantError,
    check_invariants,
    write_zip,
)


def ent(text, typ, start, cand=(), asrt=()):
    return Entity(text, typ, start, start + len(text), tuple(cand), tuple(asrt))


class TestBatBienDinhDang:
    def test_hop_le_thi_khong_no(self):
        text = "bệnh nhân viêm phổi nặng"
        check_invariants(text, [ent("viêm phổi", "CHẨN_ĐOÁN", 10, cand=("J18.9",))])

    def test_span_khong_khop_van_ban(self):
        """★ Lỗi im lặng, ăn điểm cả text_score lẫn tính hợp lệ của position."""
        with pytest.raises(OutputInvariantError, match="span"):
            check_invariants("bệnh nhân viêm phổi", [ent("viêm phổi", "CHẨN_ĐOÁN", 0)])

    def test_nhan_la_bi_chan(self):
        with pytest.raises(OutputInvariantError, match="nhãn lạ"):
            check_invariants("abc", [ent("abc", "KHÔNG_TỒN_TẠI", 0)])

    @pytest.mark.parametrize("typ", ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"])
    def test_nhan_khong_duoc_gan_ma(self, typ):
        """Đề quy định rỗng; Jaccard rỗng-gặp-rỗng = 1,0 nên gán bừa là mất điểm."""
        with pytest.raises(OutputInvariantError, match="candidates"):
            check_invariants("ho", [ent("ho", typ, 0, cand=("R05",))])

    @pytest.mark.parametrize("typ", ["TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"])
    def test_nhan_khong_duoc_gan_assertion(self, typ):
        with pytest.raises(OutputInvariantError, match="assertions"):
            check_invariants("spo2", [ent("spo2", typ, 0, asrt=("isNegated",))])

    def test_span_chong_lan_bi_chan(self):
        text = "đau ngực nhiều"
        overlapping = [ent("đau ngực", "TRIỆU_CHỨNG", 0), ent("ngực", "TRIỆU_CHỨNG", 4)]
        with pytest.raises(OutputInvariantError, match="chồng lấn"):
            check_invariants(text, overlapping)

    def test_khong_co_entity_thi_hop_le(self):
        check_invariants("văn bản không có khái niệm y tế", [])


class TestChayDauCuoi:
    @pytest.fixture
    def workspace(self, tmp_path):
        src = tmp_path / "in"
        src.mkdir()
        (src / "1.txt").write_text("Bệnh nhân bị viêm phổi.", encoding="utf-8")
        (src / "2.txt").write_text("Tiền sử tăng huyết áp.", encoding="utf-8")
        return src, tmp_path / "out"

    def test_moi_txt_ra_dung_mot_json(self, workspace):
        from smart_medic.stages import solve

        src, out = workspace
        stats = solve.run(input_dir=src, out_dir=out)
        assert stats.n_docs == 2
        assert {p.name for p in out.glob("*.json")} == {"1.json", "2.json"}

    def test_ghi_utf8_khong_escape(self, workspace):
        """`ensure_ascii=False` — PRD §8 nêu đích danh."""
        from smart_medic.stages import solve

        src, out = workspace
        solve.run(input_dir=src, out_dir=out)
        raw = (out / "1.json").read_text(encoding="utf-8")
        assert "\\u" not in raw

    def test_thu_muc_rong_thi_bao_loi(self, tmp_path):
        from smart_medic.stages import solve

        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            solve.run(input_dir=empty, out_dir=tmp_path / "o")

    def test_phat_hien_file_sot_lai(self, workspace):
        """★ File từ lần chạy trước sẽ lọt vào bài nộp nếu không cảnh báo."""
        from smart_medic.stages import solve

        src, out = workspace
        out.mkdir(parents=True)
        (out / "run_manifest.json").write_text("{}", encoding="utf-8")
        stats = solve.run(input_dir=src, out_dir=out)
        assert stats.stale == ["run_manifest.json"]


class TestDongGoi:
    def test_zip_chi_chua_file_ung_voi_input(self, tmp_path):
        src = tmp_path / "in"
        src.mkdir()
        (src / "1.txt").write_text("x", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        (out / "1.json").write_text("[]", encoding="utf-8")
        (out / "run_manifest.json").write_text("{}", encoding="utf-8")

        z = tmp_path / "sub.zip"
        assert write_zip(out, z, input_dir=src) == 1
        with zipfile.ZipFile(z) as f:
            assert f.namelist() == ["output/1.json"]

    def test_thieu_ket_qua_thi_bao_loi(self, tmp_path):
        src = tmp_path / "in"
        src.mkdir()
        (src / "1.txt").write_text("x", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(FileNotFoundError, match="1.txt"):
            write_zip(out, tmp_path / "s.zip", input_dir=src)

    def test_cau_truc_zip_theo_prd(self, tmp_path):
        """PRD §5: `output/1.json … 100.json` bên trong zip."""
        src = tmp_path / "in"
        src.mkdir()
        for n in ("1", "10", "2"):
            (src / f"{n}.txt").write_text("x", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        for n in ("1", "10", "2"):
            (out / f"{n}.json").write_text("[]", encoding="utf-8")

        z = tmp_path / "s.zip"
        write_zip(out, z, input_dir=src)
        with zipfile.ZipFile(z) as f:
            assert f.namelist() == ["output/1.json", "output/2.json", "output/10.json"]
            assert json.loads(f.read("output/1.json")) == []
