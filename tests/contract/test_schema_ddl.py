"""`ddl.sql` phải áp được sạch và chứa đúng các bảng đã thiết kế."""

from __future__ import annotations

import sqlite3

import pytest

from smart_medic.kb.schema.version import SCHEMA_VERSION, read_ddl

EXPECTED_TABLES = {
    "schema_meta",
    "sources",
    "concepts",
    "terms",
    "relations",
    "attributes",
    "closure",
}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(read_ddl())
    yield conn
    conn.close()


def test_ddl_ap_duoc_sach(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= EXPECTED_TABLES


def test_fts5_dung_duoc(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "terms_fts" in names


def test_closure_ton_tai_tu_phase_0(db):
    """Bảng có sẵn dù Phase 3 mới điền — giữ nguyên tắc 'schema ở một chỗ'."""
    assert db.execute("SELECT count(*) FROM closure").fetchone()[0] == 0


def test_closure_cam_tu_to_tien(db):
    db.execute("INSERT INTO concepts VALUES (1,'icd10','A00','disease',NULL,NULL,1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO closure VALUES (1, 1, 0)")


def test_tier_derived_bat_buoc_co_evidence(db):
    db.execute("INSERT INTO sources (source) VALUES ('s1')")
    db.execute("INSERT INTO concepts VALUES (1,'icd10','A00','disease',NULL,NULL,1)")
    ok = (
        "INSERT INTO terms (concept_id,vocab,source,term,norm_term,ascii_term,"
        "lang,term_type,tier,evidence) VALUES (?,?,?,?,?,?,?,?,?,?)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(ok, (1, "icd10", "s1", "x", "x", "x", "vi", "preferred", "derived", None))
    db.execute(ok, (1, "icd10", "s1", "x", "x", "x", "vi", "preferred", "derived", "{}"))


def test_lang_bi_rang_buoc(db):
    db.execute("INSERT INTO sources (source) VALUES ('s1')")
    db.execute("INSERT INTO concepts VALUES (1,'icd10','A00','disease',NULL,NULL,1)")
    stmt = (
        "INSERT INTO terms (concept_id,vocab,source,term,norm_term,ascii_term,"
        "lang,term_type) VALUES (?,?,?,?,?,?,?,?)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(stmt, (1, "icd10", "s1", "x", "x", "x", "fr", "preferred"))


def test_vocab_code_la_duy_nhat(db):
    db.execute("INSERT INTO concepts VALUES (1,'icd10','A00','disease',NULL,NULL,1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO concepts VALUES (2,'icd10','A00','disease',NULL,NULL,1)")


def test_schema_version_dung_dinh_dang():
    parts = SCHEMA_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
