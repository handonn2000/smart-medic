"""Test suite v0 — chỉ dùng thư viện chuẩn (unittest), không cần pytest.

    python -m unittest discover -s tests -v

Bốn nhóm test tương ứng bốn lỗi âm thầm đã đo được trên corpus. Đây không phải
test cho có: mỗi nhóm chặn một lỗi đã thực sự xảy ra hoặc đã được chứng minh là
sẽ xảy ra.
"""

from __future__ import annotations

import json
import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.normalize import NORMALIZER_VERSION, norm_text  # noqa: E402
from smart_medic.schema import (  # noqa: E402
    ASSERTABLE,
    MAPPABLE,
    Assertion,
    ConceptType,
    DiagnosisMention,
    Mention,
    Span,
    validate_record,
)
from smart_medic.stages.assertion import SectionMap  # noqa: E402
from smart_medic.stages.locate import Locator  # noqa: E402
from smart_medic.textref import build_textref, read_textref  # noqa: E402

TEST_DIR = ROOT / "data/test"
OUT_DIR = ROOT / "data/output"
KB_DIR = ROOT / "data/kb"

#: 20 file lưu ở dạng NFD — nguồn lỗi offset âm thầm.
NFD_FILES = [13, 14, 16, 17, 19, 20, 28, 34, 35, 42,
             52, 54, 56, 67, 72, 81, 86, 94, 97, 100]


def corpus() -> list[Path]:
    return sorted(TEST_DIR.glob("*.txt"), key=lambda p: int(p.stem))


# ══ 1. Normalizer: một nguồn sự thật duy nhất ════════════════════════════════


class TestNormalizerAgreement(unittest.TestCase):
    """build_textref(s).norm PHẢI bằng norm_text(s).

    Đây là cách cưỡng chế nguyên tắc "một mẩu code normalize duy nhất". Nếu hai
    đường đi lệch nhau thì alias trong KB và mention lúc chạy sẽ chuẩn hóa khác
    nhau, không bao giờ khớp, và KHÔNG có exception nào được ném.
    """

    CASES = [
        "Suy tim, không đặc hiệu",
        "trào ngược dạ dày – thực quản",
        "  nhiều   khoảng\ttrắng \n ",
        "VIẾT HOA Có Dấu",
        "",
        "a",
        "\n\n\n",
        "Thiếu men G6PD (Glucose-6-Phosphate Dehydrogenase)",
    ]

    def test_synthetic(self):
        for s in self.CASES:
            with self.subTest(s=s[:30]):
                self.assertEqual(build_textref(s).norm, norm_text(s))

    def test_nfd_and_nfc_variants(self):
        for s in self.CASES:
            for form in ("NFC", "NFD"):
                v = unicodedata.normalize(form, s)
                with self.subTest(form=form, s=s[:24]):
                    self.assertEqual(build_textref(v).norm, norm_text(v))

    def test_whole_corpus(self):
        files = corpus()
        self.assertTrue(files, f"không thấy corpus ở {TEST_DIR}")
        for p in files:
            raw = p.read_text(encoding="utf-8")
            with self.subTest(file=p.name):
                self.assertEqual(build_textref(raw).norm, norm_text(raw))

    def test_nfd_and_nfc_give_same_norm(self):
        """Cùng nội dung, khác cách lưu Unicode → norm phải giống hệt."""
        for p in corpus()[:20]:
            raw = p.read_text(encoding="utf-8")
            a = build_textref(unicodedata.normalize("NFC", raw)).norm
            b = build_textref(unicodedata.normalize("NFD", raw)).norm
            with self.subTest(file=p.name):
                self.assertEqual(a, b)


# ══ 2. Offset map: bất biến raw[start:end] == text ═══════════════════════════


class TestOffsetMap(unittest.TestCase):
    def test_roundtrip_whole_corpus(self):
        """Mọi khoảng norm ánh xạ ngược phải cho đúng đoạn raw tương ứng."""
        for p in corpus():
            tref = read_textref(p)
            n = len(tref.norm)
            for ns in range(0, n - 8, max(1, n // 40)):
                ne = ns + 8
                rs, re_ = tref.to_raw(ns, ne)
                with self.subTest(file=p.name, ns=ns):
                    self.assertLessEqual(rs, re_)
                    self.assertLessEqual(re_, len(tref.raw))
                    self.assertEqual(norm_text(tref.raw[rs:re_]), tref.norm[ns:ne].strip())

    def test_nfd_files_really_are_nfd(self):
        """Xác nhận 20 file NFD vẫn đúng như đo lường — nếu corpus đổi, test đỏ."""
        found = [
            int(p.stem) for p in corpus()
            if unicodedata.normalize("NFC", p.read_text(encoding="utf-8"))
            != p.read_text(encoding="utf-8")
        ]
        self.assertEqual(sorted(found), NFD_FILES)

    def test_file_14_length_gap(self):
        """File 14: raw 2.672 vs NFC 2.538 ký tự — lệch 134."""
        raw = (TEST_DIR / "14.txt").read_text(encoding="utf-8")
        self.assertEqual(len(raw), 2672)
        self.assertEqual(len(unicodedata.normalize("NFC", raw)), 2538)

    def test_locate_on_nfd_files(self):
        """Locator phải tìm được chuỗi NFC trong file lưu NFD."""
        for num in NFD_FILES:
            tref = read_textref(TEST_DIR / f"{num}.txt")
            probe_norm = tref.norm[50:70].strip()
            if len(probe_norm) < 5:
                continue
            span = Locator(tref).locate(probe_norm)
            with self.subTest(file=num):
                self.assertIsNotNone(span, f"không định vị được trong {num}.txt")
                self.assertTrue(span.verify(tref.raw))

    def test_locate_repeated_span_advances_cursor(self):
        """Span lặp lại: mention thứ n khớp lần thứ n, không chồng lấn."""
        tref = build_textref("ho khan và ho khan và ho khan")
        loc = Locator(tref)
        spans = [loc.locate("ho khan") for _ in range(3)]
        self.assertTrue(all(s is not None for s in spans))
        starts = [s.start for s in spans]
        self.assertEqual(len(set(starts)), 3, f"span trùng vị trí: {starts}")
        for a, b in zip(spans, spans[1:]):
            self.assertFalse(a.overlaps(b), "span chồng lấn — con trỏ đẩy sai")

    def test_locate_rejects_absent_text(self):
        tref = build_textref("bệnh nhân ho đờm xanh")
        self.assertIsNone(Locator(tref).locate("viêm phổi thùy dưới phải"))


# ══ 3. Schema: nhãn đầy đủ + candidates rỗng cho non-mappable ════════════════


class TestSchema(unittest.TestCase):
    def test_labels_are_full_with_diacritics(self):
        """Lỗi viết tắt nhãn đã làm hỏng toàn bộ 471 record một lần."""
        self.assertEqual(
            {t.value for t in ConceptType},
            {"TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM",
             "CHẨN_ĐOÁN", "THUỐC"},
        )
        for t in ConceptType:
            self.assertNotIn("_XN", t.value, f"{t.value} là dạng viết tắt")

    def test_mappable_and_assertable_sets(self):
        self.assertEqual(MAPPABLE, {ConceptType.CHAN_DOAN, ConceptType.THUOC})
        self.assertEqual(
            ASSERTABLE,
            {ConceptType.CHAN_DOAN, ConceptType.THUOC, ConceptType.TRIEU_CHUNG},
        )

    def test_candidates_rejected_for_non_mappable(self):
        """Type gate cưỡng chế bằng hệ thống kiểu, không bằng quy ước."""
        span = Span(0, 6, "ho đờm")
        for t in (ConceptType.TRIEU_CHUNG, ConceptType.TEN_XET_NGHIEM,
                  ConceptType.KET_QUA_XET_NGHIEM):
            with self.subTest(type=t.value), self.assertRaises(ValueError):
                Mention(span=span, type=t, candidates=("R06.0",))

    def test_assertions_rejected_for_lab_types(self):
        span = Span(0, 3, "WBC")
        for t in (ConceptType.TEN_XET_NGHIEM, ConceptType.KET_QUA_XET_NGHIEM):
            with self.subTest(type=t.value), self.assertRaises(ValueError):
                Mention(span=span, type=t, assertions=frozenset({Assertion.NEGATED}))

    def test_diagnosis_mention_forces_type(self):
        m = DiagnosisMention(span=Span(0, 7, "suy tim"), candidates=("I50",))
        self.assertIs(m.type, ConceptType.CHAN_DOAN)
        self.assertEqual(m.to_dict()["type"], "CHẨN_ĐOÁN")

    def test_validate_catches_broken_invariant(self):
        raw = "bệnh nhân ho đờm xanh"
        bad = {"text": "ho đờm", "type": "TRIỆU_CHỨNG", "candidates": [],
               "assertions": [], "position": [0, 6]}
        errs = validate_record(bad, raw)
        self.assertTrue(any("BẤT BIẾN VỠ" in e for e in errs), errs)

    def test_validate_catches_abbreviated_label(self):
        rec = {"text": "WBC", "type": "TÊN_XN", "candidates": [],
               "assertions": [], "position": [0, 3]}
        self.assertTrue(any("type không hợp lệ" in e for e in validate_record(rec)))

    def test_json_keeps_vietnamese(self):
        from smart_medic.schema import dumps

        out = dumps([DiagnosisMention(span=Span(0, 7, "suy tim"), candidates=("I50",))])
        self.assertIn("CHẨN_ĐOÁN", out)
        self.assertNotIn("\\u", out)


# ══ 4. Gazetteer + assertion: các bẫy đo được trên corpus ════════════════════


@unittest.skipUnless((KB_DIR / "MANIFEST.json").exists(), "chưa build KB")
class TestGazetteer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from smart_medic.kb.store import load_kb

        cls.kb = load_kb(KB_DIR)

    def test_manifest_normalizer_version_matches(self):
        self.assertEqual(self.kb.manifest["normalizer_version"], NORMALIZER_VERSION)

    def test_longest_match_wins(self):
        """"suy tim" (I50) lồng trong "suy tim, không đặc hiệu" (I50.9)."""
        tref = build_textref("Chẩn đoán: suy tim, không đặc hiệu.")
        hits = self.kb.icd_gaz.scan(tref.norm)
        self.assertTrue(hits, "không khớp gì")
        best = max(hits, key=lambda h: h.ne - h.ns)
        self.assertIn("không đặc hiệu", best.alias)
        self.assertIn("I50.9", best.codes)

    def test_risk_short_aliases_dropped(self):
        """"thận"→D30.0 là tên cắt cụt trong bảng, sai 100% trong corpus."""
        tref = build_textref("Bệnh nhân bị sỏi thận, không ứ nước.")
        aliases = {h.alias for h in self.kb.icd_gaz.scan(tref.norm)}
        self.assertNotIn("thận", aliases)

    def test_symptom_chapter_flagged(self):
        tref = build_textref("Bệnh nhân khó thở nhiều.")
        hits = [h for h in self.kb.icd_gaz.scan(tref.norm) if h.alias == "khó thở"]
        self.assertTrue(hits)
        self.assertTrue(hits[0].is_symptom_chapter, "R06.0 phải là chương triệu chứng")

    def test_scan_matches_never_overlap(self):
        for p in corpus()[:25]:
            tref = read_textref(p)
            hits = self.kb.icd_gaz.scan(tref.norm)
            for a, b in zip(hits, hits[1:]):
                with self.subTest(file=p.name):
                    self.assertLessEqual(a.ne, b.ns, "khớp gazetteer chồng lấn")


class TestAssertionTraps(unittest.TestCase):
    def test_khong_dac_hieu_is_not_negation(self):
        """"không đặc hiệu" là một phần TÊN BỆNH, không phải phủ định.

        2.487 dòng trong bảng ICD chứa cụm này.
        """
        from smart_medic.stages.assertion import AssertionTagger

        tref = build_textref("Chẩn đoán: suy tim, không đặc hiệu ở người cao tuổi")
        tag = AssertionTagger(tref)
        idx = tref.raw.index("suy tim")
        flags, _ = tag.tag(Span(idx, idx + 7, "suy tim"), ConceptType.CHAN_DOAN)
        self.assertNotIn(Assertion.NEGATED, flags)

    def test_real_negation_is_caught(self):
        from smart_medic.stages.assertion import AssertionTagger

        tref = build_textref("Bệnh nhân không sốt, không ho.")
        tag = AssertionTagger(tref)
        idx = tref.raw.index("sốt")
        flags, _ = tag.tag(Span(idx, idx + 3, "sốt"), ConceptType.TRIEU_CHUNG)
        self.assertIn(Assertion.NEGATED, flags)

    def test_family_disabled_by_default(self):
        """Cue "ông " nổ 644 lần nhưng 630 (98%) là mảnh của "kh-ông"."""
        from smart_medic.stages.assertion import AssertionTagger

        tref = build_textref("Bố bệnh nhân có tiền sử đau bụng tương tự.")
        tag = AssertionTagger(tref)
        idx = tref.raw.index("đau bụng")
        flags, _ = tag.tag(Span(idx, idx + 8, "đau bụng"), ConceptType.TRIEU_CHUNG)
        self.assertNotIn(Assertion.FAMILY, flags)

    def test_ong_inside_khong_never_fires(self):
        from smart_medic.stages.assertion import AssertionTagger

        tref = build_textref("Bệnh nhân không đau bụng.")
        tag = AssertionTagger(tref, enable_family=True)
        idx = tref.raw.index("đau bụng")
        flags, _ = tag.tag(Span(idx, idx + 8, "đau bụng"), ConceptType.TRIEU_CHUNG)
        self.assertNotIn(Assertion.FAMILY, flags)

    def test_section_map_finds_history(self):
        sm = SectionMap(norm_text(
            "Tiền sử bệnh: tăng huyết áp, đái tháo đường.\n"
            "Khám bệnh: tỉnh táo, tiếp xúc tốt."
        ))
        self.assertTrue(sm.sections)
        self.assertTrue(any(s.historical for s in sm.sections))
        self.assertTrue(any(not s.historical for s in sm.sections))


# ══ 5. End-to-end: Definition of Done của v0 ═════════════════════════════════


@unittest.skipUnless(OUT_DIR.exists() and list(OUT_DIR.glob("*.json")), "chưa chạy infer")
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = [f for f in sorted(OUT_DIR.glob("*.json"))
                     if f.name not in {"run_manifest.json", "explain.json"}]

    def test_one_output_per_input(self):
        self.assertEqual(len(self.files), len(corpus()))

    def test_every_output_valid_and_position_verified(self):
        """DoD: assert raw[start:end] == entity["text"] cho MỌI entity."""
        total = 0
        for f in self.files:
            raw = (TEST_DIR / f"{f.stem}.txt").read_text(encoding="utf-8")
            recs = json.loads(f.read_text(encoding="utf-8"))
            total += len(recs)
            with self.subTest(file=f.name):
                self.assertEqual([], __import__(
                    "smart_medic.schema", fromlist=["validate_file"]
                ).validate_file(recs, raw))
        self.assertGreater(total, 0, "không sinh được mention nào")

    def test_no_candidates_on_non_mappable(self):
        """DoD: candidates == [] cho mọi type ∉ {CHẨN_ĐOÁN, THUỐC}."""
        allowed = {t.value for t in MAPPABLE}
        for f in self.files:
            for r in json.loads(f.read_text(encoding="utf-8")):
                if r["type"] not in allowed:
                    with self.subTest(file=f.name, text=r["text"]):
                        self.assertEqual([], r["candidates"])

    def test_no_abbreviated_labels_anywhere(self):
        valid = {t.value for t in ConceptType}
        for f in self.files:
            for r in json.loads(f.read_text(encoding="utf-8")):
                self.assertIn(r["type"], valid, f"{f.name}: {r['type']}")

    def test_self_scoring_is_perfect(self):
        """DoD: score.py --pred X --gold X phải ra FINAL_SCORE = 1.0000."""
        from smart_medic.score import score_file

        for f in self.files[:30]:
            recs = json.loads(f.read_text(encoding="utf-8"))
            if not recs:
                continue
            r = score_file(recs, recs)
            with self.subTest(file=f.name):
                self.assertAlmostEqual(r["text"], 1.0, places=6)
                self.assertAlmostEqual(r["assertions"], 1.0, places=6)
                self.assertAlmostEqual(r["candidates"], 1.0, places=6)

    def test_zip_structure(self):
        import zipfile

        z = ROOT / "data/output.zip"
        if not z.exists():
            self.skipTest("chưa đóng gói zip")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        self.assertTrue(all(n.startswith("output/") and n.endswith(".json") for n in names))
        self.assertIn("output/1.json", names)
        self.assertEqual(len(names), len(corpus()))

    def test_run_manifest_present(self):
        man = json.loads((OUT_DIR / "run_manifest.json").read_text(encoding="utf-8"))
        for key in ("git_sha", "normalizer_version", "extractor", "config", "n_files"):
            self.assertIn(key, man)
        self.assertEqual(man["schema_errors"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
