"""Huấn luyện token classification BIO trên corpus tổng hợp.

★ BỐN QUYẾT ĐỊNH, MỖI CÁI CÓ LÝ DO ĐO ĐƯỢC
───────────────────────────────────────────
1. **Base là XLM-R, không phải PhoBERT.** ViMedNER cho thấy XLM-R nhìn chung
   vượt PhoBERT/ViHealthBERT trên NER y khoa tiếng Việt, và nó chạy
   syllable-level nên **không cần tách từ VnCoreNLP** — bước mà làm sai là nguồn
   lỗi phổ biến nhất khi dùng PhoBERT (PRD §4).

2. **Ghim `revision`, không dùng `"main"`.** PRD §5: BTC cài lại không được thì
   bị loại. `"main"` là nhãn di động — cùng câu lệnh, sáu tháng sau ra weights
   khác.

3. **Dev là tài liệu TỔNG HỢP.** Chọn epoch hay dò ngưỡng trên `gold_real` là
   làm hỏng chính cái cổng dùng để quyết định (quy tắc §5.7). Module này **không
   được phép** đọc `data/probe/gold_real` — không có đường dẫn nào tới đó.

4. **Ghi `sha256` corpus vào metadata checkpoint.** Không có nó thì sáu tháng sau
   không ai biết weights này huấn luyện trên corpus nào.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from smart_medic.kb.config import DATA_DIR
from smart_medic.stages.bio import IGNORE_ID, LABELS
from smart_medic.train import dataset

BASE_MODEL = "xlm-roberta-base"
# Ghim cứng. Xem quyết định 2 ở docstring.
BASE_REVISION = "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"
SEED = 20260802
CORPUS_DIR = DATA_DIR / "synth" / "v1"
OUT_DIR = DATA_DIR / "artifacts" / "tagger" / "v1"


@dataclass(slots=True)
class TrainConfig:
    epochs: int = 3
    batch_size: int = 8
    lr: float = 3e-5
    max_train_windows: int | None = None


def _set_seed(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _device():
    import torch

    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _collate(batch, pad_id: int):
    import torch

    n = max(len(b.input_ids) for b in batch)
    ids, mask, lab = [], [], []
    for b in batch:
        k = n - len(b.input_ids)
        ids.append(b.input_ids + [pad_id] * k)
        mask.append(b.attention_mask + [0] * k)
        lab.append(b.labels + [IGNORE_ID] * k)
    return (
        torch.tensor(ids),
        torch.tensor(mask),
        torch.tensor(lab),
    )


def evaluate(model, windows, tokenizer, device, batch_size: int = 16) -> dict:
    """F1 span trên dev TỔNG HỢP. Ghép span theo tài liệu, dùng lại bộ chấm thật."""
    import torch

    from smart_medic.stages.bio import tags_to_spans, transition_mask, viterbi
    from smart_medic.stages.scoring import Entity, Report, score_document

    model.eval()
    mask_t = transition_mask()
    by_doc: dict[str, tuple[list[Entity], list[Entity]]] = {}
    docs = dataset.load_corpus(CORPUS_DIR, sorted({w.doc for w in windows}, key=int))
    text_of = {name: text for name, text, _ in docs}
    gold_of = {name: spans for name, _, spans in docs}

    for i in range(0, len(windows), batch_size):
        chunk = windows[i : i + batch_size]
        ids, att, _ = _collate(chunk, tokenizer.pad_token_id)
        with torch.no_grad():
            logits = model(input_ids=ids.to(device), attention_mask=att.to(device)).logits
        logp = torch.log_softmax(logits, dim=-1).cpu().tolist()
        for w, row in zip(chunk, logp, strict=False):
            n = len(w.input_ids)
            pred = tags_to_spans(text_of[w.doc], w.offsets, viterbi(row[:n], mask_t))
            g, p = by_doc.setdefault(w.doc, (gold_of[w.doc], []))
            p.extend(pred)

    rep = Report()
    for name, (g, p) in by_doc.items():
        merged = sorted({(e.start, e.end, e.type) for e in p})
        pred = [Entity(text_of[name][s:e], t, s, e) for s, e, t in merged]
        rep.docs.append(score_document(g, pred, name=name))
    return {
        "span_f1": round(rep.f1, 4),
        "span_precision": round(rep.precision, 4),
        "span_recall": round(rep.recall, 4),
        "type_accuracy": round(rep.type_accuracy, 4),
        "n_docs": len(rep.docs),
    }


def run(cfg: TrainConfig | None = None, *, out_dir: Path | None = None) -> dict:
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    cfg = cfg or TrainConfig()
    out = out_dir or OUT_DIR
    _set_seed(SEED)
    device = _device()

    tok = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REVISION, use_fast=True)
    splits = dataset.read_splits(CORPUS_DIR)
    train_w = dataset.build(CORPUS_DIR, tok, splits["train"])
    dev_w = dataset.build(CORPUS_DIR, tok, splits["dev"])
    if cfg.max_train_windows:
        train_w = train_w[: cfg.max_train_windows]
    print(f"  train {len(train_w)} cửa sổ · dev {len(dev_w)} cửa sổ · thiết bị {device}")

    model = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL,
        revision=BASE_REVISION,
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id={lab: i for i, lab in enumerate(LABELS)},
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr)

    rng = random.Random(SEED)
    history = []
    for ep in range(1, cfg.epochs + 1):
        model.train()
        order = list(range(len(train_w)))
        rng.shuffle(order)
        total = 0.0
        for i in range(0, len(order), cfg.batch_size):
            batch = [train_w[j] for j in order[i : i + cfg.batch_size]]
            ids, att, lab = _collate(batch, tok.pad_token_id)
            loss = model(
                input_ids=ids.to(device), attention_mask=att.to(device), labels=lab.to(device)
            ).loss
            loss.backward()
            opt.step()
            opt.zero_grad()
            total += loss.item()
        metrics = evaluate(model, dev_w, tok, device)
        metrics["epoch"] = ep
        metrics["train_loss"] = round(total / max(1, len(order) // cfg.batch_size), 4)
        history.append(metrics)
        print(f"  epoch {ep}: loss {metrics['train_loss']} · dev F1 {metrics['span_f1']}")

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    meta = {
        "base_model": BASE_MODEL,
        "base_revision": BASE_REVISION,
        "seed": SEED,
        "labels": list(LABELS),  # thứ tự nhãn — `tagger.load` kiểm lại khi nạp
        "corpus_sha256": manifest["corpus_sha256"],
        "corpus_dir": str(CORPUS_DIR),
        "config": {"epochs": cfg.epochs, "batch_size": cfg.batch_size, "lr": cfg.lr},
        "history": history,
        "dev": history[-1] if history else {},
        "threshold": 0.0,
    }
    (out / "smk_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta
