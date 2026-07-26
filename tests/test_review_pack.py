"""Tests for deterministic medication curation artifacts."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.review_pack import ReviewPackError, build_review_pack  # noqa: E402

KB_DIR = ROOT / "data/kb"


@unittest.skipUnless((KB_DIR / "MANIFEST.json").exists(), "chưa build KB")
class TestReviewPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load_kb(KB_DIR)

    @staticmethod
    def _fixture(root: Path) -> tuple[Path, Path]:
        input_dir = root / "input"
        input_dir.mkdir()
        raw1 = "Thuốc đang dùng: gleevec. Không sốt."
        raw2 = unicodedata.normalize("NFD", "Thuốc đang dùng: gleevec.")
        (input_dir / "1.txt").write_text(raw1, encoding="utf-8")
        (input_dir / "2.txt").write_text(raw2, encoding="utf-8")

        records = {}
        for name, raw in (("1.txt", raw1), ("2.txt", raw2)):
            surface = "gleevec"
            start = raw.index(surface)
            records[name] = [
                {
                    "text": surface,
                    "type": "THUỐC",
                    "candidates": [],
                    "assertions": [],
                    "position": [start, start + len(surface)],
                    "_provenance": {
                        "extractor": "rxnorm_v3_2",
                        "locate_method": "rxnorm_anchor_scan",
                        "link_path": "rxnorm_anchor_only",
                        "kb_rows": ["rx-anchor:test"],
                        "scores": {"confidence": 0.0},
                        "evidence": {"anchor": "gleevec"},
                    },
                },
                {
                    "text": "sốt" if name == "1.txt" else surface,
                    "type": "TRIỆU_CHỨNG",
                    "candidates": [],
                    "assertions": [],
                    "position": [0, 1],
                    "_provenance": {},
                },
            ]
        explain = root / "explain.json"
        explain.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return input_dir, explain

    def test_all_layers_are_deterministic_and_offsets_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            input_dir, explain = self._fixture(temp)
            curation = temp / "curation"
            first = build_review_pack(
                input_dir=input_dir,
                explain_path=explain,
                kb=self.kb,
                root=curation,
                scope="all",
            )
            files = [
                first["bronze"] / "MANIFEST.json",
                first["silver"] / "medication_mentions.csv",
                first["silver"] / "medication_groups.csv",
                first["silver"] / "MANIFEST.json",
                first["gold"] / "medication_annotations.csv",
                first["gold"] / "MANIFEST.json",
            ]
            before = {path: path.read_bytes() for path in files}
            second = build_review_pack(
                input_dir=input_dir,
                explain_path=explain,
                kb=self.kb,
                root=curation,
                scope="all",
            )
            self.assertEqual(2, second["mentions"])
            self.assertEqual(1, second["groups"])
            self.assertEqual(before, {path: path.read_bytes() for path in files})

            with (second["silver"] / "medication_mentions.csv").open(
                encoding="utf-8", newline=""
            ) as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(2, len(rows))
            self.assertTrue(all(row["surface_text"] == "gleevec" for row in rows))
            self.assertTrue(all("⟦gleevec⟧" in row["display_context"] for row in rows))
            self.assertTrue(all(row["review_reason"] == "plaintext_unlinked" for row in rows))

    def test_stale_explain_offset_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            input_dir, explain = self._fixture(temp)
            value = json.loads(explain.read_text(encoding="utf-8"))
            value["1.txt"][0]["position"] = [0, 7]
            explain.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ReviewPackError, "offset mismatch"):
                build_review_pack(
                    input_dir=input_dir,
                    explain_path=explain,
                    kb=self.kb,
                    root=temp / "curation",
                    scope="all",
                )

    def test_existing_changed_gold_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            input_dir, explain = self._fixture(temp)
            result = build_review_pack(
                input_dir=input_dir,
                explain_path=explain,
                kb=self.kb,
                root=temp / "curation",
                scope="all",
            )
            gold = result["gold"] / "medication_annotations.csv"
            gold.write_text("human edit\n", encoding="utf-8")
            with self.assertRaisesRegex(ReviewPackError, "refusing to overwrite"):
                build_review_pack(
                    input_dir=input_dir,
                    explain_path=explain,
                    kb=self.kb,
                    root=temp / "curation",
                    scope="all",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
