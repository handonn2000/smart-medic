"""Regression tests for the no-training v3 accuracy providers."""

from __future__ import annotations

import json
import sys
import unittest
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.pipeline import Pipeline  # noqa: E402
from smart_medic.retrieval import IcdRetriever  # noqa: E402
from smart_medic.schema import Assertion, ConceptType, Span  # noqa: E402
from smart_medic.score import score_file  # noqa: E402
from smart_medic.stages.assertion import AssertionTagger  # noqa: E402
from smart_medic.stages.clinical import ClinicalSymptomExtractor  # noqa: E402
from smart_medic.stages.extract import (  # noqa: E402
    CompositeExtractor,
    GazetteerExtractor,
    IcdCueExtractor,
    RxNormExtractor,
)
from smart_medic.stages.lab import LabObservationExtractor  # noqa: E402
from smart_medic.textref import build_textref, read_textref  # noqa: E402

KB_DIR = ROOT / "data/kb"


class TestLabObservationExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = LabObservationExtractor()

    def records(self, raw: str):
        return [
            (candidate.type, candidate.span.text, candidate.span.start, candidate.span.end)
            for candidate in self.extractor.extract(build_textref(raw))
        ]

    def test_numeric_lab_pair_includes_unit(self):
        raw = "Xét nghiệm: Glucose máu: 13,2 mmol/l."
        self.assertEqual(
            [
                (ConceptType.TEN_XET_NGHIEM, "Glucose máu", 12, 23),
                (ConceptType.KET_QUA_XET_NGHIEM, "13,2 mmol/l", 25, 36),
            ],
            self.records(raw),
        )

    def test_imaging_qualitative_pair(self):
        raw = "Chụp CT sọ não kết quả âm tính."
        self.assertEqual(
            [
                (ConceptType.TEN_XET_NGHIEM, "Chụp CT sọ não", 0, 14),
                (ConceptType.KET_QUA_XET_NGHIEM, "âm tính", 23, 30),
            ],
            self.records(raw),
        )

    def test_result_before_test_name(self):
        raw = "âm tính cấy máu"
        self.assertEqual(
            [
                (ConceptType.KET_QUA_XET_NGHIEM, "âm tính", 0, 7),
                (ConceptType.TEN_XET_NGHIEM, "cấy máu", 8, 15),
            ],
            self.records(raw),
        )

    def test_parenthetical_test_name_is_one_long_span_in_pipeline(self):
        raw = "HGB (Hemoglobin): 92 g/L"
        candidates = self.extractor.extract(build_textref(raw))
        outer = next(item for item in candidates if item.span.start == 0)
        self.assertEqual("HGB (Hemoglobin)", outer.span.text)

    def test_drug_glucose_is_not_lab(self):
        raw = "Glucose 5% x 1000ml truyền tĩnh mạch."
        self.assertEqual([], self.records(raw))

    def test_disease_and_prose_false_pairs_are_rejected(self):
        self.assertEqual([], self.records("Tăng huyết áp nguyên phát."))
        self.assertEqual([], self.records("protein amyloid ngoài tế bào tăng."))

    def test_nfd_offsets_round_trip_to_raw(self):
        raw = unicodedata.normalize("NFD", "Xét nghiệm: Glucose máu: 13,2 mmol/l.")
        candidates = self.extractor.extract(build_textref(raw))
        self.assertEqual(2, len(candidates))
        for candidate in candidates:
            self.assertTrue(candidate.span.verify(raw))


class TestClinicalV3(unittest.TestCase):
    def test_colloquial_symptoms_are_discovered_with_raw_offsets(self):
        raw = "Bệnh nhân đi tiêu ra máu, đau bụng và buồn nôn."
        candidates = ClinicalSymptomExtractor().extract(build_textref(raw))
        self.assertEqual(
            ["đi tiêu ra máu", "đau bụng", "buồn nôn"],
            [candidate.span.text for candidate in candidates],
        )
        self.assertTrue(all(candidate.span.verify(raw) for candidate in candidates))

    def test_high_frequency_non_symptom_phrases_are_rejected(self):
        raw = "Thuốc hạ sốt phù hợp. - ho Bệnh bạch cầu dòng tủy."
        self.assertEqual([], ClinicalSymptomExtractor().extract(build_textref(raw)))

    def test_negation_scope_covers_coordinated_list_but_not_new_line(self):
        raw = "Không có khó thở, đau bụng và buồn nôn"
        tref = build_textref(raw)
        candidates = ClinicalSymptomExtractor().extract(tref)
        tagged = {
            candidate.span.text: AssertionTagger(tref).tag(candidate.span, candidate.type)[0]
            for candidate in candidates
        }
        self.assertTrue(all(Assertion.NEGATED in flags for flags in tagged.values()))

        raw = "Không sốt\nĐau bụng"
        tref = build_textref(raw)
        pain = next(
            candidate for candidate in ClinicalSymptomExtractor().extract(tref)
            if candidate.span.text == "Đau bụng"
        )
        self.assertNotIn(
            Assertion.NEGATED,
            AssertionTagger(tref).tag(pain.span, pain.type)[0],
        )

    def test_post_negation_is_supported(self):
        raw = "Cúm âm tính"
        span = Span(0, 3, "Cúm")
        flags, _ = AssertionTagger(build_textref(raw)).tag(span, ConceptType.CHAN_DOAN)
        self.assertIn(Assertion.NEGATED, flags)

    def test_qa_answer_ends_pre_admission_medication_section(self):
        raw = (
            "Thuốc trước khi nhập viện: aspirin\n"
            "Câu trả lời của bác sĩ: Bệnh nhân béo phì."
        )
        tref = build_textref(raw)
        start = raw.index("béo phì")
        span = Span(start, start + len("béo phì"), "béo phì")
        flags, _ = AssertionTagger(tref).tag(span, ConceptType.CHAN_DOAN)
        self.assertNotIn(Assertion.HISTORICAL, flags)

    def test_negation_does_not_leak_into_conditional_consequence(self):
        raw = "Nếu không điều trị kịp thời, bệnh có thể gây suy tim."
        tref = build_textref(raw)
        start = raw.index("suy tim")
        span = Span(start, start + len("suy tim"), "suy tim")
        flags, _ = AssertionTagger(tref).tag(span, ConceptType.CHAN_DOAN)
        self.assertNotIn(Assertion.NEGATED, flags)

    def test_negation_stops_at_exception_and_new_action(self):
        cases = (
            ("Phủ nhận bệnh nền ngoại trừ nhiễm trùng gần đây.", "nhiễm trùng"),
            ("Không dùng đều, bắt đầu dùng suboxone hôm qua.", "suboxone"),
        )
        for raw, text in cases:
            with self.subTest(raw=raw):
                tref = build_textref(raw)
                start = raw.index(text)
                span = Span(start, start + len(text), text)
                flags, _ = AssertionTagger(tref).tag(span, ConceptType.THUOC)
                self.assertNotIn(Assertion.NEGATED, flags)


@unittest.skipUnless((KB_DIR / "icd10_aliases.csv.gz").exists(), "chưa build KB")
class TestV3Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load_kb(KB_DIR)
        cls.pipeline = Pipeline(
            cls.kb,
            CompositeExtractor(
                GazetteerExtractor(cls.kb, contextual_ambiguity=True),
                IcdCueExtractor(cls.kb),
                RxNormExtractor(cls.kb, contextual_analytes=True),
                ClinicalSymptomExtractor(),
                LabObservationExtractor(),
                name="v3_composite",
            ),
        )

    def test_corpus_derived_icd_rewrites(self):
        retriever = IcdRetriever(self.kb)
        expected = {
            "cao huyết áp": "I10",
            "tiểu đường type 2": "E11",
            "tiểu đường type 1": "E10",
            "xuất huyết tiêu hóa": "K92.2",
            "bàn chân bẹt": "Q66.5",
        }
        for phrase, code in expected.items():
            with self.subTest(phrase=phrase):
                ranked = retriever.retrieve(phrase)
                self.assertTrue(ranked)
                self.assertEqual(code, ranked[0].code)

    def test_corpus_derived_diagnoses_return_one_specific_code(self):
        expected = {
            "Bị cao huyết áp.": "I10",
            "Bị tiểu đường type 2.": "E11",
            "Chẩn đoán viêm bao tử.": "K29.7",
            "Theo dõi xuất huyết tiêu hóa.": "K92.2",
            "Khám bàn chân bẹt.": "Q66.5",
        }
        for raw, code in expected.items():
            with self.subTest(raw=raw):
                mentions = self.pipeline.run(build_textref(raw))
                diagnosis = next(
                    mention for mention in mentions if mention.type is ConceptType.CHAN_DOAN
                )
                self.assertEqual((code,), diagnosis.candidates)

    def test_contextual_hierarchy_prefers_parent_unless_unspecified(self):
        resolve = GazetteerExtractor._resolve_hierarchy
        self.assertEqual(("L50",), resolve(("L50", "L50.8"), "mày đay"))
        self.assertEqual(
            ("L50.8",),
            resolve(("L50", "L50.8"), "mày đay không đặc hiệu"),
        )

    def test_three_character_mask_is_not_lost(self):
        candidates = RxNormExtractor(self.kb).extract(build_textref("Dùng *** theo chỉ định."))
        self.assertEqual(1, len(candidates))
        self.assertEqual("***", candidates[0].span.text)
        self.assertEqual("masked_unresolved", candidates[0].provenance.link_path)

    def test_glucose_infusion_is_drug_not_lab(self):
        raw = "Glucose 5% x 1000ml truyền tĩnh mạch."
        mentions = self.pipeline.run(build_textref(raw))
        self.assertEqual(1, len(mentions))
        self.assertEqual(ConceptType.THUOC, mentions[0].type)
        self.assertEqual("Glucose 5% x 1000ml truyền tĩnh mạch", mentions[0].span.text)
        self.assertEqual(("1795612",), mentions[0].candidates)

    def test_curated_v3_metric_fixture_is_exact(self):
        fixture = ROOT / "tests/fixtures/v3_metric"
        rows = []
        for source in sorted((fixture / "input").glob("*.txt")):
            tref = read_textref(source)
            predicted = [mention.to_dict() for mention in self.pipeline.run(tref)]
            gold = json.loads(
                (fixture / "gold" / f"{source.stem}.json").read_text(encoding="utf-8")
            )
            rows.append(score_file(gold, predicted))
        self.assertTrue(rows)
        for component in ("text", "assertions", "candidates"):
            self.assertTrue(all(row[component] == 1.0 for row in rows), component)

    def test_top_near_duplicate_pairs_have_consistent_shared_lines(self):
        """Audit the six strongest measured duplicate pairs, including NFD/NFC."""

        def line_signatures(number: int):
            tref = read_textref(ROOT / f"data/test/{number}.txt")
            mentions = self.pipeline.run(tref)
            result: dict[str, list[set[tuple]]] = {}
            start = 0
            for line in tref.raw.splitlines(keepends=True):
                end = start + len(line)
                key = norm_text(line)
                if len(key) >= 15:
                    signature = {
                        (
                            norm_text(mention.span.text),
                            mention.type.value,
                            mention.candidates,
                            tuple(sorted(item.value for item in mention.assertions)),
                        )
                        for mention in mentions
                        if start <= mention.span.start and mention.span.end <= end
                    }
                    result.setdefault(key, []).append(signature)
                start = end
            return result

        cache = {}
        for left, right in ((86, 94), (76, 83), (75, 84), (67, 94), (7, 9), (13, 16)):
            for number in (left, right):
                cache.setdefault(number, line_signatures(number))
            a, b = cache[left], cache[right]
            shared = {
                key for key in a.keys() & b.keys()
                if len(a[key]) == len(b[key]) == 1
            }
            with self.subTest(pair=(left, right)):
                self.assertTrue(shared)
                self.assertTrue(all(a[key][0] == b[key][0] for key in shared))


if __name__ == "__main__":
    unittest.main(verbosity=2)
