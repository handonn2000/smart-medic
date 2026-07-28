#!/usr/bin/env python3
"""Train encoder NER từ nhãn bạc/vàng rồi export bundle ONNX cho v4.

CHỈ CHẠY LÚC DEV. Không nằm trong runtime nộp bài: thứ được nộp là ``models/``
đã export, cộng ba wheel trong requirements.txt. Teacher LLM cũng không nằm ở
đây — nhãn bạc sinh bằng ``scripts/preannotate_dev.py --files 1-100``, cùng một
đường gán vị trí với gold.

    # 1. sinh prompt cho toàn corpus, chạy qua LLM của bạn, ingest lại
    PYTHONPATH=src python3 scripts/preannotate_dev.py --emit-prompts data/silver_prompts --files 1-100
    PYTHONPATH=src python3 scripts/preannotate_dev.py --ingest data/silver_responses --out data/silver --files 1-100

    # 2. train + export (cần requirements-dev.txt)
    .venv/bin/python scripts/train_ner.py --silver data/silver --gold data/dev_gold --export models

**Hợp đồng quan trọng nhất của file này:** nhãn BIO phải được tính trên
``tref.norm`` bằng ĐÚNG tokenizer và ĐÚNG offset mà
:class:`smart_medic.stages.neural.NeuralExtractor` dùng lúc inference. JSON lưu
position trên ``raw``; nếu train trên raw mà infer trên norm thì model học một
phân phối span khác với phân phối được chấm — và sai kiểu đó KHÔNG ném
exception, nó chỉ làm điểm thấp. Vì vậy ``raw_to_norm_span()`` ở dưới là đoạn
code đáng soi kỹ nhất, không phải vòng lặp train.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.fileset import parse_file_selector  # noqa: E402
from smart_medic.modelstore import write_manifest  # noqa: E402
from smart_medic.schema import ConceptType  # noqa: E402
from smart_medic.textref import TextRef, build_textref  # noqa: E402

DEFAULT_BASE = "xlm-roberta-base"

#: 6/20 file gold GIỮ LẠI, không đưa vào train — dùng để so v3 với v4 cho công bằng.
#:
#: Vì sao phải có: ``data/test/``, ``data/silver_prompts/`` và ``data/dev_gold/``
#: là **cùng một tập file**. Nhãn bạc là pseudo-label cho chính tập test, và
#: trước đây không có chỗ nào tách holdout. Nên "v4 > v3 trên gold" là phép so
#: không công bằng: v4 đã train trên đúng 20 file gold đó, v3 thì chưa — con số
#: sẽ đẹp, và phần đẹp lên có thể chỉ là ghi nhớ.
#:
#: Chọn 6 file này để **phản chiếu đúng phân tầng của tập dev** (xem
#: docs/reports/2026-07-25-phan-tich-du-lieu.md §thiết kế), không phải lấy bừa
#: hay lấy 6 file đầu:
#:
#:   thể loại  ghi chú lâm sàng 2 · hỏi đáp bệnh nhân 3 · giáo dục/khác 1
#:             (dev là 8 : 9 : 3 — cùng tỉ lệ)
#:   NFD       2/6 = 33%   (dev 6/20 = 30%)
#:   token che 2/6 = 33%   (dev 7/20 = 35%)
#:
#: NFD và token che PHẢI có mặt: chúng là hai chỗ đã gây lỗi thật (position lệch
#: âm thầm, và mất hoạt chất để map RxNorm). Một holdout toàn file NFC sạch sẽ
#: báo "ổn" ngay cả khi hai lớp lỗi đó quay lại.
HOLDOUT_FILES: tuple[int, ...] = (12, 16, 25, 26, 31, 42)


def bio_labels() -> list[str]:
    """``O`` trước, rồi B-/I- cho 5 ConceptType. Thứ tự này ĐI VÀO artifact."""
    out = ["O"]
    for ctype in ConceptType:
        out.extend((f"B-{ctype.value}", f"I-{ctype.value}"))
    return out


def raw_to_norm_span(tref: TextRef, rs: int, re_: int) -> tuple[int, int] | None:
    """Ánh xạ [rs, re_) trên raw về [ns, ne) trên norm.

    ``TextRef`` chỉ mang chiều norm→raw (đó là chiều mà pipeline cần). Ở đây ta
    cần chiều ngược để dựng nhãn train. Không thêm map mới vào TextRef — nó là
    tầng nền có test riêng và không nên phình ra vì nhu cầu dev-time; thay vào
    đó quét chính ``n2r``/``n2r_end`` đã có, nên hai chiều không thể lệch nhau.
    """
    ns = ne = None
    for index in range(len(tref.norm)):
        if ns is None and tref.n2r[index] >= rs:
            ns = index
        if tref.n2r_end[index] <= re_:
            ne = index + 1
        elif ns is not None:
            break
    if ns is None or ne is None or ns >= ne:
        return None
    return ns, ne


def encode_document(tokenizer, tref: TextRef, records: list[dict], label_index: dict[str, int]):
    """Một document → (input_ids, labels) theo BIO trên norm."""
    encoding = tokenizer(
        tref.norm,
        return_offsets_mapping=True,
        truncation=False,
        add_special_tokens=False,
    )
    offsets = encoding["offset_mapping"]
    labels = [label_index["O"]] * len(offsets)

    for record in records:
        rs, re_ = record["position"]
        mapped = raw_to_norm_span(tref, rs, re_)
        if mapped is None:
            continue
        ns, ne = mapped
        ctype = record["type"]
        first = True
        for index, (cs, ce) in enumerate(offsets):
            if ce <= cs:                      # token rỗng
                continue
            if cs >= ne or ce <= ns:          # ngoài span
                continue
            prefix = "B" if first else "I"
            labels[index] = label_index[f"{prefix}-{ctype}"]
            first = False
    return encoding["input_ids"], labels, offsets


def load_dataset(dirs: list[Path], input_dir: Path, tokenizer, label_index,
                 holdout: frozenset[str] = frozenset()):
    """Nạp mọi thư mục nhãn. Trùng file thì thư mục SAU thắng (gold > silver).

    ``holdout`` lọc theo TÊN FILE sau khi đã gộp, nên nó loại file khỏi **cả**
    silver lẫn gold. Lọc riêng từng thư mục thì không đủ: silver phủ file 1–100
    nên một file gold bị giữ lại vẫn sẽ lọt vào train qua đường nhãn bạc, và
    holdout coi như vô nghĩa mà không có dấu hiệu gì.
    """
    by_name: dict[str, list[dict]] = {}
    for d in dirs:
        if d is None or not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            if path.name in {"run_manifest.json", "explain.json"}:
                continue
            by_name[path.stem] = json.loads(path.read_text(encoding="utf-8"))

    for name in holdout & set(by_name):
        del by_name[name]

    samples = []
    for name, records in sorted(by_name.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 10**9):
        src = input_dir / f"{name}.txt"
        if not src.exists():
            continue
        tref = build_textref(src.read_text(encoding="utf-8"))
        ids, labels, _ = encode_document(tokenizer, tref, records, label_index)
        samples.append({"input_ids": ids, "labels": labels, "name": name})
    return samples


def chunk_sample(sample, max_length: int, stride: int, pad_id: int):
    """Cắt cửa sổ trượt giống hệt inference, chừa 2 chỗ cho <s>/</s>."""
    width = max_length - 2
    step = max(1, width - stride)
    ids, labels = sample["input_ids"], sample["labels"]
    out = []
    start = 0
    while start < len(ids):
        end = min(start + width, len(ids))
        out.append((ids[start:end], labels[start:end]))
        if end == len(ids):
            break
        start += step
    return out


def train(args) -> int:
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    torch.manual_seed(args.seed)                 # NFR3: tất định

    label_list = bio_labels()
    label_index = {name: i for i, name in enumerate(label_list)}

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    holdout = frozenset(str(n) for n in args.holdout)
    samples = load_dataset(
        [args.silver, args.gold], args.input, tokenizer, label_index, holdout
    )
    if holdout:
        print(f"  holdout {len(holdout)} file (KHÔNG train): "
              f"{', '.join(sorted(holdout, key=int))}")
    if not samples:
        print(
            "LỖI: không có dữ liệu train.\n"
            "Sinh nhãn bạc trước:\n"
            "  python3 scripts/preannotate_dev.py --emit-prompts data/silver_prompts --files 1-100",
            file=sys.stderr,
        )
        return 2

    pad_id = tokenizer.pad_token_id
    cls_id, sep_id = tokenizer.cls_token_id, tokenizer.sep_token_id
    windows = []
    for sample in samples:
        windows.extend(chunk_sample(sample, args.max_length, args.stride, pad_id))
    print(f"  {len(samples)} document → {len(windows)} cửa sổ train")

    def collate(batch):
        width = max(len(ids) for ids, _ in batch) + 2
        input_ids, attention, labels = [], [], []
        for ids, labs in batch:
            row = [cls_id, *ids, sep_id]
            lab = [-100, *labs, -100]           # -100 = bỏ qua trong loss
            pad = width - len(row)
            input_ids.append(row + [pad_id] * pad)
            attention.append([1] * len(row) + [0] * pad)
            labels.append(lab + [-100] * pad)
        return (
            torch.tensor(input_ids), torch.tensor(attention), torch.tensor(labels),
        )

    loader = DataLoader(
        windows, batch_size=args.batch_size, shuffle=True, collate_fn=collate,
        generator=torch.Generator().manual_seed(args.seed),
    )
    model = AutoModelForTokenClassification.from_pretrained(
        args.base_model,
        num_labels=len(label_list),
        id2label={i: name for i, name in enumerate(label_list)},
        label2id=label_index,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    model.train()
    for epoch in range(args.epochs):
        total = 0.0
        for input_ids, attention, labels in loader:
            optimizer.zero_grad()
            out = model(input_ids=input_ids, attention_mask=attention, labels=labels)
            out.loss.backward()
            optimizer.step()
            total += float(out.loss)
        print(f"  epoch {epoch + 1}/{args.epochs}  loss={total / max(1, len(loader)):.4f}")

    export_bundle(args, model, tokenizer, label_list)
    return 0


def export_bundle(args, model, tokenizer, label_list) -> None:
    import torch

    out_dir = args.export
    out_dir.mkdir(parents=True, exist_ok=True)
    model.eval()

    # Tokenizer nhanh (Rust) lưu ra tokenizer.json — runtime chỉ cần wheel
    # `tokenizers`, KHÔNG cần transformers + sentencepiece + protobuf. Đây đúng
    # chỗ đã vỡ ở lần thử SapBERT trước (PRD tab 04 §6).
    tokenizer.backend_tokenizer.save(str(out_dir / "tokenizer.json"))

    dummy_ids = torch.ones((1, 16), dtype=torch.long)
    dummy_mask = torch.ones((1, 16), dtype=torch.long)

    class Wrapper(torch.nn.Module):
        """Chỉ trả logits — ONNX không cần ModelOutput dict."""

        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_ids, attention_mask):
            return self.inner(input_ids=input_ids, attention_mask=attention_mask).logits

    torch.onnx.export(
        Wrapper(model),
        (dummy_ids, dummy_mask),
        str(out_dir / "ner.onnx"),
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

    manifest = write_manifest(
        out_dir,
        model_version=args.model_version,
        labels=label_list,
        base_model=args.base_model,
        max_length=args.max_length,
        stride=args.stride,
        extra={"seed": args.seed, "epochs": args.epochs},
    )
    print(f"\n✓ bundle → {out_dir}")
    for name, meta in sorted(manifest["artifacts"].items()):
        print(f"    {name:16} {meta['bytes'] / 1e6:>8.1f} MB  {meta['sha256'][:16]}…")
    print(
        "\n  Kiểm tra ngay:\n"
        "    PYTHONPATH=src python3 -m smart_medic.infer --extractor v4 "
        "--input data/test --output data/output --explain\n"
        "    PYTHONPATH=src python3 -m smart_medic.score --pred data/output "
        "--gold data/dev_gold --src data/test --verbose"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train + export bundle NER cho --extractor v4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--silver", type=Path, default=ROOT / "data/silver")
    parser.add_argument("--gold", type=Path, default=ROOT / "data/dev_gold",
                        help="ghi đè nhãn bạc khi trùng file")
    parser.add_argument("--input", type=Path, default=ROOT / "data/test")
    parser.add_argument("--export", type=Path, default=ROOT / "models")
    parser.add_argument("--base-model", default=DEFAULT_BASE,
                        help="ViMedNER đo được XLM-R > PhoBERT/ViHealthBERT, và "
                             "XLM-R chạy mức âm tiết nên không cần VnCoreNLP")
    parser.add_argument("--model-version", default="v4-xlmr-silver")
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--stride", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--holdout", default=",".join(str(n) for n in HOLDOUT_FILES),
                        help="file GIỮ LẠI khỏi train để chấm công bằng; "
                             "'' để train trên tất cả (khi đó đừng chấm trên gold)")
    args = parser.parse_args(argv)
    args.holdout = parse_file_selector(args.holdout) if args.holdout.strip() else ()

    try:
        return train(args)
    except ImportError as exc:
        print(
            f"LỖI: thiếu dependency dev-time: {exc}\n"
            "Cài: pip install -r requirements-dev.txt\n"
            "(Runtime nộp bài KHÔNG cần khối này — chỉ cần requirements.txt.)",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
