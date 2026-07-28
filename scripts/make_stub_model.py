#!/usr/bin/env python3
"""Dựng model bundle GIẢ, tí hon, tất định — làm fixture cho test.

Vì sao cần: :class:`smart_medic.stages.neural.NeuralExtractor` chứa phần logic
dễ sai nhất của v4 — cửa sổ trượt có chồng lấn, giải mã BIO, và ánh xạ offset
token → norm → raw. Phần đó phải được test ĐỘC LẬP với việc model thật đã được
train hay chưa, nếu không thì tới lúc có weights mới phát hiện lỗi, và lúc đó
không phân biệt được "model dở" với "decode sai".

Bundle sinh ra ở đây KHÔNG học gì cả. Nó là một bảng tra: token id → logits cố
định. Nhờ vậy test khẳng định được span CHÍNH XÁC thay vì chỉ "không crash".

Chạy (cần torch, chỉ dev-time):
    .venv/bin/python scripts/make_stub_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.modelstore import write_manifest  # noqa: E402
from smart_medic.schema import ConceptType  # noqa: E402

OUT = ROOT / "tests/fixtures/stub_model"

#: Từ vựng tí hon. Chọn từ tiếng Việt CÓ DẤU để fixture đi qua đúng đường
#: NFC/NFD mà corpus thật đi qua.
VOCAB_WORDS = [
    "bệnh", "nhân", "bị", "sốt", "cao", "và", "ho", "khan",
    "chẩn", "đoán", "viêm", "phổi", "dùng", "paracetamol", "500mg",
    "xét", "nghiệm", "bạch", "cầu", "12.5", "không", "có",
]

#: token → nhãn mà stub sẽ phát ra. Đủ để dựng span nhiều token, span một
#: token, và hai span cạnh nhau khác type.
TOKEN_LABEL = {
    "sốt": "B-TRIỆU_CHỨNG",
    "cao": "I-TRIỆU_CHỨNG",
    "ho": "B-TRIỆU_CHỨNG",
    "khan": "I-TRIỆU_CHỨNG",
    "viêm": "B-CHẨN_ĐOÁN",
    "phổi": "I-CHẨN_ĐOÁN",
    "paracetamol": "B-THUỐC",
    "500mg": "I-THUỐC",
    "bạch": "B-TÊN_XÉT_NGHIỆM",
    "cầu": "I-TÊN_XÉT_NGHIỆM",
    "12.5": "B-KẾT_QUẢ_XÉT_NGHIỆM",
}


def labels() -> list[str]:
    out = ["O"]
    for ctype in ConceptType:
        out.extend((f"B-{ctype.value}", f"I-{ctype.value}"))
    return out


def build_tokenizer(path: Path) -> dict[str, int]:
    from tokenizers import Tokenizer, models, pre_tokenizers

    specials = ["<s>", "</s>", "<unk>"]
    vocab = {tok: i for i, tok in enumerate(specials + VOCAB_WORDS)}
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="<unk>"))
    # Whitespace pre-tokenizer giữ offset ký tự — đó chính là thứ
    # NeuralExtractor dựa vào để ánh xạ ngược về norm.
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    path.parent.mkdir(parents=True, exist_ok=True)
    tok.save(str(path))
    return vocab


def build_onnx(path: Path, vocab: dict[str, int], label_list: list[str]) -> None:
    import torch
    import torch.nn as nn

    label_index = {name: i for i, name in enumerate(label_list)}

    class StubTagger(nn.Module):
        """Embedding thuần: id → logits. Không attention, không học."""

        def __init__(self, n_vocab: int, n_labels: int) -> None:
            super().__init__()
            self.table = nn.Embedding(n_vocab, n_labels)
            with torch.no_grad():
                self.table.weight.fill_(0.0)
                self.table.weight[:, label_index["O"]] = 6.0
                for word, label in TOKEN_LABEL.items():
                    self.table.weight[vocab[word], label_index["O"]] = 0.0
                    self.table.weight[vocab[word], label_index[label]] = 6.0

        def forward(self, input_ids, attention_mask=None):  # noqa: ARG002
            return self.table(input_ids)

    model = StubTagger(len(vocab), len(label_list)).eval()
    dummy = torch.zeros((1, 8), dtype=torch.long)
    torch.onnx.export(
        model,
        (dummy, torch.ones((1, 8), dtype=torch.long)),
        str(path),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "logits": {0: "batch", 1: "seq"},
        },
        opset_version=14,
        dynamo=False,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    label_list = labels()
    vocab = build_tokenizer(OUT / "tokenizer.json")
    build_onnx(OUT / "ner.onnx", vocab, label_list)
    manifest = write_manifest(
        OUT,
        model_version="stub-v1",
        labels=label_list,
        base_model="stub/wordlevel",
        # Cửa sổ cố tình BÉ để test được đường cắt cửa sổ trượt mà không cần
        # văn bản dài hàng nghìn token.
        max_length=16,
        stride=4,
    )
    print(f"✓ stub bundle → {OUT}")
    for name, meta in sorted(manifest["artifacts"].items()):
        print(f"    {name:16} {meta['bytes']:>8} B  {meta['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
