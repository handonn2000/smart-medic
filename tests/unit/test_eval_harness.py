"""Hạ tầng đánh giá — dò cấu trúc bộ gold, ghép cặp theo tên, không gộp bộ."""

from __future__ import annotations

import json

import pytest

from smart_medic.eval.harness import (
    compare_reports,
    find_annotation_dir,
    load_gold,
    paired_finals,
)


def write_gold(root, subdir: str, docs: dict[str, list[dict]]) -> None:
    (root / subdir).mkdir(parents=True, exist_ok=True)
    (root / "text").mkdir(parents=True, exist_ok=True)
    for stem, ents in docs.items():
        (root / subdir / f"{stem}.json").write_text(
            json.dumps(ents, ensure_ascii=False), encoding="utf-8"
        )
        (root / "text" / f"{stem}.txt").write_text("viêm phổi", encoding="utf-8")


def ent(text="viêm phổi", typ="CHẨN_ĐOÁN", pos=(0, 9), cand=(), asrt=()):
    return {
        "text": text,
        "type": typ,
        "candidates": list(cand),
        "assertions": list(asrt),
        "position": list(pos),
    }


class TestDoCauTrucThuMuc:
    def test_uu_tien_annotations_gold(self, tmp_path):
        """gold/ và gold_real/ dùng `annotations_gold/`."""
        write_gold(tmp_path, "annotations_gold", {"1": [ent()]})
        (tmp_path / "annotations").mkdir()
        assert find_annotation_dir(tmp_path).name == "annotations_gold"

    def test_roi_ve_annotations(self, tmp_path):
        """★ gold_batch1 để nhãn ở `annotations/` — dò, không đoán."""
        write_gold(tmp_path, "annotations", {"1": [ent()]})
        assert find_annotation_dir(tmp_path).name == "annotations"

    def test_khong_co_thu_muc_nhan_thi_no(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="không có thư mục nhãn"):
            find_annotation_dir(tmp_path)


class TestLoadGold:
    def test_doc_dung_so_span(self, tmp_path):
        write_gold(tmp_path, "annotations_gold", {"1": [ent(), ent(pos=(10, 19))], "2": [ent()]})
        gold = load_gold(tmp_path)
        assert [len(v) for v in gold.values()] == [2, 1]

    def test_thu_tu_theo_so_khong_theo_chuoi(self, tmp_path):
        """`100.json` phải nằm sau `9.json`, không phải sau `10.json`."""
        write_gold(tmp_path, "annotations_gold", {s: [ent()] for s in ("1", "9", "10", "100")})
        assert list(load_gold(tmp_path)) == ["1", "9", "10", "100"]

    def test_thu_muc_rong_thi_no(self, tmp_path):
        (tmp_path / "annotations_gold").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            load_gold(tmp_path)


def fake_set(finals: dict[str, float], by_type: dict | None = None) -> dict:
    return {
        "final": round(sum(finals.values()) / len(finals), 4),
        "documents": [{"name": k, "final": v} for k, v in finals.items()],
        "by_type": by_type or {},
    }


class TestGhepCapTheoTen:
    def test_can_theo_ten_chu_khong_theo_vi_tri(self):
        """★ Hai lần chạy có thể khác thứ tự duyệt.

        Ghép theo vị trí sẽ trừ file `1` của bên này với file `2` của bên kia —
        cho ra một CI trông hoàn toàn bình thường mà vô nghĩa.
        """
        base = fake_set({"1": 0.1, "2": 0.9})
        new = fake_set({"2": 0.9, "1": 0.1})
        bf, nf, names = paired_finals(base, new)
        assert names == ["1", "2"]
        assert bf == nf == [0.1, 0.9]

    def test_chi_lay_file_chung(self):
        bf, nf, names = paired_finals(
            fake_set({"1": 0.1, "2": 0.2, "3": 0.3}), fake_set({"2": 0.5, "3": 0.6, "4": 0.7})
        )
        assert names == ["2", "3"]
        assert (bf, nf) == ([0.2, 0.3], [0.5, 0.6])

    def test_khong_co_file_chung_thi_no(self):
        with pytest.raises(ValueError, match="không có file nào chung"):
            paired_finals(fake_set({"1": 0.1}), fake_set({"2": 0.2}))


class TestCompareReports:
    def test_bao_cao_rieng_tung_bo_gold(self):
        """★ Quy tắc §5.2: không có ô nào để ghi số gộp ba bộ."""
        base = {"sets": {"gold_real": fake_set({"1": 0.4}), "gold": fake_set({"1": 0.6})}}
        new = {"sets": {"gold_real": fake_set({"1": 0.5}), "gold": fake_set({"1": 0.6})}}
        out = compare_reports(base, new, b=100)
        assert set(out["sets"]) == {"gold_real", "gold"}
        assert out["sets"]["gold_real"]["delta_final"]["point"] == pytest.approx(0.1)
        assert out["sets"]["gold"]["delta_final"]["point"] == pytest.approx(0.0)

    def test_delta_theo_nhanh(self):
        bt_base = {"CHẨN_ĐOÁN": {"recall": 0.8, "precision": 0.7}}
        bt_new = {"CHẨN_ĐOÁN": {"recall": 0.9, "precision": 0.6}}
        out = compare_reports(
            {"sets": {"s": fake_set({"1": 0.4}, bt_base)}},
            {"sets": {"s": fake_set({"1": 0.4}, bt_new)}},
            b=100,
        )
        d = out["sets"]["s"]["by_type_delta"]["CHẨN_ĐOÁN"]
        assert (d["recall"], d["precision"]) == (pytest.approx(0.1), pytest.approx(-0.1))

    def test_khong_co_bo_chung_thi_no(self):
        with pytest.raises(ValueError, match="không có bộ gold nào chung"):
            compare_reports(
                {"sets": {"a": fake_set({"1": 0.1})}},
                {"sets": {"b": fake_set({"1": 0.1})}},
                b=100,
            )
