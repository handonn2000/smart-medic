"""Tests cho holdout và bộ chọn tập file.

Hợp đồng đáng khóa nhất ở đây rất dễ hỏng một cách im lặng: ``data/test/``,
``data/silver_prompts/`` và ``data/dev_gold/`` là **cùng một tập 100 file**, nên
một file gold "giữ lại" vẫn có thể lọt vào train qua đường **nhãn bạc**. Nếu
điều đó xảy ra thì holdout mất tác dụng mà không có triệu chứng nào — train vẫn
chạy, điểm vẫn ra, chỉ là con số so sánh v3/v4 trở thành vô nghĩa.

Test dùng tokenizer giả để **không** phụ thuộc torch/transformers: thứ cần kiểm
là logic lọc tập dữ liệu, không phải phép tokenize.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from smart_medic.fileset import parse_file_selector  # noqa: E402
from train_ner import HOLDOUT_FILES, bio_labels, load_dataset  # noqa: E402

DEV_FILES = (1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94)


class FakeTokenizer:
    """Tokenizer tối thiểu: mỗi ký tự là một token."""

    def __call__(self, text, **_kwargs):
        return {
            "input_ids": list(range(len(text))),
            "offset_mapping": [(i, i + 1) for i in range(len(text))],
        }


class TestFileSelector(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_file_selector("1,3,4"), (1, 3, 4))
        self.assertEqual(parse_file_selector("1-5"), (1, 2, 3, 4, 5))
        self.assertEqual(parse_file_selector("1-3, 7"), (1, 2, 3, 7))

    def test_duplicates_collapse_keeping_order(self):
        self.assertEqual(parse_file_selector("3,1,3"), (3, 1))

    def test_reversed_range_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            parse_file_selector("9-2")


class TestHoldoutFiltering(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.silver = self.tmp / "silver"
        self.gold = self.tmp / "gold"
        self.inputs = self.tmp / "input"
        for d in (self.silver, self.gold, self.inputs):
            d.mkdir()
        # Silver phủ 1..6; gold chỉ có 5,6 — mô phỏng đúng thế thật.
        for n in range(1, 7):
            (self.inputs / f"{n}.txt").write_text("sốt và ho", encoding="utf-8")
            self._write(self.silver / f"{n}.json", "sốt", 0, 3)
        for n in (5, 6):
            self._write(self.gold / f"{n}.json", "ho", 7, 9)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _write(path, text, start, end):
        path.write_text(json.dumps([{
            "text": text, "type": "TRIỆU_CHỨNG", "candidates": [],
            "assertions": [], "position": [start, end],
        }], ensure_ascii=False), encoding="utf-8")

    def _load(self, holdout=frozenset()):
        labels = bio_labels()
        return load_dataset(
            [self.silver, self.gold], self.inputs, FakeTokenizer(),
            {n: i for i, n in enumerate(labels)}, holdout,
        )

    def test_without_holdout_every_file_is_used(self):
        self.assertEqual({s["name"] for s in self._load()},
                         {"1", "2", "3", "4", "5", "6"})

    def test_holdout_file_present_only_in_silver_is_excluded(self):
        names = {s["name"] for s in self._load(frozenset({"2"}))}
        self.assertNotIn("2", names)
        self.assertEqual(len(names), 5)

    def test_holdout_file_present_in_both_dirs_is_excluded_from_both(self):
        """Ca quan trọng nhất: file 5 có ở CẢ silver lẫn gold.

        Lọc riêng thư mục gold thì nhãn bạc của file 5 vẫn vào train và model
        vẫn thấy văn bản đó. Phải biến mất hoàn toàn.
        """
        names = {s["name"] for s in self._load(frozenset({"5"}))}
        self.assertNotIn("5", names)

    def test_holdout_naming_unknown_file_is_harmless(self):
        self.assertEqual(len(self._load(frozenset({"999"}))), 6)


class TestHoldoutComposition(unittest.TestCase):
    """Holdout phải phản chiếu phân tầng của dev, không phải lấy bừa."""

    def test_holdout_is_a_subset_of_the_frozen_dev_set(self):
        self.assertTrue(set(HOLDOUT_FILES) <= set(DEV_FILES))

    def test_holdout_size_leaves_enough_gold_to_train_on(self):
        self.assertEqual(len(HOLDOUT_FILES), 6)
        self.assertEqual(len(set(DEV_FILES) - set(HOLDOUT_FILES)), 14)

    def test_holdout_covers_nfd_and_masked_tokens(self):
        """Hai lớp lỗi đã xảy ra thật phải có mặt trong holdout.

        NFD làm position lệch âm thầm; token bị che xóa mất chính hoạt chất cần
        để map RxNorm. Holdout toàn file NFC sạch sẽ báo "ổn" ngay cả khi hai
        lớp lỗi đó quay lại — nên đây là khẳng định về giá trị chẩn đoán của
        tập holdout, không phải về nội dung file.
        """
        import re
        import unicodedata

        data = ROOT / "data/test"
        if not data.is_dir():
            self.skipTest("chưa có data/test")
        nfd = masked = 0
        for n in HOLDOUT_FILES:
            raw = (data / f"{n}.txt").read_text(encoding="utf-8")
            if raw != unicodedata.normalize("NFC", raw):
                nfd += 1
            if re.search(r"\*{3,}", raw):
                masked += 1
        self.assertGreaterEqual(nfd, 1, "holdout không có file NFD nào")
        self.assertGreaterEqual(masked, 1, "holdout không có file nào có token bị che")


if __name__ == "__main__":
    unittest.main()
