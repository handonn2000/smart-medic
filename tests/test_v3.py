"""Regression tests for the no-training v3 accuracy providers."""

from __future__ import annotations

import json
import sys
import unittest
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.batch import CrossDocumentMaskResolver  # noqa: E402
from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.pipeline import (  # noqa: E402
    Pipeline,
    PipelineConfig,
    select_candidate_set,
)
from smart_medic.retrieval import IcdRetriever  # noqa: E402
from smart_medic.schema import (  # noqa: E402
    Assertion,
    ConceptType,
    Mention,
    Provenance,
    Span,
)
from smart_medic.score import score_file  # noqa: E402
from smart_medic.stages.assertion import AssertionTagger  # noqa: E402
from smart_medic.stages.clinical import ClinicalSymptomExtractor  # noqa: E402
from smart_medic.stages.extract import (  # noqa: E402
    SYMPTOM_CHAPTER_TYPE_CONFIDENCE,
    Candidate,
    CompositeExtractor,
    GazetteerExtractor,
    IcdCueExtractor,
    RxNormExtractor,
)
from smart_medic.stages.lab import LabObservationExtractor  # noqa: E402
from smart_medic.textref import build_textref, read_textref  # noqa: E402

KB_DIR = ROOT / "data/kb"

OFFICIAL_CLINICAL_EXAMPLE = (
    "Bệnh nhân bị bệnh 1 tuần nay, ho đờm xanh, tức ngực, đau thượng vị, "
    "ợ hơi, được chẩn đoán mắc bệnh trào ngược dạ dày – thực quản."
)

OFFICIAL_MEDICATION_EXAMPLE = (
    "Danh sách thuốc trước nhập viện chính xác và đầy đủ. "
    "1. amlodipine 10 mg po daily "
    "2. aspirin 81 mg po daily "
    "3. metoprolol succinate xl 50 mg po daily "
    "4. guaifenesin ml po q6h:prn điều trị ho "
    "5. nystatin oral suspension 5 ml po qid:prn điều trị nấm "
    "6. acetaminophen 325-650 mg po q6h:prn điều trị sốt đau "
    "7. pravastatin 40 mg po daily "
    "8. docusate sodium 100 mg po bid điều trị táo bón "
    "9. senna 8.6 mg po bid:prn điều trị táo bón "
    "10. clonazepam 0.5 mg po qam:prn điều trị lo âu "
    "11. clonazepam 1.5 mg po qhs điều trị âu mất ngủ"
)


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

    def test_official_lyph_alias_and_parenthetical_span(self):
        raw = "LYPH% (Tỷ lệ bạch cầu lympho):12,8"
        self.assertEqual(
            [
                (
                    ConceptType.TEN_XET_NGHIEM,
                    "LYPH% (Tỷ lệ bạch cầu lympho)",
                    0,
                    29,
                ),
                (ConceptType.KET_QUA_XET_NGHIEM, "12,8", 30, 34),
            ],
            self.records(raw),
        )

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

    def test_official_clinical_example_contract(self):
        mentions = self.pipeline.run(build_textref(OFFICIAL_CLINICAL_EXAMPLE))
        symptoms = [
            mention.span.text
            for mention in mentions
            if mention.type is ConceptType.TRIEU_CHUNG
        ]
        self.assertEqual(
            ["ho đờm xanh", "tức ngực", "đau thượng vị", "ợ hơi"],
            symptoms,
        )
        diagnosis = next(
            mention for mention in mentions
            if mention.span.text == "bệnh trào ngược dạ dày – thực quản"
        )
        self.assertEqual(ConceptType.CHAN_DOAN, diagnosis.type)
        self.assertEqual(("K21.0", "K21.9"), diagnosis.candidates)

    def test_official_medication_regimen_contract(self):
        mentions = self.pipeline.run(build_textref(OFFICIAL_MEDICATION_EXAMPLE))
        by_text = {mention.span.text: mention for mention in mentions}
        expected_drugs = {
            "amlodipine 10 mg po daily": "308135",
            "aspirin 81 mg po daily": "243670",
            "metoprolol succinate xl 50 mg po daily": "866436",
            "clonazepam 1.5 mg po qhs": "197528",
        }
        for text, code in expected_drugs.items():
            with self.subTest(text=text):
                mention = by_text[text]
                self.assertEqual(ConceptType.THUOC, mention.type)
                self.assertEqual((code,), mention.candidates)
                self.assertIn(Assertion.HISTORICAL, mention.assertions)
                self.assertTrue(mention.span.verify(OFFICIAL_MEDICATION_EXAMPLE))

        for symptom in ("táo bón", "lo âu", "mất ngủ"):
            with self.subTest(symptom=symptom):
                matching = [
                    mention for mention in mentions if mention.span.text == symptom
                ]
                self.assertTrue(matching)
                self.assertTrue(all(
                    mention.type is ConceptType.TRIEU_CHUNG
                    and not mention.candidates
                    and not mention.assertions
                    for mention in matching
                ))

    def test_generic_anatomy_and_procedure_are_not_diagnoses(self):
        raw = (
            "Siêu âm bàng quang. Tác dụng phụ của thuốc. "
            "Tiến hành chọc dò dịch não tủy."
        )
        mentions = self.pipeline.run(build_textref(raw))
        self.assertFalse(any(
            mention.type is ConceptType.CHAN_DOAN for mention in mentions
        ))
        self.assertTrue(any(
            mention.type is ConceptType.TEN_XET_NGHIEM
            and mention.span.text == "chọc dò dịch não tủy"
            for mention in mentions
        ))

    def test_context_gate_prefers_specific_diagnosis_spans(self):
        raw = (
            "Chẩn đoán viêm tủy xương và nhiễm khuẩn đường tiết niệu. "
            "Khám thấy phù gai thị. Siêu âm tuyến tiền liệt. "
            "Tiếp tục thuốc chống đông máu."
        )
        mentions = self.pipeline.run(build_textref(raw))
        diagnoses = {
            mention.span.text: mention.candidates
            for mention in mentions
            if mention.type is ConceptType.CHAN_DOAN
        }
        self.assertEqual(("M86",), diagnoses["viêm tủy xương"])
        self.assertEqual(
            ("N39.0",), diagnoses["nhiễm khuẩn đường tiết niệu"]
        )
        self.assertEqual(("H47.1",), diagnoses["phù gai thị"])
        self.assertNotIn("viêm tủy", diagnoses)
        self.assertNotIn("nhiễm khuẩn", diagnoses)
        self.assertNotIn("tuyến tiền liệt", diagnoses)
        self.assertNotIn("chống đông máu", diagnoses)

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

    def test_bare_drug_mentions_fall_back_to_exact_anchor(self):
        """A bare ingredient/brand links to its IN/BN, never to ()."""
        extractor = RxNormExtractor(self.kb)
        for text, code, tty in (
            ("Bệnh nhân uống omeprazole mỗi sáng.", "7646", "IN"),
            ("Được cho tylenol khi sốt.", "202433", "BN"),
            ("Dùng thuốc doxycycline.", "3640", "IN"),
        ):
            with self.subTest(mention=text):
                candidates = [
                    c for c in extractor.extract(build_textref(text)) if c.type is ConceptType.THUOC
                ]
                self.assertEqual(1, len(candidates))
                self.assertEqual((code,), candidates[0].codes)
                self.assertEqual(tty, candidates[0].provenance.evidence["anchor_tty"])
                # Every emitted code must still trace back to a KB row.
                self.assertIn(f"rx-anchor:{code}", candidates[0].provenance.kb_rows)

    def test_anchor_fallback_bypasses_the_retrieval_threshold(self):
        """The fallback survives the pipeline filter, like gazetteer_exact."""
        raw = "Bệnh nhân uống omeprazole mỗi sáng."
        extractor = RxNormExtractor(self.kb)
        pipe = Pipeline(self.kb, extractor, PipelineConfig(candidate_threshold=0.99))
        drugs = [m for m in pipe.run(build_textref(raw)) if m.type is ConceptType.THUOC]
        self.assertEqual([("7646",)], [m.candidates for m in drugs])

    def test_analytes_never_gain_a_fallback_code(self):
        """The fallback must not turn lab analytes into drugs."""
        raw = "Xét nghiệm: glucose 5.6 mmol/L, creatinine 88 umol/L, albumin 40 g/L."
        candidates = RxNormExtractor(self.kb).extract(build_textref(raw))
        self.assertEqual([], [c.span.text for c in candidates])

    def test_masked_token_still_abstains_under_the_fallback(self):
        """A ``*****`` has no anchor, so there is nothing to fall back to."""
        candidates = RxNormExtractor(self.kb).extract(
            build_textref("Bệnh nhân uống ***** mỗi tối.")
        )
        self.assertEqual(1, len(candidates))
        self.assertEqual((), candidates[0].codes)
        self.assertEqual("masked_unresolved", candidates[0].provenance.link_path)

    def test_three_character_mask_is_not_lost(self):
        candidates = RxNormExtractor(self.kb).extract(build_textref("Dùng *** theo chỉ định."))
        self.assertEqual(1, len(candidates))
        self.assertEqual("***", candidates[0].span.text)
        self.assertEqual("masked_unresolved", candidates[0].provenance.link_path)

    def test_preposed_dose_is_local_and_part_of_drug_span(self):
        raw = (
            "Bệnh nhân dùng 80mg po lasix ở nhà\n"
            "Nhận 80mg lasix iv\n"
            "Được cho po metoprolol"
        )
        candidates = RxNormExtractor(self.kb).extract(build_textref(raw))
        by_text = {candidate.span.text: candidate for candidate in candidates}
        # Oral route + strength agree with a product → SCD.
        self.assertEqual(("205732",), by_text["80mg po lasix"].codes)
        # IV route conflicts with the oral products, and ``po metoprolol`` has
        # no strength at all.  Neither may be given a product code — but both
        # fall back to their exact brand/ingredient anchor rather than to ().
        for text, code, tty in (
            ("80mg lasix iv", "202991", "BN"),      # Lasix
            ("po metoprolol", "6918", "IN"),        # metoprolol
        ):
            with self.subTest(mention=text):
                self.assertEqual((code,), by_text[text].codes)
                self.assertEqual(tty, by_text[text].provenance.evidence["anchor_tty"])
                self.assertEqual(
                    "rxnorm_anchor_exact", by_text[text].provenance.link_path
                )

    def test_structured_brand_regimen_links_exact_product(self):
        raw = (
            "Medrol 16mg x 3 viên, uống 8h sáng\n"
            "Zestril 10mg x 1 viên, uống sáng\n"
            "coumadin 3.0 mg /ngày"
        )
        candidates = RxNormExtractor(self.kb).extract(build_textref(raw))
        by_text = {candidate.span.text: candidate.codes for candidate in candidates}
        self.assertEqual(
            ("207138",), by_text["Medrol 16mg x 3 viên, uống 8h sáng"]
        )
        self.assertEqual(
            ("104377",), by_text["Zestril 10mg x 1 viên, uống sáng"]
        )
        self.assertEqual(("855320",), by_text["coumadin 3.0 mg /ngày"])

    def test_masked_regimen_never_crosses_a_line_boundary(self):
        raw = "Dùng **************\nTiêm thuốc khác"
        candidate = RxNormExtractor(self.kb).extract(build_textref(raw))[0]
        self.assertEqual("**************", candidate.span.text)
        self.assertTrue(candidate.span.verify(raw))

    def test_cross_document_mask_resolution_requires_unique_template(self):
        visible_text = "Thuốc: aspirin 81 mg po daily"
        masked_text = "Thuốc: ******** 81 mg po daily"
        visible_tref = build_textref(visible_text)
        masked_tref = build_textref(masked_text)
        visible = self.pipeline.run(visible_tref)
        masked = self.pipeline.run(masked_tref)
        target = next(mention for mention in masked if "*" in mention.span.text)
        self.assertFalse(target.candidates)

        stats = CrossDocumentMaskResolver().resolve({
            "visible.txt": (visible_tref, visible),
            "masked.txt": (masked_tref, masked),
        })
        self.assertEqual(1, stats.resolved)
        self.assertEqual(("243670",), target.candidates)
        self.assertEqual(
            "masked_cross_document_template", target.provenance.link_path
        )

        conflicting = Mention(
            span=Span(7, len(visible_text), visible_text[7:]),
            type=ConceptType.THUOC,
            candidates=("conflict",),
            provenance=Provenance(
                kb_rows=["test:conflict"],
                scores={"confidence": 1.0, "code:conflict": 1.0},
                evidence={"anchor": "aspirin"},
            ),
        )
        fresh_masked = self.pipeline.run(masked_tref)
        unresolved = next(
            mention for mention in fresh_masked if "*" in mention.span.text
        )
        conflict_stats = CrossDocumentMaskResolver().resolve({
            "visible.txt": (visible_tref, visible),
            "conflict.txt": (visible_tref, [conflicting]),
            "masked.txt": (masked_tref, fresh_masked),
        })
        self.assertEqual(0, conflict_stats.resolved)
        self.assertGreaterEqual(conflict_stats.conflicts, 1)
        self.assertFalse(unresolved.candidates)

    def test_rxnorm_output_modes_are_traceable(self):
        current = "1665021"
        legacy = self.kb.remap_reverse[current][0]

        class FixedDrugExtractor:
            name = "fixed_drug"

            @staticmethod
            def extract(tref):
                return [Candidate(
                    Span(0, len(tref.raw), tref.raw),
                    ConceptType.THUOC,
                    (current,),
                    Provenance(
                        link_path="rxnorm_rerank",
                        kb_rows=[f"rx:{current}"],
                        scores={"confidence": 1.0, f"code:{current}": 1.0},
                    ),
                )]

        tref = build_textref("fixed drug")
        expected = {
            "current": (current,),
            "legacy": (legacy,),
            "both": (current, legacy),
        }
        for mode, codes in expected.items():
            with self.subTest(mode=mode):
                mention = Pipeline(
                    self.kb,
                    FixedDrugExtractor(),
                    PipelineConfig(rxnorm_output_mode=mode),
                ).run(tref)[0]
                self.assertEqual(codes, mention.candidates)
                if mode != "current":
                    self.assertIn(
                        f"rx-remap:{legacy}->{current}", mention.provenance.kb_rows
                    )
                if mode == "legacy":
                    self.assertNotIn(
                        f"code:{current}", mention.provenance.scores
                    )

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


class _StubKB:
    """KB tối thiểu: tầng quyết định chỉ chạm tới remap khi đổi output mode."""

    remap_reverse: dict[str, list[str]] = {}


class _FixedExtractor:
    """Phát đúng một mention đã dựng sẵn — để cô lập tầng quyết định."""

    name = "fixed"

    def __init__(self, ctype, codes, scores, *, link_path, type_confidence=1.0):
        self.ctype = ctype
        self.codes = codes
        self.scores = scores
        self.link_path = link_path
        self.type_confidence = type_confidence

    def extract(self, tref):
        return [Candidate(
            Span(0, len(tref.raw), tref.raw),
            self.ctype,
            self.codes,
            Provenance(
                extractor=self.name,
                link_path=self.link_path,
                kb_rows=[f"icd:{code}" for code in self.codes],
                scores=self.scores,
                type_confidence=self.type_confidence,
            ),
        )]


class TestCandidateDecisionLayer(unittest.TestCase):
    """§1.5 + §2.5 báo cáo v4: bỏ trống theo TYPE, kích thước tập suy ra."""

    def run_fixed(self, extractor, cfg=None):
        pipeline = Pipeline(_StubKB(), extractor, cfg or PipelineConfig())
        return pipeline.run(build_textref("một mention"))[0]

    def test_abstention_floor_is_derived_from_a1(self):
        self.assertAlmostEqual(2 / 3, PipelineConfig().min_type_confidence)
        self.assertAlmostEqual(
            0.5, PipelineConfig(a1_top1_accuracy=1.0).min_type_confidence
        )
        # Sàn cứng chỉ siết chặt được, không nới ra.
        self.assertAlmostEqual(
            0.9, PipelineConfig(type_confidence_floor=0.9).min_type_confidence
        )
        self.assertAlmostEqual(
            2 / 3, PipelineConfig(type_confidence_floor=0.1).min_type_confidence
        )

    def test_low_retrieval_score_alone_never_abstains(self):
        """Điểm rerank thấp KHÔNG được làm ta bỏ trống: J(∅) = 0 tuyệt đối."""
        mention = self.run_fixed(
            _FixedExtractor(
                ConceptType.CHAN_DOAN,
                ("J18.9",),
                {"confidence": 0.11, "code:J18.9": 0.11},
                link_path="icd_lexical_retrieval|rerank",
            ),
            PipelineConfig(candidate_threshold=0.99),
        )
        self.assertEqual(("J18.9",), mention.candidates)
        self.assertNotIn("abstained", mention.provenance.link_path)

    def test_low_type_confidence_abstains_even_with_a_perfect_score(self):
        mention = self.run_fixed(_FixedExtractor(
            ConceptType.CHAN_DOAN,
            ("R06.0",),
            {"confidence": 1.0, "code:R06.0": 1.0},
            link_path="icd_lexical_retrieval|rerank",
            type_confidence=SYMPTOM_CHAPTER_TYPE_CONFIDENCE,
        ))
        self.assertEqual((), mention.candidates)
        self.assertIn("abstained_low_type_confidence", mention.provenance.link_path)

    def test_abstention_also_applies_to_exact_link_paths(self):
        """Bypass của gazetteer_exact là bypass NGƯỠNG ĐIỂM, không phải p_t."""
        mention = self.run_fixed(_FixedExtractor(
            ConceptType.CHAN_DOAN,
            ("R51",),
            {"confidence": 1.0},
            link_path="gazetteer_exact",
            type_confidence=SYMPTOM_CHAPTER_TYPE_CONFIDENCE,
        ))
        self.assertEqual((), mention.candidates)

    def test_single_code_unless_gold_plausibly_lists_two(self):
        tied = {"confidence": 1.0}
        cases = (
            # Anh em cùng cha + hòa điểm → gold có thể liệt kê cả hai (K21).
            (("K21.0", "K21.9"), tied, ("K21.0", "K21.9")),
            (("K29.6", "K29.7"), tied, ("K29.6", "K29.7")),
            # Cha/con ruột: đó là lựa chọn độ đặc hiệu, gold chỉ lấy một.
            (("I60", "I60.8"), tied, ("I60",)),
            # Anh em nhưng KHÔNG hòa điểm → E[J] cực đại tại k = 1.
            (
                ("K21.0", "K21.9"),
                {"confidence": 0.9, "code:K21.0": 0.9, "code:K21.9": 0.7},
                ("K21.0",),
            ),
            # Mã RxNorm không có phân cấp → không bao giờ là cặp.
            (("2374360", "250651"), tied, ("2374360",)),
        )
        for codes, scores, expected in cases:
            with self.subTest(codes=codes):
                decision = select_candidate_set(
                    codes, scores=scores, link_path="gazetteer_exact"
                )
                self.assertEqual(expected, decision.codes)
                self.assertFalse(decision.abstained)
                self.assertEqual(len(codes) - len(expected), decision.dropped)

    def test_ambiguity_margin_is_the_derived_q_ratio(self):
        """``q/(1−q) > p₁ − p₂`` — margin 0 nghĩa là đòi hòa điểm tuyệt đối."""
        scores = {"code:K21.0": 0.90, "code:K21.9": 0.86}
        self.assertEqual(
            ("K21.0",),
            select_candidate_set(
                ("K21.0", "K21.9"), scores=scores, link_path="gazetteer_exact"
            ).codes,
        )
        self.assertEqual(
            ("K21.0", "K21.9"),
            select_candidate_set(
                ("K21.0", "K21.9"),
                scores=scores,
                link_path="gazetteer_exact",
                ambiguity_margin=0.05,
            ).codes,
        )

    def test_tied_order_follows_the_kb_and_is_deterministic(self):
        for _ in range(3):
            self.assertEqual(
                ("K21.9", "K21.0"),
                select_candidate_set(
                    ("K21.9", "K21.0"),
                    scores={"confidence": 1.0},
                    link_path="gazetteer_exact",
                ).codes,
            )

    def test_stats_separate_abstention_from_set_truncation(self):
        from smart_medic.pipeline import RunStats

        stats = RunStats()
        Pipeline(_StubKB(), _FixedExtractor(
            ConceptType.CHAN_DOAN,
            ("R51",),
            {"confidence": 1.0},
            link_path="gazetteer_exact",
            type_confidence=SYMPTOM_CHAPTER_TYPE_CONFIDENCE,
        )).run(build_textref("đau đầu"), stats)
        self.assertEqual(1, stats.dropped_type_confidence)
        self.assertEqual(0, stats.dropped_threshold)

        stats = RunStats()
        Pipeline(_StubKB(), _FixedExtractor(
            ConceptType.CHAN_DOAN,
            ("I60", "I60.8", "I60.9"),
            {"confidence": 1.0},
            link_path="gazetteer_exact",
        )).run(build_textref("xuất huyết"), stats)
        self.assertEqual(0, stats.dropped_type_confidence)
        self.assertEqual(2, stats.dropped_threshold)


@unittest.skipUnless((KB_DIR / "icd10_aliases.csv.gz").exists(), "chưa build KB")
class TestSymptomChapterTypePrior(unittest.TestCase):
    """Chương R là TIÊN NGHIỆM VỀ TYPE, không phải blocklist."""

    @classmethod
    def setUpClass(cls):
        cls.kb = load_kb(KB_DIR)

    def test_chapter_r_gazetteer_hit_records_the_prior(self):
        candidates = GazetteerExtractor(self.kb).extract(
            build_textref("Bệnh nhân khó thở nhiều.")
        )
        match = next(c for c in candidates if c.span.text == "khó thở")
        self.assertIs(ConceptType.TRIEU_CHUNG, match.type)
        self.assertEqual((), match.codes)
        self.assertEqual(
            SYMPTOM_CHAPTER_TYPE_CONFIDENCE, match.provenance.type_confidence
        )
        self.assertEqual("icd_chapter_r", match.provenance.evidence["type_prior"])
        # Chính con số đó phải nằm dưới ngưỡng phát mã.
        self.assertLess(
            match.provenance.type_confidence,
            PipelineConfig().min_type_confidence,
        )

    def test_cue_retrieval_keeps_the_mention_and_retypes_it(self):
        """Trước đây chương R bị ``continue`` — mất luôn mention lẫn recall."""
        extractor = IcdCueExtractor(self.kb)
        ranked = extractor.retriever.retrieve("chóng mặt và choáng váng")
        self.assertTrue(ranked)
        candidate = extractor._typed_candidate(
            Span(0, 7, "sốt cao"),
            ("R50.9",),
            Provenance(link_path="icd_lexical_retrieval|rerank", kb_rows=["icd:R50.9"]),
            "R50.9",
        )
        self.assertIs(ConceptType.TRIEU_CHUNG, candidate.type)
        self.assertEqual((), candidate.codes)
        self.assertIn("symptom_chapter_prior", candidate.provenance.link_path)
        self.assertEqual(["icd:R50.9"], candidate.provenance.kb_rows)

    def test_non_symptom_chapter_keeps_full_type_confidence(self):
        candidates = GazetteerExtractor(self.kb).extract(
            build_textref("Chẩn đoán viêm phổi.")
        )
        match = next(c for c in candidates if c.type is ConceptType.CHAN_DOAN)
        self.assertEqual(1.0, match.provenance.type_confidence)
        self.assertGreaterEqual(
            match.provenance.type_confidence,
            PipelineConfig().min_type_confidence,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
