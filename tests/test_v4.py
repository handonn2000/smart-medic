"""Tests cho v4 — model bundle và NeuralExtractor.

Hai nhóm:

* :class:`TestModelStore` chạy Ở MỌI MÁY (chỉ thư viện chuẩn). Nó khóa hợp đồng
  verify bundle — phần quyết định việc "thiếu weights" là lỗi TO lúc start chứ
  không phải output tệ âm thầm ở file thứ 73.
* :class:`TestNeuralExtractor` cần onnxruntime + tokenizers nên tự SKIP khi
  thiếu. Việc skip đó chính nó là một khẳng định: nhánh v0–v3 phải chạy được
  trên máy không có ba wheel kia, nếu không thì NFR1 đã vỡ.

Fixture ``tests/fixtures/stub_model`` là bundle tí hon TẤT ĐỊNH (1,3 KB), sinh
bằng ``scripts/make_stub_model.py``. Nó không học gì — chỉ là bảng tra token→nhãn
— nên test khẳng định được span CHÍNH XÁC, và logic cửa sổ trượt / giải mã BIO /
ánh xạ offset được kiểm ĐỘC LẬP với việc model thật đã train hay chưa.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.modelstore import (  # noqa: E402
    ModelError,
    bundle_exists,
    load_bundle,
    write_manifest,
)
from smart_medic.normalize import NORMALIZER_VERSION  # noqa: E402
from smart_medic.schema import ConceptType  # noqa: E402
from smart_medic.textref import build_textref  # noqa: E402

STUB = ROOT / "tests/fixtures/stub_model"

try:  # runtime inference là tùy chọn — xem docstring
    import numpy  # noqa: F401
    import onnxruntime  # noqa: F401
    from tokenizers import Tokenizer  # noqa: F401

    HAVE_RUNTIME = True
except ImportError:
    HAVE_RUNTIME = False


def _bio_labels() -> list[str]:
    out = ["O"]
    for ctype in ConceptType:
        out.extend((f"B-{ctype.value}", f"I-{ctype.value}"))
    return out


class TestModelStore(unittest.TestCase):
    """Hợp đồng verify — chạy không cần onnxruntime."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _stub_bundle(self) -> Path:
        if not bundle_exists(STUB):
            self.skipTest("chưa sinh fixture: scripts/make_stub_model.py")
        target = self.tmp / "bundle"
        shutil.copytree(STUB, target)
        return target

    def test_missing_bundle_names_the_v3_fallback(self):
        with self.assertRaises(ModelError) as ctx:
            load_bundle(self.tmp / "khong-ton-tai")
        message = str(ctx.exception)
        self.assertIn("--extractor v3", message)
        self.assertIn("train_ner.py", message)

    def test_stub_bundle_loads(self):
        bundle = load_bundle(self._stub_bundle())
        self.assertEqual("stub-v1", bundle.model_version)
        self.assertEqual(tuple(_bio_labels()), bundle.labels)
        self.assertTrue(bundle.onnx_path.is_file())
        self.assertTrue(bundle.tokenizer_path.is_file())

    def test_tampered_weights_fail_loud(self):
        """Checksum sai phải chặn ở start — không được chạy tiếp."""
        bundle_dir = self._stub_bundle()
        onnx = bundle_dir / "ner.onnx"
        onnx.write_bytes(onnx.read_bytes() + b"\x00")
        with self.assertRaises(ModelError) as ctx:
            load_bundle(bundle_dir)
        self.assertIn("kích thước", str(ctx.exception))

    def test_deleted_artifact_fails_loud(self):
        bundle_dir = self._stub_bundle()
        (bundle_dir / "tokenizer.json").unlink()
        with self.assertRaises(ModelError):
            load_bundle(bundle_dir)

    def test_normalizer_version_mismatch_fails_loud(self):
        """Model học trên chuỗi đã chuẩn hóa — lệch normalizer là lệch phân phối."""
        bundle_dir = self._stub_bundle()
        manifest_path = bundle_dir / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["normalizer_version"] = NORMALIZER_VERSION + 1
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ModelError) as ctx:
            load_bundle(bundle_dir)
        self.assertIn("normalizer_version", str(ctx.exception))

    def test_abbreviated_labels_are_rejected(self):
        """``TÊN_XN`` từng làm hỏng cả 471 record. Trong artifact còn khó thấy hơn."""
        bundle_dir = self._stub_bundle()
        bad = [label.replace("TÊN_XÉT_NGHIỆM", "TÊN_XN") for label in _bio_labels()]
        with self.assertRaises(ModelError) as ctx:
            write_manifest(
                bundle_dir, model_version="x", labels=bad, base_model="stub/wordlevel"
            )
        self.assertIn("BIO", str(ctx.exception))

    def test_importing_modelstore_does_not_pull_onnxruntime(self):
        """Nhánh v0–v3 phải chạy trên máy chỉ có thư viện chuẩn (NFR1/NFR2)."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; import smart_medic.modelstore, smart_medic.infer;"
                " assert 'onnxruntime' not in sys.modules, 'onnxruntime bị nạp sớm';"
                " print('ok')",
            ],
            env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)


@unittest.skipUnless(HAVE_RUNTIME, "cần onnxruntime + tokenizers (pip install -r requirements.txt)")
class TestNeuralExtractor(unittest.TestCase):
    SENTENCE = "Bệnh nhân bị sốt cao và ho khan, chẩn đoán viêm phổi, dùng paracetamol 500mg"

    @classmethod
    def setUpClass(cls):
        if not bundle_exists(STUB):
            raise unittest.SkipTest("chưa sinh fixture: scripts/make_stub_model.py")
        from smart_medic.stages.neural import NeuralExtractor

        cls.extractor = NeuralExtractor(load_bundle(STUB))

    def _spans(self, raw: str):
        tref = build_textref(raw)
        candidates = self.extractor.extract(tref)
        for candidate in candidates:
            self.assertTrue(
                candidate.span.verify(tref.raw),
                f"BẤT BIẾN VỠ: {candidate.span!r}",
            )
        return [(c.span.text, c.type) for c in candidates]

    def test_multi_token_spans_on_nfc(self):
        self.assertEqual(
            [
                ("sốt cao", ConceptType.TRIEU_CHUNG),
                ("ho khan", ConceptType.TRIEU_CHUNG),
                ("viêm phổi", ConceptType.CHAN_DOAN),
                ("paracetamol 500mg", ConceptType.THUOC),
            ],
            self._spans(unicodedata.normalize("NFC", self.SENTENCE)),
        )

    def test_nfd_input_yields_identical_text_at_shifted_offsets(self):
        """20/100 file corpus lưu ở NFD. Text phải giống, offset phải khác."""
        nfc = unicodedata.normalize("NFC", self.SENTENCE)
        nfd = unicodedata.normalize("NFD", self.SENTENCE)
        self.assertNotEqual(len(nfc), len(nfd))       # fixture thật sự là NFD

        tref_nfc, tref_nfd = build_textref(nfc), build_textref(nfd)
        got_nfc = self.extractor.extract(tref_nfc)
        got_nfd = self.extractor.extract(tref_nfd)

        self.assertEqual(
            [unicodedata.normalize("NFC", c.span.text) for c in got_nfc],
            [unicodedata.normalize("NFC", c.span.text) for c in got_nfd],
        )
        self.assertNotEqual(
            [c.span.start for c in got_nfc], [c.span.start for c in got_nfd]
        )

    def test_mention_is_not_severed_at_a_window_boundary(self):
        """Hồi quy: cửa sổ trượt từng chặt ``sốt cao`` thành ``sốt`` + ``cao``.

        Cả hai mảnh vẫn verify được trên raw nên lỗi này KHÔNG ném exception —
        nó chỉ biến một mention đúng thành hai mention sai. Fixture dùng
        max_length=16 nên 8 lần lặp chắc chắn cắt qua nhiều cửa sổ.
        """
        raw = ("bệnh nhân bị sốt cao và ho khan " * 8).strip()
        tref = build_textref(raw)
        self.assertGreater(len(self.extractor._chunks(tref.norm)), 1, "phải nhiều cửa sổ")

        texts = [text for text, _ in self._spans(raw)]
        self.assertEqual(8, texts.count("sốt cao"))
        self.assertEqual(8, texts.count("ho khan"))
        self.assertNotIn("sốt", texts)                # mảnh vỡ của span dài
        self.assertNotIn("cao", texts)

    def test_windows_never_emit_overlapping_spans(self):
        raw = ("bệnh nhân bị sốt cao và ho khan " * 8).strip()
        spans = sorted(
            (c.span.start, c.span.end) for c in self.extractor.extract(build_textref(raw))
        )
        for (_, end), (next_start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, next_start)

    def test_never_emits_candidates(self):
        """Linking là việc của KB. Model nhớ ra mã = LLM bịa mã, đề bài cấm."""
        for candidate in self.extractor.extract(build_textref(self.SENTENCE)):
            self.assertEqual((), candidate.codes)
            self.assertEqual([], candidate.provenance.kb_rows)

    def test_type_confidence_feeds_the_decision_layer(self):
        """p_t phải có thật — tầng quyết định của pipeline đọc chính nó."""
        for candidate in self.extractor.extract(build_textref(self.SENTENCE)):
            self.assertGreater(candidate.provenance.type_confidence, 0.0)
            self.assertLessEqual(candidate.provenance.type_confidence, 1.0)

    def test_min_score_gates_span_opening(self):
        from smart_medic.stages.neural import NeuralExtractor

        strict = NeuralExtractor(load_bundle(STUB), min_score=0.999999)
        self.assertEqual([], strict.extract(build_textref(self.SENTENCE)))

    def test_inference_is_deterministic(self):
        """NFR3: chạy lại phải ra hệt nhau, kể cả trên máy BTC."""
        first = self._spans(self.SENTENCE)
        for _ in range(3):
            self.assertEqual(first, self._spans(self.SENTENCE))

    def test_empty_and_whitespace_input_is_safe(self):
        for raw in ("", "   ", "\n\n"):
            self.assertEqual([], self.extractor.extract(build_textref(raw)))


class TestTrainingLabelAlignment(unittest.TestCase):
    """``raw_to_norm_span`` — đoạn dễ sai nhất của train_ner.py.

    JSON lưu position trên ``raw``; model học và suy luận trên ``norm``. Nếu hai
    chiều lệch nhau thì model học một phân phối span khác với phân phối được
    chấm — và sai kiểu đó KHÔNG ném exception, nó chỉ làm điểm thấp. Vì vậy
    chiều nghịch phải có test riêng, đúng như ``textref`` có.

    Không cần torch: hàm này thuần thư viện chuẩn.
    """

    @staticmethod
    def _fn():
        sys.path.insert(0, str(ROOT / "scripts"))
        from train_ner import raw_to_norm_span

        return raw_to_norm_span

    def test_round_trip_on_nfc_and_nfd(self):
        raw_to_norm_span = self._fn()
        sentence = "Bệnh nhân bị sốt cao và ho khan, chẩn đoán viêm phổi."
        for form in ("NFC", "NFD"):
            raw = unicodedata.normalize(form, sentence)
            tref = build_textref(raw)
            for needle in ("sốt cao", "ho khan", "viêm phổi", "Bệnh nhân"):
                target = unicodedata.normalize(form, needle)
                rs = raw.index(target)
                re_ = rs + len(target)
                with self.subTest(form=form, needle=needle):
                    mapped = raw_to_norm_span(tref, rs, re_)
                    self.assertIsNotNone(mapped)
                    self.assertEqual((rs, re_), tref.to_raw(*mapped))

    def test_round_trip_on_real_corpus_output(self):
        """Hồi quy trên dữ liệu thật: mọi span của artifact phải map hai chiều."""
        out_dir = ROOT / "data/output"
        if not (out_dir / "1.json").is_file():
            self.skipTest("chưa có data/output — chạy smart_medic.infer trước")
        raw_to_norm_span = self._fn()
        checked = 0
        for index in (1, 5, 14, 42, 54, 94, 100):     # gồm nhiều file NFD
            src = ROOT / f"data/test/{index}.txt"
            pred = out_dir / f"{index}.json"
            if not (src.is_file() and pred.is_file()):
                continue
            tref = build_textref(src.read_text(encoding="utf-8"))
            for record in json.loads(pred.read_text(encoding="utf-8")):
                rs, re_ = record["position"]
                mapped = raw_to_norm_span(tref, rs, re_)
                self.assertIsNotNone(mapped, f"{index}: {record['text']!r}")
                self.assertEqual((rs, re_), tref.to_raw(*mapped), record["text"])
                checked += 1
        self.assertGreater(checked, 100, "mẫu kiểm quá nhỏ")


if __name__ == "__main__":
    unittest.main()
