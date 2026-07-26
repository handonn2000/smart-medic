"""Regression tests for the deterministic v2 providers and simulator."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.metric_simulator import (  # noqa: E402
    candidates_at_threshold,
    sweep,
)
from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.pipeline import Pipeline, PipelineConfig  # noqa: E402
from smart_medic.retrieval import IcdRetriever  # noqa: E402
from smart_medic.score import score_file  # noqa: E402
from smart_medic.schema import ConceptType  # noqa: E402
from smart_medic.stages.extract import (  # noqa: E402
    CompositeExtractor,
    GazetteerExtractor,
    IcdCueExtractor,
    RxNormExtractor,
)
from smart_medic.textref import build_textref, read_textref  # noqa: E402

KB_DIR = ROOT / "data/kb"


@unittest.skipUnless((KB_DIR / "icd10_aliases.csv.gz").exists(), "chưa build KB")
class TestV2Providers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load_kb(KB_DIR)

    def test_icd_reranker_expands_g6pd(self):
        ranked = IcdRetriever(self.kb).retrieve("thiếu men G6PD")
        self.assertTrue(ranked)
        self.assertEqual("D55.0", ranked[0].code)
        self.assertGreaterEqual(ranked[0].score, 0.80)

    def test_strong_cue_extracts_colloquial_diagnosis(self):
        raw = "Bệnh nhân được chẩn đoán thiếu men G6PD."
        mentions = IcdCueExtractor(self.kb).extract(build_textref(raw))
        self.assertEqual(1, len(mentions))
        self.assertEqual("thiếu men G6PD", mentions[0].span.text)
        self.assertEqual("D55.0", mentions[0].codes[0])
        self.assertTrue(mentions[0].span.verify(raw))

    def test_rxnorm_requires_dose_form_evidence(self):
        extractor = RxNormExtractor(self.kb)
        ambiguous = extractor.extract(build_textref("Được cho aspirin 325mg x 1."))
        self.assertEqual(1, len(ambiguous))
        self.assertEqual((), ambiguous[0].codes)

        supported_text = "Được cho aspirin 325mg, 1 viên uống."
        supported = extractor.extract(build_textref(supported_text))
        self.assertEqual("212033", supported[0].codes[0])
        self.assertTrue(supported[0].span.verify(supported_text))

    def test_analyte_is_not_extracted_as_drug(self):
        mentions = RxNormExtractor(self.kb).extract(
            build_textref("Kết quả xét nghiệm glucose 120 mg/dL.")
        )
        self.assertEqual([], mentions)

    def test_masked_drug_is_safe_when_unresolved(self):
        text = "Danh sách thuốc: ********** chưa xác định."
        mentions = RxNormExtractor(self.kb).extract(build_textref(text))
        self.assertEqual(1, len(mentions))
        self.assertIs(ConceptType.THUOC, mentions[0].type)
        self.assertEqual((), mentions[0].codes)
        self.assertEqual("masked_unresolved", mentions[0].provenance.link_path)

    def test_pipeline_keeps_only_close_scored_candidates(self):
        text = "Được cho aspirin 325mg, 1 viên uống."
        pipe = Pipeline(
            self.kb,
            RxNormExtractor(self.kb),
            PipelineConfig(candidate_threshold=0.80, ambiguity_margin=0.01),
        )
        mentions = pipe.run(build_textref(text))
        self.assertEqual(("212033",), mentions[0].candidates)

    def test_curated_metric_fixture_improves_over_v0(self):
        fixture = ROOT / "tests/fixtures/v2_metric"
        gazetteer = GazetteerExtractor(self.kb)
        v0 = Pipeline(self.kb, gazetteer)
        v2 = Pipeline(
            self.kb,
            CompositeExtractor(
                gazetteer,
                IcdCueExtractor(self.kb),
                RxNormExtractor(self.kb),
            ),
        )
        scores = {"v0": [], "v2": []}
        for source in sorted((fixture / "input").glob("*.txt")):
            tref = read_textref(source)
            gold = json.loads(
                (fixture / "gold" / f"{source.stem}.json").read_text(encoding="utf-8")
            )
            for name, pipeline in (("v0", v0), ("v2", v2)):
                predicted = [mention.to_dict() for mention in pipeline.run(tref)]
                row = score_file(gold, predicted)
                scores[name].append(
                    0.3 * row["text"] + 0.3 * row["assertions"] + 0.4 * row["candidates"]
                )
        v0_score = sum(scores["v0"]) / len(scores["v0"])
        v2_score = sum(scores["v2"]) / len(scores["v2"])
        self.assertAlmostEqual(1.0, v2_score)
        self.assertGreater(v2_score, v0_score)

    def test_near_duplicate_pair_has_consistent_semantic_output(self):
        """Files 76/83 are a measured near-duplicate pair in the roadmap."""
        pipeline = Pipeline(
            self.kb,
            CompositeExtractor(
                GazetteerExtractor(self.kb),
                IcdCueExtractor(self.kb),
                RxNormExtractor(self.kb),
            ),
        )

        def signature(number: int):
            return {
                (
                    norm_text(mention.span.text),
                    mention.type.value,
                    mention.candidates,
                    tuple(sorted(value.value for value in mention.assertions)),
                )
                for mention in pipeline.run(read_textref(ROOT / f"data/test/{number}.txt"))
            }

        self.assertEqual(signature(76), signature(83))


class TestMetricSimulator(unittest.TestCase):
    def setUp(self):
        self.record = {
            "text": "aspirin 325mg",
            "type": "THUỐC",
            "candidates": ["A"],
            "assertions": [],
            "position": [0, 13],
            "_provenance": {
                "link_path": "rxnorm_rerank",
                "scores": {"confidence": 0.90, "code:A": 0.90, "code:B": 0.70},
            },
        }

    def test_threshold_reconstructs_candidates_from_provenance(self):
        self.assertEqual(["A"], candidates_at_threshold(self.record, 0.80))
        self.assertEqual([], candidates_at_threshold(self.record, 0.95))

    def test_expected_sweep_labels_proxy_not_gold(self):
        points = sweep(
            {"1.txt": [self.record]},
            [0.80, 0.95],
            exact_accuracy=0.90,
            empty_gold_rate=0.20,
        )
        self.assertTrue(all(point.mode == "expected" for point in points))
        self.assertGreater(points[0].candidate_score, points[1].candidate_score)


if __name__ == "__main__":
    unittest.main(verbosity=2)
