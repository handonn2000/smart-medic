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
