"""Tests for the dev-set pre-annotation tooling and the metric sweep.

Trọng tâm là **round-trip không cần LLM**: lấy prediction thật trong
``data/output/{n}.json``, xóa hết ``position`` để giả lập đúng thứ mà LLM được
phép trả về (chỉ text/type/assertions/candidates), cho chạy qua ``--ingest``,
rồi khẳng định position phục hồi được TRÙNG KHÍT bản gốc.

Phép thử này chứng minh đường định vị đúng trên chính văn bản corpus, bao gồm
các file lưu ở dạng NFD (13, 14, 16, 17, 42, 54, 94) — nơi ``str.find()`` thất
bại âm thầm và là lý do ``TextRef`` tồn tại.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import metric_sweep  # noqa: E402
import preannotate_dev as pre  # noqa: E402

from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.schema import ConceptType, validate_file  # noqa: E402
from smart_medic.textref import build_textref, read_textref  # noqa: E402

TEST_DIR = ROOT / "data/test"
OUTPUT_DIR = ROOT / "data/output"
#: File lưu ở dạng NFD — bẫy chính mà round-trip phải chứng minh là đã xử lý.
NFD_FILES = (14, 16, 17, 42, 54, 94)


def fake_llm_response(records: list[dict]) -> list[dict]:
    """Giả lập câu trả lời LLM: đúng 4 trường, KHÔNG có position."""
    return [
        {
            "text": r["text"],
            "type": r["type"],
            "assertions": list(r.get("assertions", [])),
            "candidates": list(r.get("candidates", [])),
        }
        for r in records
    ]


@contextlib.contextmanager
def quiet():
    """Nuốt stdout — test không cần in bảng báo cáo ra màn hình."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def occurrence_complete(records: list[dict], src: Path) -> list[dict]:
    """Bản annotation liệt kê ĐỦ mọi lần xuất hiện của mỗi chuỗi, theo thứ tự.

    Đây là thứ prompt yêu cầu LLM trả về ("khái niệm xuất hiện n lần thì liệt kê
    n lần"), và cũng là điều kiện để round-trip đúng tuyệt đối.
    """
    tref = build_textref(src.read_text(encoding="utf-8"))
    hay = tref.norm
    meta = {}
    for r in records:
        meta.setdefault(norm_text(r["text"]), r)

    items: list[tuple[int, dict]] = []
    for needle, template in meta.items():
        i = hay.find(needle)
        while i >= 0:
            start, end = tref.to_raw(i, i + len(needle))
            items.append((start, {
                "text": tref.raw[start:end],
                "type": template["type"],
                "assertions": list(template.get("assertions", [])),
                "candidates": list(template.get("candidates", [])),
            }))
            i = hay.find(needle, i + len(needle))
    items.sort(key=lambda x: x[0])
    return [item for _, item in items]


class TestPromptPayload(unittest.TestCase):
    def test_prompt_carries_exact_accented_labels(self):
        payload = pre.build_prompt("1", "Bệnh nhân sốt.")
        blob = payload["system"] + payload["user"]
        for label in ("TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM",
                      "CHẨN_ĐOÁN", "THUỐC"):
            self.assertIn(label, blob)
        # Viết tắt đã làm hỏng 471 record một lần — prompt không được chứa chúng
        # ngoài phần cảnh báo, và schema_hint phải là tên đầy đủ.
        self.assertEqual(list(payload["schema_hint"]["types"]),
                         [t.value for t in ConceptType])

    def test_prompt_lists_three_assertions_and_forbids_positions(self):
        payload = pre.build_prompt("1", "x")
        for name in ("isNegated", "isFamily", "isHistorical"):
            self.assertIn(name, payload["system"])
        self.assertIn("position", payload["schema_hint"]["forbidden_fields"])
        self.assertIn("KHÔNG TRẢ VỀ VỊ TRÍ", payload["system"])

    def test_prompt_embeds_document_text(self):
        payload = pre.build_prompt("42", "Bệnh nhân khó thở nhiều.")
        self.assertIn("Bệnh nhân khó thở nhiều.", payload["user"])

    def test_emit_prompts_writes_one_payload_per_dev_file(self):
        with tempfile.TemporaryDirectory() as tmp, quiet():
            out = Path(tmp)
            rc = pre.emit_prompts(TEST_DIR, out, (1, 3, 14))
            self.assertEqual(0, rc)
            for n in (1, 3, 14):
                self.assertTrue((out / f"{n}.request.json").exists())
                self.assertTrue((out / f"{n}.prompt.txt").exists())
            index = json.loads((out / "index.json").read_text(encoding="utf-8"))
            self.assertEqual([1, 3, 14], index["dev_files"])

    def test_dev_file_set_is_the_frozen_twenty(self):
        self.assertEqual(
            (1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94),
            pre.DEV_FILES,
        )
        for n in pre.DEV_FILES:
            self.assertTrue((TEST_DIR / f"{n}.txt").exists(), f"thiếu {n}.txt")


class TestResponseParsing(unittest.TestCase):
    def test_plain_array(self):
        items, mode = pre.parse_response('[{"text": "sốt"}]')
        self.assertEqual("clean", mode)
        self.assertEqual(1, len(items))

    def test_markdown_fence_is_stripped(self):
        body = '```json\n[{"text": "sốt", "type": "TRIỆU_CHỨNG"}]\n```'
        items, mode = pre.parse_response(body)
        self.assertEqual("clean", mode)
        self.assertEqual("sốt", items[0]["text"])

    def test_truncated_response_recovers_longest_valid_prefix(self):
        body = (
            '[{"text": "sốt", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},\n'
            ' {"text": "ho", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},\n'
            ' {"text": "khó th'
        )
        items, mode = pre.parse_response(body)
        self.assertEqual("truncated_prefix", mode)
        self.assertEqual(["sốt", "ho"], [i["text"] for i in items])

    def test_truncated_inside_fence(self):
        body = '```json\n[{"text": "sốt", "type": "TRIỆU_CHỨNG"}, {"text": "kh'
        items, mode = pre.parse_response(body)
        self.assertEqual("truncated_prefix", mode)
        self.assertEqual(1, len(items))

    def test_object_wrapper(self):
        items, mode = pre.parse_response('{"mentions": [{"text": "sốt"}]}')
        self.assertEqual("object_wrapper", mode)
        self.assertEqual(1, len(items))

    def test_garbage_is_reported_not_raised(self):
        items, mode = pre.parse_response("xin lỗi, tôi không thể trả lời")
        self.assertEqual([], items)
        self.assertEqual("no_array", mode)


class TestIngestDiscipline(unittest.TestCase):
    def _ingest(self, raw: str, items: list[dict]):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "9001.txt"
            src.write_text(raw, encoding="utf-8")
            tref = read_textref(src)
        report = pre.FileReport(name="9001")
        return pre.ingest_file("9001", tref, items, report), report

    def test_paraphrased_span_is_dropped_not_guessed(self):
        raw = "Bệnh nhân sốt cao 39 độ."
        records, report = self._ingest(
            raw,
            [
                {"text": "sốt cao", "type": "TRIỆU_CHỨNG",
                 "assertions": [], "candidates": []},
                {"text": "bệnh nhân bị sốt rất cao", "type": "TRIỆU_CHỨNG",
                 "assertions": [], "candidates": []},
            ],
        )
        self.assertEqual(1, len(records))
        self.assertEqual(["bệnh nhân bị sốt rất cao"], report.dropped_unlocatable)
        self.assertEqual([], validate_file(records, raw))

    def test_nth_mention_maps_to_nth_occurrence(self):
        raw = "sốt, ho, sốt, sốt"
        items = [
            {"text": "sốt", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []}
            for _ in range(3)
        ]
        records, _ = self._ingest(raw, items)
        self.assertEqual([[0, 3], [9, 12], [14, 17]],
                         [r["position"] for r in records])
        for r in records:
            self.assertEqual(r["text"], raw[r["position"][0]:r["position"][1]])

    def test_type_gate_strips_candidates_on_non_mappable_types(self):
        raw = "Bệnh nhân khó thở."
        records, report = self._ingest(
            raw,
            [{"text": "khó thở", "type": "TRIỆU_CHỨNG",
              "assertions": [], "candidates": ["R06.0"]}],
        )
        self.assertEqual([], records[0]["candidates"])
        self.assertEqual(1, len(report.stripped_candidates))
        self.assertEqual([], validate_file(records, raw))

    def test_assertion_gate_strips_assertions_on_lab_types(self):
        raw = "Glucose 5.6 mmol/L"
        records, report = self._ingest(
            raw,
            [{"text": "5.6 mmol/L", "type": "KẾT_QUẢ_XÉT_NGHIỆM",
              "assertions": ["isNegated"], "candidates": []}],
        )
        self.assertEqual([], records[0]["assertions"])
        self.assertEqual(1, len(report.stripped_assertions))

    def test_llm_supplied_positions_are_ignored_and_reported(self):
        raw = "Bệnh nhân sốt."
        records, report = self._ingest(
            raw,
            [{"text": "sốt", "type": "TRIỆU_CHỨNG", "assertions": [],
              "candidates": [], "position": [999, 1002]}],
        )
        self.assertEqual(1, report.ignored_positions)
        self.assertEqual([10, 13], records[0]["position"])

    def test_abbreviated_label_is_dropped(self):
        raw = "Công thức máu bình thường."
        records, report = self._ingest(
            raw,
            [{"text": "Công thức máu", "type": "TÊN_XN",
              "assertions": [], "candidates": []}],
        )
        self.assertEqual([], records)
        self.assertEqual(1, len(report.dropped_bad_type))

    def test_malformed_items_do_not_raise(self):
        raw = "sốt"
        records, report = self._ingest(
            raw, ["chuỗi trần", {"type": "TRIỆU_CHỨNG"}, {"text": "", "type": "THUỐC"}]
        )
        self.assertEqual([], records)
        self.assertEqual(3, len(report.dropped_malformed))

    def test_ingest_refuses_to_write_when_schema_fails(self):
        # Không có câu trả lời → không ghi file nào, và không nổ.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gold"
            with quiet():
                failed, reports = pre.ingest(Path(tmp), TEST_DIR, out, (1,))
            self.assertEqual(0, failed)
            self.assertEqual("missing", reports[0].parse_mode)
            self.assertFalse((out / "1.json").exists())


class TestRoundTripOnRealCorpus(unittest.TestCase):
    """Chứng minh đường định vị đúng trên văn bản corpus thật, không cần LLM.

    Giới hạn đã đo và phải nói rõ: round-trip từ artifact v3 KHÔNG thể đúng
    100% về nguyên lý. Có mention mà chuỗi của nó xuất hiện sớm hơn trong văn
    bản nhưng v3 **không** annotate lần đó (v3 sót recall — đúng chẩn đoán của
    báo cáo v4 §1.3). Khi câu trả lời không mang position, không thông tin nào
    phân biệt được "lần thứ nhất" với "lần thứ hai" trong trường hợp đó.

    Vậy nên có hai phép thử:
      * :meth:`test_round_trip_is_exact_when_annotation_is_occurrence_complete`
        — annotation liệt kê ĐỦ mọi lần xuất hiện (đúng như prompt yêu cầu):
        khôi phục phải TRÙNG KHÍT tuyệt đối.
      * :meth:`test_round_trip_on_v3_artifact_verbatim` — artifact v3 nguyên
        trạng: mọi span phải verify được, và mọi sai lệch phải là lần-xuất-hiện
        khác của CÙNG chuỗi (tức lỗ hổng recall của v3), không bao giờ là span
        không verify được.
    """

    @classmethod
    def setUpClass(cls):
        if not OUTPUT_DIR.exists():
            raise unittest.SkipTest("chưa có data/output")

    @staticmethod
    def _round_trip(files, expand: bool):
        """Trả (originals, recovered, reports). ``expand``: liệt kê đủ occurrence."""
        with tempfile.TemporaryDirectory() as tmp:
            responses = Path(tmp) / "responses"
            gold = Path(tmp) / "gold"
            responses.mkdir()

            usable: list[int] = []
            originals: dict[str, list[dict]] = {}
            for n in files:
                pred_path = OUTPUT_DIR / f"{n}.json"
                if not pred_path.exists():
                    continue
                records = sorted(
                    json.loads(pred_path.read_text(encoding="utf-8")),
                    key=lambda r: (r["position"][0], r["position"][1]),
                )
                originals[str(n)] = records
                usable.append(n)
                items = fake_llm_response(records)
                if expand:
                    items = occurrence_complete(records, TEST_DIR / f"{n}.txt")
                (responses / f"{n}.json").write_text(
                    json.dumps(items, ensure_ascii=False), encoding="utf-8"
                )

            with quiet():
                failed, reports = pre.ingest(responses, TEST_DIR, gold, usable)
            recovered = {
                r.name: json.loads((gold / f"{r.name}.json").read_text(encoding="utf-8"))
                for r in reports if r.written
            }
            return originals, recovered, reports, failed

    def test_round_trip_is_exact_when_annotation_is_occurrence_complete(self):
        originals, recovered, reports, failed = self._round_trip(pre.DEV_FILES, expand=True)
        self.assertEqual(0, failed)
        self.assertTrue(originals)
        for report in reports:
            with self.subTest(file=report.name):
                self.assertTrue(report.written)
                self.assertEqual([], report.schema_errors)
                self.assertEqual([], report.dropped_unlocatable)
                got = {(r["text"], tuple(r["position"])) for r in recovered[report.name]}
                for r in originals[report.name]:
                    self.assertIn(
                        (r["text"], tuple(r["position"])), got,
                        f"mất span {r['text']!r} @ {r['position']} trong file {report.name}",
                    )

    def test_round_trip_on_v3_artifact_verbatim(self):
        originals, recovered, reports, failed = self._round_trip(pre.DEV_FILES, expand=False)
        self.assertEqual(0, failed)

        total = mismatched = 0
        for report in reports:
            with self.subTest(file=report.name):
                self.assertTrue(report.written)
                self.assertEqual([], report.schema_errors)
                self.assertEqual([], report.dropped_unlocatable)

                raw = (TEST_DIR / f"{report.name}.txt").read_text(encoding="utf-8")
                hay = build_textref(raw).norm
                expected = originals[report.name]
                got = recovered[report.name]
                self.assertEqual(len(expected), len(got))

                # Bất biến TUYỆT ĐỐI: mọi span xuất ra đều verify trên raw.
                for act in got:
                    self.assertEqual(act["text"], raw[act["position"][0]:act["position"][1]])

                landed = {(r["text"], r["type"], tuple(r["position"])) for r in got}
                for exp in expected:
                    total += 1
                    if (exp["text"], exp["type"], tuple(exp["position"])) in landed:
                        continue
                    mismatched += 1
                    # Sai lệch duy nhất được phép: chuỗi đó xuất hiện nhiều lần
                    # trong văn bản và v3 chỉ annotate một phần — lỗ hổng recall
                    # của v3, không phải lỗi offset.
                    self.assertGreater(
                        hay.count(norm_text(exp["text"])), 1,
                        f"[{report.name}] {exp['text']!r} lệch nhưng chỉ xuất hiện một lần",
                    )

        self.assertGreater(total, 400)
        # Đo được: 3/423 trên artifact v3.3, cả ba đều là lỗ hổng recall của v3.
        self.assertLessEqual(mismatched / total, 0.02, f"{mismatched}/{total} lệch")

    def test_round_trip_covers_the_nfd_files(self):
        originals, recovered, reports, failed = self._round_trip(NFD_FILES, expand=True)
        self.assertEqual(0, failed)
        for report in reports:
            with self.subTest(file=report.name):
                raw = (TEST_DIR / f"{report.name}.txt").read_text(encoding="utf-8")
                # File NFD: raw dài hơn NFC vì dấu là ký tự tổ hợp riêng.
                self.assertNotEqual(
                    len(raw), len(unicodedata.normalize("NFC", raw)),
                    f"file {report.name} không còn ở dạng NFD — cập nhật NFD_FILES",
                )
                got = {(r["text"], tuple(r["position"])) for r in recovered[report.name]}
                for r in originals[report.name]:
                    self.assertIn((r["text"], tuple(r["position"])), got)


class TestMetricSweep(unittest.TestCase):
    def _dirs(self, tmp: str, gold_files: dict, pred_files: dict):
        gold_dir, pred_dir = Path(tmp) / "gold", Path(tmp) / "pred"
        gold_dir.mkdir()
        pred_dir.mkdir()
        for name, records in gold_files.items():
            (gold_dir / f"{name}.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8")
        for name, records in pred_files.items():
            (pred_dir / f"{name}.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return gold_dir, pred_dir

    def test_sweep_covers_all_twelve_readings(self):
        recs = [{"text": "sốt", "type": "TRIỆU_CHỨNG", "candidates": [],
                 "assertions": [], "position": [0, 3]}]
        rows = metric_sweep.sweep({"1": recs}, {"1": recs}, ["1"])
        self.assertEqual(12, len(rows))
        self.assertEqual(
            {(m, w, u) for m in metric_sweep.MATCH_MODES
             for w in metric_sweep.WER_MODES for u in metric_sweep.UNMATCHED_MODES},
            {(r["match"], r["wer"], r["unmatched"]) for r in rows},
        )
        for row in rows:
            self.assertAlmostEqual(1.0, row["final"], places=6)

    def test_unmatched_zero_versus_skip_diverges_on_missed_mentions(self):
        gold = [
            {"text": "sốt", "type": "TRIỆU_CHỨNG", "candidates": [],
             "assertions": [], "position": [0, 3]},
            {"text": "ho", "type": "TRIỆU_CHỨNG", "candidates": [],
             "assertions": [], "position": [5, 7]},
            {"text": "buồn nôn", "type": "TRIỆU_CHỨNG", "candidates": [],
             "assertions": [], "position": [9, 17]},
        ]
        pred = gold[:1]
        rows = metric_sweep.sweep({"1": gold}, {"1": pred}, ["1"])
        by_key = {(r["match"], r["wer"], r["unmatched"]): r for r in rows}
        zero = by_key[("overlap", "mean", "zero")]
        skip = by_key[("overlap", "mean", "skip")]
        # Đây chính là giả thuyết của báo cáo v4 §1.2: cùng một output, hai cách
        # đọc metric, chênh nhau cả một bậc điểm.
        self.assertAlmostEqual(1.0 / 3.0, zero["final"], places=6)
        self.assertAlmostEqual(1.0, skip["final"], places=6)

    def test_scores_only_the_intersection(self):
        recs = [{"text": "sốt", "type": "TRIỆU_CHỨNG", "candidates": [],
                 "assertions": [], "position": [0, 3]}]
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir, pred_dir = self._dirs(tmp, {"1": recs}, {"1": recs, "2": recs})
            gold = metric_sweep.load_dir(gold_dir)
            pred = metric_sweep.load_dir(pred_dir)
            keys = sorted(set(gold) & set(pred), key=metric_sweep._sort_key)
            self.assertEqual(["1"], keys)
            with quiet():
                rc = metric_sweep.main(["--gold", str(gold_dir), "--pred", str(pred_dir),
                                        "--leaderboard", "21.5450"])
            self.assertEqual(0, rc)

    def test_load_dir_skips_report_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "1.json").write_text("[]", encoding="utf-8")
            (d / "run_manifest.json").write_text("{}", encoding="utf-8")
            (d / "explain.json").write_text("{}", encoding="utf-8")
            self.assertEqual(["1"], sorted(metric_sweep.load_dir(d)))


if __name__ == "__main__":
    unittest.main()
