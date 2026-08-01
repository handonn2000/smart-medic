"""Đường dẫn phải suy ra từ gốc repo và override được bằng biến môi trường."""

from __future__ import annotations

import importlib

from smart_medic.kb import config


def test_project_root_dung():
    assert (config.PROJECT_ROOT / "pyproject.toml").is_file()


def test_duong_dan_nam_duoi_data_dir():
    for p in (config.RAW_DIR, config.STAGING_DIR, config.ARTIFACT_DIR):
        assert config.DATA_DIR in p.parents or p == config.DATA_DIR


def test_override_bang_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SMK_ARTIFACT_DIR", str(tmp_path))
    reloaded = importlib.reload(config)
    try:
        assert tmp_path.resolve() == reloaded.ARTIFACT_DIR
    finally:
        monkeypatch.delenv("SMK_ARTIFACT_DIR")
        importlib.reload(config)


def test_nguong_fanin_nhat_quan():
    """Nạp rộng ở build-time, lọc chặt ở query-time (§P3.2)."""
    assert config.SNOMED_FANIN_QUERY_DEFAULT <= config.SNOMED_FANIN_INGEST_MAX


class TestTimGocDuAn:
    """★ Bug này chỉ lộ khi cài package KHÔNG ở chế độ `-e`.

    Bản đầu đếm cứng `parents[3]`; trong site-packages nó cho ra
    `/usr/local/lib/python3.13` nên `DATA_DIR` trỏ sai hoàn toàn. Container
    build chạy trên dữ liệu rỗng rồi ghi artifact vào chỗ bị vứt đi — mà validate
    vẫn báo "Rule 8/8" vì database rỗng thì không có gì mồ côi để bắt.
    """

    def test_tim_thay_marker_o_to_tien(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        deep = tmp_path / "src" / "pkg" / "sub"
        deep.mkdir(parents=True)
        assert config.find_project_root(deep / "mod.py") == tmp_path.resolve()

    def test_khong_co_marker_thi_roi_ve_cwd(self, tmp_path, monkeypatch):
        """Mô phỏng site-packages: không tổ tiên nào có pyproject.toml."""
        sitepkgs = tmp_path / "lib" / "python3.13" / "site-packages" / "smart_medic" / "kb"
        sitepkgs.mkdir(parents=True)
        workdir = tmp_path / "app"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        assert config.find_project_root(sitepkgs / "config.py") == workdir.resolve()

    def test_lay_marker_GAN_NHAT(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        inner = tmp_path / "vendor" / "lib"
        inner.mkdir(parents=True)
        (inner / "pyproject.toml").write_text("", encoding="utf-8")
        assert config.find_project_root(inner / "x" / "y.py") == inner.resolve()

    def test_repo_that_van_tim_dung(self):
        assert (config.PROJECT_ROOT / "pyproject.toml").is_file()
        assert (config.PROJECT_ROOT / "src" / "smart_medic").is_dir()
