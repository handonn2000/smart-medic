"""Hợp đồng staging — biên giới giữa `extract` và `load`.

Đổi bất kỳ thứ gì ở đây là BREAKING CHANGE với mọi extractor.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from smart_medic.kb import staging

REQUIRED_FIELDS = {
    "concepts": {
        "vocab",
        "code",
        "source",
        "entity_kind",
        "pref_vi",
        "pref_en",
        "is_active",
    },
    "terms": {
        "vocab",
        "code",
        "source",
        "term",
        "lang",
        "term_type",
        "is_preferred",
        "tier",
        "evidence",
    },
    "relations": {
        "src_vocab",
        "src_code",
        "rel",
        "dst_vocab",
        "dst_code",
        "rel_group",
        "priority",
        "tier",
        "meta",
    },
    "attributes": {"vocab", "code", "attr", "value"},
    "sources": {"source", "release", "origin_file", "sha256", "n_rows"},
}


def test_dung_du_5_bang_staging():
    assert set(staging.STAGING_SCHEMAS) == set(REQUIRED_FIELDS)


@pytest.mark.parametrize("name", sorted(REQUIRED_FIELDS))
def test_schema_co_dung_cot(name):
    assert set(staging.STAGING_SCHEMAS[name].names) == REQUIRED_FIELDS[name]


@pytest.mark.parametrize("name", sorted(REQUIRED_FIELDS))
def test_schema_la_pyarrow(name):
    assert isinstance(staging.STAGING_SCHEMAS[name], pa.Schema)


def test_khoa_tu_nhien_khong_duoc_null():
    """Staging dùng (vocab, code) làm khoá — không được nullable."""
    for name in ("concepts", "terms", "attributes"):
        sch = staging.STAGING_SCHEMAS[name]
        assert not sch.field("vocab").nullable
        assert not sch.field("code").nullable


def test_staging_khong_co_concept_id():
    """concept_id chỉ được gán ở pha `load`, không tồn tại ở staging (§5.2)."""
    for sch in staging.STAGING_SCHEMAS.values():
        assert "concept_id" not in sch.names


def test_gia_tri_hop_le_duoc_khai_bao():
    assert set(staging.TIERS) == {"authoritative", "derived", "generated"}
    assert set(staging.LANGS) == {"vi", "en"}
    assert set(staging.VOCABS) == {"icd10", "rxnorm", "snomed"}
