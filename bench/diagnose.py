"""Phân loại lỗi và oracle ablation — "điểm còn nằm ở đâu".

Hai công cụ:

``error_taxonomy``
    Chia mọi mention gold/pred vào các rổ lỗi *loại trừ nhau*. Rổ quan trọng
    nhất là **BOUNDARY**: gold không được ghép nhưng CÓ pred chồng lấn. Đó là
    lỗi *biên span*, không phải lỗi *phát hiện* — và hai loại này cần hai cách
    sửa hoàn toàn khác nhau (hậu xử lý nới biên vs. thêm dữ liệu huấn luyện).
    Nhánh v4.1 đo được 48/101 span sót thuộc rổ này.

``oracle_ablations``
    Lần lượt thay **một** trường bằng đáp án rồi chấm lại. Chênh lệch so với
    baseline là **trần điểm** của module tương ứng. Đây là cách duy nhất để
    biết nên bỏ hai tuần vào retrieval hay vào NER mà không phải đoán.

    Thang oracle được xếp theo mức "gian lận" tăng dần, nên đọc theo cột chênh
    lệch cộng dồn thì ra đúng bản đồ phân bổ công sức.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from .matching import MATCHERS, iou
from .metric import CorpusScores, score_corpus, wer


# ── phân loại lỗi ─────────────────────────────────────────────────────────────


@dataclass
class Taxonomy:
    counts: dict[str, int] = field(default_factory=lambda: collections.Counter())
    by_type: dict[str, dict[str, int]] = field(
        default_factory=lambda: collections.defaultdict(collections.Counter)
    )
    span_words_gold: list[int] = field(default_factory=list)
    span_words_pred: list[int] = field(default_factory=list)
    span_words_gold_by_type: dict[str, list[int]] = field(
        default_factory=lambda: collections.defaultdict(list)
    )
    span_words_pred_by_type: dict[str, list[int]] = field(
        default_factory=lambda: collections.defaultdict(list)
    )
    examples: dict[str, list[tuple[str, str, str]]] = field(
        default_factory=lambda: collections.defaultdict(list)
    )

    def add(self, bucket: str, ctype: str) -> None:
        self.counts[bucket] += 1
        self.by_type[ctype][bucket] += 1


def error_taxonomy(
    gold: dict[str, list[dict]],
    pred: dict[str, list[dict]],
    *,
    match: str = "greedy",
    max_examples: int = 8,
) -> Taxonomy:
    tax = Taxonomy()
    matcher = MATCHERS[match]

    for key in sorted(gold):
        g_list, p_list = gold[key], pred.get(key, [])
        pairs = matcher(g_list, p_list)

        for m in g_list:
            tax.span_words_gold.append(len(m["text"].split()))
            tax.span_words_gold_by_type[m["type"]].append(len(m["text"].split()))
        for m in p_list:
            tax.span_words_pred.append(len(m["text"].split()))
            tax.span_words_pred_by_type[m["type"]].append(len(m["text"].split()))

        for gi, pi in pairs:
            # ── gold bị bỏ sót ────────────────────────────────────────────────
            if pi is None:
                g = g_list[gi]
                overlapped = any(iou(g, p) > 0 for p in p_list)
                bucket = "MISS_BOUNDARY" if overlapped else "MISS_DETECT"
                tax.add(bucket, g["type"])
                if len(tax.examples[bucket]) < max_examples:
                    near = max((iou(g, p), p["text"]) for p in p_list) if p_list else (0, "")
                    tax.examples[bucket].append((key, g["text"], near[1]))
                continue
            # ── pred thừa ─────────────────────────────────────────────────────
            if gi is None:
                p = p_list[pi]
                overlapped = any(iou(g, p) > 0 for g in g_list)
                bucket = "SPUR_BOUNDARY" if overlapped else "SPUR_INVENT"
                tax.add(bucket, p["type"])
                if len(tax.examples[bucket]) < max_examples:
                    tax.examples[bucket].append((key, "", p["text"]))
                continue
            # ── cặp khớp: lỗi nội dung ────────────────────────────────────────
            g, p = g_list[gi], p_list[pi]
            if g["type"] != p["type"]:
                tax.add("TYPE_WRONG", g["type"])
                if len(tax.examples["TYPE_WRONG"]) < max_examples:
                    tax.examples["TYPE_WRONG"].append(
                        (key, f'{g["text"]} [{g["type"]}]', f'{p["text"]} [{p["type"]}]')
                    )
            if wer(g["text"], p["text"]) > 0:
                tax.add("TEXT_INEXACT", g["type"])
                if len(tax.examples["TEXT_INEXACT"]) < max_examples:
                    tax.examples["TEXT_INEXACT"].append((key, g["text"], p["text"]))
            gc, pc = set(g.get("candidates") or []), set(p.get("candidates") or [])
            if gc and not pc:
                tax.add("CAND_ABSTAIN", g["type"])
                if len(tax.examples["CAND_ABSTAIN"]) < max_examples:
                    tax.examples["CAND_ABSTAIN"].append((key, g["text"], "|".join(sorted(gc))))
            elif pc and not gc:
                tax.add("CAND_SPURIOUS", g["type"])
                if len(tax.examples["CAND_SPURIOUS"]) < max_examples:
                    tax.examples["CAND_SPURIOUS"].append((key, g["text"], "|".join(sorted(pc))))
            elif gc and pc and gc != pc:
                bucket = "CAND_PARTIAL" if gc & pc else "CAND_WRONG"
                tax.add(bucket, g["type"])
                if len(tax.examples[bucket]) < max_examples:
                    tax.examples[bucket].append(
                        (key, "|".join(sorted(gc)), "|".join(sorted(pc)))
                    )
            ga, pa = set(g.get("assertions") or []), set(p.get("assertions") or [])
            if ga != pa:
                bucket = "ASSERT_MISS" if ga - pa else "ASSERT_OVER"
                tax.add(bucket, g["type"])
                if len(tax.examples[bucket]) < max_examples:
                    tax.examples[bucket].append(
                        (key, "|".join(sorted(ga)) or "∅", "|".join(sorted(pa)) or "∅")
                    )
        tax.add("_files", "_")
    return tax


# ── oracle ablation ───────────────────────────────────────────────────────────


def _clone(mentions: list[dict]) -> list[dict]:
    return [dict(m) for m in mentions]


def _apply_oracle(
    gold: list[dict], pred: list[dict], fields: tuple[str, ...], match: str
) -> list[dict]:
    """Copy giá trị gold vào pred cho các cặp ĐÃ ghép được.

    Cố ý **không** thêm mention mới: oracle này đo trần của một module với độ
    phủ hiện tại, tách bạch khỏi câu hỏi recall (đã có oracle riêng cho nó).
    """
    out = _clone(pred)
    for gi, pi in MATCHERS[match](gold, pred):
        if gi is None or pi is None:
            continue
        for f in fields:
            if f == "text":
                out[pi]["text"] = gold[gi]["text"]
                out[pi]["position"] = list(gold[gi]["position"])
            else:
                out[pi][f] = gold[gi].get(f, [] if f != "type" else out[pi]["type"])
    return out


ORACLES: dict[str, tuple[str, ...]] = {
    "baseline": (),
    "+assertions": ("assertions",),
    "+candidates": ("candidates",),
    "+text (biên span)": ("text",),
    "+type": ("type",),
    "+tất cả trừ recall": ("text", "type", "assertions", "candidates"),
}


def oracle_ablations(
    gold: dict[str, list[dict]],
    pred: dict[str, list[dict]],
    *,
    match: str = "greedy",
) -> dict[str, CorpusScores]:
    out: dict[str, CorpusScores] = {}
    for name, fields in ORACLES.items():
        patched = {
            k: _apply_oracle(gold[k], pred.get(k, []), fields, match) for k in gold
        }
        out[name] = score_corpus(gold, patched, match=match)
    # bỏ mọi mention thừa, giữ nguyên phần còn lại — trần của tầng LỌC
    kept = {}
    for k in gold:
        pairs = MATCHERS[match](gold[k], pred.get(k, []))
        keep_idx = {pi for gi, pi in pairs if gi is not None and pi is not None}
        kept[k] = [m for i, m in enumerate(pred.get(k, [])) if i in keep_idx]
    out["+precision (bỏ pred thừa)"] = score_corpus(gold, kept, match=match)

    # bổ sung mọi gold còn thiếu, giữ nguyên phần thừa — trần của tầng PHÁT HIỆN
    filled = {}
    for k in gold:
        pairs = MATCHERS[match](gold[k], pred.get(k, []))
        extra = [dict(gold[k][gi]) for gi, pi in pairs if pi is None and gi is not None]
        filled[k] = _clone(pred.get(k, [])) + extra
    out["+recall (thêm gold thiếu)"] = score_corpus(gold, filled, match=match)

    # trần tuyệt đối
    out["= gold (mọi thứ hoàn hảo)"] = score_corpus(gold, gold, match=match)
    return out


def recall_sweep(
    gold: dict[str, list[dict]],
    pred: dict[str, list[dict]],
    *,
    match: str = "greedy",
    steps: int = 11,
    seed: int = 20260728,
) -> list[tuple[float, float]]:
    """Bơm dần mention gold còn thiếu vào pred để vẽ đường *điểm theo recall*.

    Cho biết **hình dạng** đường cong, không chỉ hai đầu mút: nếu nó lồi thì
    những cải tiến recall đầu tiên rẻ mà ăn nhiều điểm; nếu lõm thì ngược lại.
    """
    import random

    rng = random.Random(seed)
    missing: list[tuple[str, dict]] = []
    for k in gold:
        pairs = MATCHERS[match](gold[k], pred.get(k, []))
        for gi, pi in pairs:
            if pi is None and gi is not None:
                missing.append((k, gold[k][gi]))
    rng.shuffle(missing)

    out = []
    for step in range(steps):
        frac = step / (steps - 1)
        take = int(round(frac * len(missing)))
        patched = {k: _clone(pred.get(k, [])) for k in gold}
        for k, m in missing[:take]:
            patched[k].append(dict(m))
        s = score_corpus(gold, patched, match=match)
        out.append((frac, s.final))
    return out
