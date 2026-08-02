"""Corpus → BIO. Dùng tokenizer GIẢ nên không cần torch/transformers."""

from __future__ import annotations

import json
import unicodedata

from smart_medic.stages.bio import IGNORE_ID, LABELS, tags_to_spans
from smart_medic.stages.scoring import Entity
from smart_medic.train import dataset


class FakeTokenizer:
    """Cắt theo khoảng trắng, trả `offset_mapping` như HuggingFace fast tokenizer.

    Đủ để kiểm phần ta viết (căn span ↔ token, cửa sổ). Hành vi thật của XLM-R
    đã được đo riêng — xem docstring `train/dataset.py`.
    """

    pad_token_id = 1

    def __call__(self, text, **kw):
        offs, ids = [(0, 0)], [0]
        i = 0
        for w in text.split(" "):
            if w:
                offs.append((i, i + len(w)))
                ids.append(len(offs))
            i += len(w) + 1
        offs.append((0, 0))
        ids.append(2)
        return {
            "input_ids": [ids],
            "attention_mask": [[1] * len(ids)],
            "offset_mapping": [offs],
        }


class TestSpansToTags:
    def test_token_dac_biet_khong_tinh_loss(self):
        tok = FakeTokenizer()
        text = "Chẩn đoán: viêm phổi"
        spans = [Entity("viêm phổi", "CHẨN_ĐOÁN", 11, 20)]
        w = dataset.encode_document("1", text, spans, tok)[0]
        assert w.labels[0] == IGNORE_ID and w.labels[-1] == IGNORE_ID

    def test_nhan_B_roi_I(self):
        tok = FakeTokenizer()
        text = "Chẩn đoán: viêm phổi"
        spans = [Entity("viêm phổi", "CHẨN_ĐOÁN", 11, 20)]
        w = dataset.encode_document("1", text, spans, tok)[0]
        got = [LABELS[t] for t in w.labels if t != IGNORE_ID]
        assert got == ["O", "O", "B-CHẨN_ĐOÁN", "I-CHẨN_ĐOÁN"]

    def test_vong_tron_ra_lai_span(self):
        tok = FakeTokenizer()
        text = "sốt cao và ho"
        spans = [Entity("sốt cao", "TRIỆU_CHỨNG", 0, 7), Entity("ho", "TRIỆU_CHỨNG", 11, 13)]
        w = dataset.encode_document("1", text, spans, tok)[0]
        back = tags_to_spans(text, w.offsets, w.labels)
        assert [(e.start, e.end, e.text) for e in back] == [(0, 7, "sốt cao"), (11, 13, "ho")]

    def test_van_ban_NFD_van_ra_offset_dung(self):
        tok = FakeTokenizer()
        text = unicodedata.normalize("NFD", "tiền sản giật")
        spans = [Entity(text, "CHẨN_ĐOÁN", 0, len(text))]
        w = dataset.encode_document("1", text, spans, tok)[0]
        for e in tags_to_spans(text, w.offsets, w.labels):
            assert text[e.start : e.end] == e.text


class TestLoadCorpus:
    def test_doc_bang_read_document_khong_phai_read_text(self, tmp_path):
        """★ `Path.read_text()` bật universal newlines và nuốt `\\r` — lệch offset.

        `sample_output.json` của BTC lệch 19/19 mục đúng vì chuyện này.
        """
        (tmp_path / "text").mkdir()
        (tmp_path / "annotations").mkdir()
        raw = "dòng một\r\nsốt cao"
        (tmp_path / "text" / "1.txt").write_bytes(raw.encode("utf-8"))
        (tmp_path / "annotations" / "1.json").write_text(
            json.dumps(
                [
                    {
                        "text": "sốt cao",
                        "type": "TRIỆU_CHỨNG",
                        "candidates": [],
                        "assertions": [],
                        "position": [10, 17],
                    }
                ]
            ),
            encoding="utf-8",
        )
        _, text, spans = dataset.load_corpus(tmp_path)[0]
        assert "\r" in text, "phải giữ nguyên CRLF"
        assert text[spans[0].start : spans[0].end] == "sốt cao"

    def test_thu_tu_theo_so(self, tmp_path):
        (tmp_path / "text").mkdir()
        (tmp_path / "annotations").mkdir()
        for stem in ("1", "9", "10", "100"):
            (tmp_path / "text" / f"{stem}.txt").write_text("x", encoding="utf-8")
            (tmp_path / "annotations" / f"{stem}.json").write_text("[]", encoding="utf-8")
        assert [n for n, _, _ in dataset.load_corpus(tmp_path)] == ["1", "9", "10", "100"]
