"""Tests cho lớp chuẩn hóa mã candidates.

Mọi ca ICD dưới đây là mã **đã thật sự do LLM trả về** khi dựng gold dev, không
phải ca bịa: 8/136 mã là ICD-10-CM (Mỹ) đặc hiệu hơn một bậc so với danh mục
WHO/Việt Nam trong KB. Khóa chúng lại vì đây là lớp lỗi im lặng — mã sai không
làm gãy schema, nó chỉ lặng lẽ cho Jaccard = 0 ở đúng thành phần trọng số 0.4.

Hai khẳng định quan trọng ngang nhau, và cái thứ hai dễ bị bỏ quên:

* mã hỏng thì được sửa hoặc bị loại;
* mã **đúng thì không được đụng vào** — một tầng "chuẩn hóa" hăng quá sẽ tự tay
  phá gold, và sẽ không ai để ý cho tới lúc điểm tụt.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.kb.store import load_kb  # noqa: E402
from smart_medic.kb.validate import (  # noqa: E402
    normalize_candidates,
    normalize_icd,
    normalize_rxcui,
)

KB_DIR = ROOT / "data/kb"


class TestIcdNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (KB_DIR / "MANIFEST.json").exists():
            raise unittest.SkipTest("chưa build KB: python -m smart_medic.kb.build")
        cls.kb = load_kb(KB_DIR)

    def test_icd10_cm_codes_seen_in_real_llm_output_fold_to_who(self):
        # Đúng 8 mã đã gặp khi ingest hai lượt opus-5 và sonnet-5.
        for given, want in [
            ("G47.33", "G47.3"), ("I25.10", "I25.1"), ("I25.41", "I25.4"),
            ("I48.91", "I48.9"), ("K05.9", "K05"), ("K20.9", "K20"),
            ("L03.90", "L03.9"), ("R56.9", "R56"),
        ]:
            with self.subTest(code=given):
                self.assertEqual(normalize_icd(given, self.kb.icd_concepts).result, want)

    def test_valid_codes_are_left_alone(self):
        for code in ("A82.9", "E11.9", "D55.0", "S06.6", "K25.9", "E85.3", "N46"):
            with self.subTest(code=code):
                self.assertEqual(normalize_icd(code, self.kb.icd_concepts).result, code)

    def test_unknown_code_is_dropped_not_guessed(self):
        self.assertIsNone(normalize_icd("ZZ9.9", self.kb.icd_concepts).result)
        self.assertIsNone(normalize_icd("", self.kb.icd_concepts).result)

    def test_never_invents_specificity(self):
        """Cắt hậu tố chỉ đi MỘT CHIỀU: đặc hiệu → tổng quát.

        Nâng mã cha lên con ".9" là việc của tầng quyết định, nơi có bằng chứng
        riêng để làm. Trộn nó vào đây thì hai tầng cùng chỉnh một thứ và không
        còn đo được tầng nào gây ra thay đổi gì.
        """
        # A82 có thật trong KB, nên phải giữ nguyên chứ không tự nhảy sang A82.9.
        self.assertEqual(normalize_icd("A82", self.kb.icd_concepts).result, "A82")

    def test_case_and_whitespace_are_tolerated(self):
        self.assertEqual(normalize_icd(" a82.9 ", self.kb.icd_concepts).result, "A82.9")


class TestRxcuiNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (KB_DIR / "MANIFEST.json").exists():
            raise unittest.SkipTest("chưa build KB: python -m smart_medic.kb.build")
        cls.kb = load_kb(KB_DIR)

    def test_live_codes_are_left_alone(self):
        for cui in ("612", "11258", "282386", "866924", "212033", "1364436"):
            with self.subTest(cui=cui):
                fix = normalize_rxcui(cui, self.kb.rx_concepts, self.kb.rx_remap)
                self.assertEqual(fix.result, cui)

    def test_unknown_cui_is_dropped(self):
        fix = normalize_rxcui("999999999", self.kb.rx_concepts, self.kb.rx_remap)
        self.assertIsNone(fix.result)

    def test_retired_cui_absent_from_local_remap_is_dropped_not_faked(self):
        """727 (nhôm hydroxid) hỏng nhưng KHÔNG có trong RXNCUI.RRF bản này.

        Nó chỉ lộ ra khi tra RxNav bên ngoài. Gọi mạng thì vi phạm NFR1, nên
        hợp đồng đúng ở đây là LOẠI BỎ — và test này tồn tại để không ai
        "sửa" nó bằng một bảng tay chép từ RxNav rồi quên mất là đã chép.
        """
        fix = normalize_rxcui("727", self.kb.rx_concepts, self.kb.rx_remap)
        self.assertIsNone(fix.result)


class TestCandidateGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (KB_DIR / "MANIFEST.json").exists():
            raise unittest.SkipTest("chưa build KB: python -m smart_medic.kb.build")
        cls.kb = load_kb(KB_DIR)

    def test_non_mappable_types_never_get_codes(self):
        for type_name in ("TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"):
            with self.subTest(type=type_name):
                codes, _ = normalize_candidates(["R50.9"], type_name, self.kb)
                self.assertEqual(codes, [])

    def test_duplicates_collapse_after_normalization(self):
        # I25.10 và I25.1 quy về cùng một mã ⇒ chỉ còn một.
        codes, _ = normalize_candidates(["I25.10", "I25.1"], "CHẨN_ĐOÁN", self.kb)
        self.assertEqual(codes, ["I25.1"])

    def test_bare_string_is_accepted_like_a_list(self):
        codes, _ = normalize_candidates("E11.9", "CHẨN_ĐOÁN", self.kb)
        self.assertEqual(codes, ["E11.9"])

    def test_fixes_are_reported_only_when_something_changed(self):
        _, quiet = normalize_candidates(["E11.9"], "CHẨN_ĐOÁN", self.kb)
        self.assertEqual(quiet, [])
        _, loud = normalize_candidates(["I25.10"], "CHẨN_ĐOÁN", self.kb)
        self.assertEqual(len(loud), 1)

    def test_every_code_in_shipped_gold_survives_the_gate(self):
        """Gold đã chốt phải đi qua chính tầng này mà không mất mã nào.

        Nếu test này đỏ thì hoặc gold có mã rác, hoặc tầng chuẩn hóa vừa trở
        nên hung hăng quá mức — cả hai đều là tin cần biết ngay.
        """
        import json

        gold_dir = ROOT / "data/dev_gold"
        if not gold_dir.is_dir():
            self.skipTest("chưa có data/dev_gold")
        checked = 0
        for path in sorted(gold_dir.glob("*.json")):
            for record in json.loads(path.read_text(encoding="utf-8")):
                if not record["candidates"]:
                    continue
                codes, _ = normalize_candidates(
                    record["candidates"], record["type"], self.kb
                )
                self.assertEqual(
                    codes, record["candidates"],
                    f"{path.name}: {record['text']!r}",
                )
                checked += 1
        self.assertGreater(checked, 250, "gold trông thưa bất thường")


if __name__ == "__main__":
    unittest.main()
