"""Pha `normalize` — staging/raw/ → staging/norm/.

Chạy trên staging giả trong tmp_path nên nhanh và không cần nguồn thô.
"""

from __future__ import annotations

import importlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from smart_medic.kb import staging


@pytest.fixture
def staged(monkeypatch, tmp_path):
    """Dựng staging/raw/ tối thiểu rồi trả module `normalize` đã trỏ vào đó."""
    monkeypatch.setenv("SMK_STAGING_DIR", str(tmp_path))
    from smart_medic.kb import config

    importlib.reload(config)
    normalize = importlib.reload(importlib.import_module("smart_medic.kb.normalize"))

    raw = tmp_path / staging.RAW_SUBDIR
    raw.mkdir(parents=True)
    rows = {
        "concepts": [
            {
                "vocab": "icd10",
                "code": "D55.0",
                "source": "s",
                "entity_kind": "disease",
                "pref_vi": "Thiếu men G6PD",
                "pref_en": None,
                "is_active": True,
            }
        ],
        "terms": [
            {
                "vocab": "icd10",
                "code": "D55.0",
                "source": "s",
                "term": "  Thiếu men  G6PD  ",
                "lang": "vi",
                "term_type": "preferred",
                "is_preferred": True,
                "tier": "authoritative",
                "evidence": None,
            },
            {
                "vocab": "rxnorm",
                "code": "243670",
                "source": "s",
                "term": "aspirin 81MG Oral Tablet",
                "lang": "en",
                "term_type": "SCD",
                "is_preferred": True,
                "tier": "authoritative",
                "evidence": None,
            },
        ],
        "relations": [],
        "attributes": [],
        "sources": [
            {
                "source": "s",
                "release": None,
                "origin_file": None,
                "sha256": None,
                "n_rows": 1,
            }
        ],
    }
    for name, schema in staging.STAGING_SCHEMAS.items():
        pq.write_table(pa.Table.from_pylist(rows[name], schema=schema), raw / f"{name}.parquet")

    yield normalize, tmp_path

    monkeypatch.delenv("SMK_STAGING_DIR")
    importlib.reload(config)
    importlib.reload(importlib.import_module("smart_medic.kb.normalize"))


def _terms(tmp_path):
    return pq.read_table(tmp_path / staging.NORM_SUBDIR / "terms.parquet").to_pylist()


def test_sinh_du_5_file(staged):
    normalize, tmp_path = staged
    normalize.run()
    for name in staging.STAGING_SCHEMAS:
        assert (tmp_path / staging.NORM_SUBDIR / f"{name}.parquet").is_file()


def test_terms_co_them_hai_cot(staged):
    normalize, tmp_path = staged
    normalize.run()
    schema = pq.read_schema(tmp_path / staging.NORM_SUBDIR / "terms.parquet")
    assert set(schema.names) == set(staging.NORM_TERMS_SCHEMA.names)


def test_chuan_hoa_tieng_viet(staged):
    normalize, tmp_path = staged
    normalize.run()
    row = next(r for r in _terms(tmp_path) if r["vocab"] == "icd10")
    assert row["norm_term"] == "thiếu men g6pd"
    assert row["ascii_term"] == "thieu men g6pd"


def test_chuan_hoa_ham_luong_cho_rxnorm(staged):
    """Chỉ bộ mã có hàm lượng mới đi qua `normalize_dosage`."""
    normalize, tmp_path = staged
    normalize.run()
    row = next(r for r in _terms(tmp_path) if r["vocab"] == "rxnorm")
    assert row["norm_term"] == "aspirin 81 mg oral tablet"


def test_bang_khac_duoc_chep_nguyen(staged):
    normalize, tmp_path = staged
    counts = normalize.run()
    assert counts["concepts"] == 1
    assert counts["terms"] == 2


def test_bao_loi_ro_khi_thieu_staging(monkeypatch, tmp_path):
    monkeypatch.setenv("SMK_STAGING_DIR", str(tmp_path / "trong"))
    from smart_medic.kb import config

    importlib.reload(config)
    normalize = importlib.reload(importlib.import_module("smart_medic.kb.normalize"))
    try:
        with pytest.raises(FileNotFoundError, match="smk kb extract"):
            normalize.run()
    finally:
        monkeypatch.delenv("SMK_STAGING_DIR")
        importlib.reload(config)
        importlib.reload(importlib.import_module("smart_medic.kb.normalize"))
