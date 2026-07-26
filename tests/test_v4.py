"""Regression and safety tests for the opt-in v4 medication path."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.batch import CrossDocumentMaskResolver  # noqa: E402
from smart_medic.infer import main as infer_main  # noqa: E402
from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.schema import ConceptType, Mention, Provenance, Span  # noqa: E402
from smart_medic.stages.extract import RxNormExtractor  # noqa: E402
from smart_medic.stages.medication_v4 import (  # noqa: E402
    DrugAliasStore,
    MedicationAttributeParser,
    MedicationDataError,
    V4MedicationExtractor,
)
from smart_medic.textref import build_textref  # noqa: E402

KB_DIR = ROOT / "data/kb"
FROZEN_V3_OUTPUT_SHA256 = (
    "253026321c4b116ac81047dcf2ba66ed922fbc87282d9b4b3b6fe9d6a993fc24"
)
FROZEN_V3_ZIP_SHA256 = (
    "bd91d7a2d5ef7d26f7144b61cd65b7ce1b5987bdda6d216cc0966f5d2b7020da"
)


class TestMedicationAttributeParser(unittest.TestCase):
    def test_structured_vietnamese_regimen(self):
        attrs = MedicationAttributeParser().parse(
            "Medrol 16mg x 3 viên, uống 8h sáng", anchor="Medrol"
        )
        self.assertEqual("medrol", attrs.name)
        self.assertEqual(("16",), attrs.strengths)
        self.assertEqual(("mg",), attrs.units)
        self.assertEqual("tablet", attrs.dose_form)
        self.assertEqual("PO", attrs.route)
        self.assertEqual("x 3 viên", attrs.quantity)

    def test_microgram_and_mask_are_normalized(self):
        attrs = MedicationAttributeParser().parse("******** 25 μg viên")
        self.assertEqual(("25",), attrs.strengths)
        self.assertEqual(("mcg",), attrs.units)
        self.assertTrue(attrs.masked)


@unittest.skipUnless((KB_DIR / "MANIFEST.json").exists(), "chưa build KB")
class TestV4MedicationExtractor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load_kb(KB_DIR)

    @staticmethod
    def _snapshot(candidates):
        return [
            {
                "span": asdict(candidate.span),
                "type": candidate.type.value,
                "codes": candidate.codes,
                "provenance": asdict(candidate.provenance),
            }
            for candidate in candidates
        ]

    def test_strict_wrapper_is_identical_to_v3_extractor(self):
        cases = (
            "Dùng gleevec theo chỉ định.",
            "Được cho aspirin 325mg, 1 viên uống.",
            "Kết quả xét nghiệm glucose 120 mg/dL.",
            "Dùng ******** 25 mg theo chỉ định.",
        )
        base = RxNormExtractor(self.kb, contextual_analytes=True)
        strict = V4MedicationExtractor(self.kb, specificity="strict")
        for raw in cases:
            with self.subTest(raw=raw):
                tref = build_textref(raw)
                self.assertEqual(
                    self._snapshot(base.extract(tref)),
                    self._snapshot(strict.extract(tref)),
                )

    def test_hierarchical_mode_links_exact_unique_name_only(self):
        candidate = V4MedicationExtractor(
            self.kb, specificity="hierarchical"
        ).extract(build_textref("Dùng gleevec theo chỉ định."))[0]
        self.assertEqual(1, len(candidate.codes))
        self.assertIn(self.kb.rx_concepts[candidate.codes[0]]["tty"], {"IN", "BN"})
        self.assertEqual(
            "rxnorm_hierarchical_backoff", candidate.provenance.link_path
        )
        self.assertEqual(
            self.kb.rx_concepts[candidate.codes[0]]["tty"],
            candidate.provenance.evidence["specificity_tty"],
        )

    def test_hierarchical_mode_never_identifies_a_mask(self):
        candidate = V4MedicationExtractor(
            self.kb, specificity="hierarchical"
        ).extract(build_textref("Dùng ******** theo chỉ định."))[0]
        self.assertEqual((), candidate.codes)
        self.assertEqual("masked_unresolved", candidate.provenance.link_path)

    def test_hierarchical_mode_keeps_analyte_block(self):
        candidates = V4MedicationExtractor(
            self.kb, specificity="hierarchical"
        ).extract(build_textref("Kết quả xét nghiệm glucose 120 mg/dL."))
        self.assertEqual([], candidates)

    def test_reviewed_external_product_alias_is_traceable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aliases.csv"
            fields = list(DrugAliasStore.REQUIRED_COLUMNS)
            # Use a stable explicit field order rather than frozenset order.
            fields = [
                "alias", "rxcui", "tty", "ingredient", "strength", "unit",
                "dose_form", "source", "source_version", "license",
                "evidence_level", "review_status",
            ]
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "alias": "thuốc mẫu", "rxcui": "243670", "tty": "SCD",
                    "ingredient": "aspirin", "strength": "81", "unit": "mg",
                    "dose_form": "tablet", "source": "fixture",
                    "source_version": "1", "license": "test-only",
                    "evidence_level": "product", "review_status": "approved",
                })
            store = DrugAliasStore.from_csv(path, self.kb)
            candidates = V4MedicationExtractor(
                self.kb, specificity="strict", alias_store=store
            ).extract(build_textref("Dùng thuốc mẫu 81 mg viên uống."))
            medication = next(
                candidate for candidate in candidates
                if candidate.type is ConceptType.THUOC
            )
            self.assertEqual(("243670",), medication.codes)
            self.assertIn("drug-alias:", " ".join(medication.provenance.kb_rows))

    def test_external_alias_rejects_tty_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aliases.csv"
            path.write_text(
                "alias,rxcui,tty,ingredient,strength,unit,dose_form,source,"
                "source_version,license,evidence_level,review_status\n"
                "thuốc mẫu,243670,BN,aspirin,81,mg,tablet,fixture,1,test,product,approved\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MedicationDataError, "does not match"):
                DrugAliasStore.from_csv(path, self.kb)

    def test_hierarchical_links_are_not_mask_support(self):
        raw_visible = "Danh sách thuốc dùng tại nhà: gleevec"
        raw_masked = "Danh sách thuốc dùng tại nhà: *******"
        tref_visible = build_textref(raw_visible)
        tref_masked = build_textref(raw_masked)
        linked = V4MedicationExtractor(
            self.kb, specificity="hierarchical"
        ).extract(tref_visible)[0]
        masked_candidate = V4MedicationExtractor(
            self.kb, specificity="hierarchical"
        ).extract(tref_masked)[0]
        linked_mention = Mention(
            span=linked.span, type=linked.type, candidates=linked.codes,
            provenance=linked.provenance,
        )
        masked_mention = Mention(
            span=masked_candidate.span, type=masked_candidate.type,
            candidates=(), provenance=masked_candidate.provenance,
        )
        stats = CrossDocumentMaskResolver(
            excluded_support_paths=("rxnorm_hierarchical_backoff",)
        ).resolve({
            "visible.txt": (tref_visible, [linked_mention]),
            "masked.txt": (tref_masked, [masked_mention]),
        })
        self.assertEqual(0, stats.resolved)
        self.assertEqual((), masked_mention.candidates)


@unittest.skipUnless((ROOT / "data/test/100.txt").exists(), "corpus unavailable")
class TestV3FrozenCompatibility(unittest.TestCase):
    def test_v3_and_v4_strict_numeric_outputs_are_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v3_out = root / "v3"
            v4_out = root / "v4"
            v3_zip = root / "v3.zip"
            self.assertEqual(0, infer_main([
                "--input", str(ROOT / "data/test"),
                "--output", str(v3_out),
                "--kb", str(KB_DIR),
                "--extractor", "v3",
                "--zip", str(v3_zip),
            ]))
            self.assertEqual(0, infer_main([
                "--input", str(ROOT / "data/test"),
                "--output", str(v4_out),
                "--kb", str(KB_DIR),
                "--extractor", "v4",
                "--rxnorm-specificity", "strict",
            ]))
            v3_manifest = json.loads(
                (v3_out / "run_manifest.json").read_text(encoding="utf-8")
            )
            v4_manifest = json.loads(
                (v4_out / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(FROZEN_V3_OUTPUT_SHA256, v3_manifest["output_sha256"])
            self.assertEqual(FROZEN_V3_OUTPUT_SHA256, v4_manifest["output_sha256"])
            self.assertEqual(
                FROZEN_V3_ZIP_SHA256,
                hashlib.sha256(v3_zip.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
