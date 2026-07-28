"""Deployment integrity and reproducibility regression tests for v3."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.infer import package_zip  # noqa: E402
from smart_medic.kb.build import _write  # noqa: E402
from smart_medic.kb.store import KBError, load_kb  # noqa: E402

KB_DIR = ROOT / "data/kb"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestDeterministicArtifacts(unittest.TestCase):
    def test_gzip_writer_is_byte_reproducible(self):
        rows = [{"code": "A01", "name": "thử"}, {"code": "B02", "name": "test"}]
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.csv.gz"
            second = Path(tmp) / "second.csv.gz"
            _write(first, rows)
            _write(second, rows)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with gzip.open(first, "rt", encoding="utf-8", newline="") as fh:
                self.assertEqual(rows, list(csv.DictReader(fh)))

    def test_submission_zip_ignores_mtime_and_stale_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "output"
            out.mkdir()
            (out / "2.json").write_text('[{"id": 2}]', encoding="utf-8")
            (out / "1.json").write_text('[{"id": 1}]', encoding="utf-8")
            (out / "99.json").write_text('[{"stale": true}]', encoding="utf-8")
            (out / "run_manifest.json").write_text("{}", encoding="utf-8")
            first, second = root / "first.zip", root / "second.zip"
            current_run = [out / "2.json", out / "1.json"]

            self.assertEqual(2, package_zip(out, first, current_run))
            os.utime(out / "1.json", (1_900_000_000, 1_900_000_000))
            os.utime(out / "2.json", (1_000_000_000, 1_000_000_000))
            self.assertEqual(2, package_zip(out, second, current_run))

            self.assertEqual(sha256(first), sha256(second))
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(["output/1.json", "output/2.json"], archive.namelist())
                self.assertTrue(
                    all(info.date_time == (1980, 1, 1, 0, 0, 0)
                        for info in archive.infolist())
                )
                self.assertTrue(
                    all(info.external_attr >> 16 == 0o100644
                        for info in archive.infolist())
                )


@unittest.skipUnless((KB_DIR / "MANIFEST.json").exists(), "chưa build KB")
class TestKnowledgeBaseIntegrity(unittest.TestCase):
    def test_checked_in_kb_matches_manifest(self):
        kb = load_kb(KB_DIR)
        artifacts = kb.manifest["artifacts"]
        self.assertEqual(2, kb.manifest["manifest_version"])
        self.assertEqual(5, len(artifacts))
        for name, metadata in artifacts.items():
            with self.subTest(name=name):
                path = KB_DIR / name
                self.assertEqual(metadata["bytes"], path.stat().st_size)
                self.assertEqual(metadata["sha256"], sha256(path))

    def test_tampered_kb_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "kb"
            shutil.copytree(KB_DIR, copied)
            target = copied / "icd10_aliases.csv.gz"
            target.write_bytes(target.read_bytes() + b"tampered")
            with self.assertRaisesRegex(KBError, "sai kích thước"):
                load_kb(copied)

    def test_unmanifested_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "kb"
            shutil.copytree(KB_DIR, copied)
            (copied / "stale.csv.gz").write_bytes(b"")
            with self.assertRaisesRegex(KBError, "không được manifest"):
                load_kb(copied)


if __name__ == "__main__":
    unittest.main(verbosity=2)
