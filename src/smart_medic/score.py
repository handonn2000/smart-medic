"""score.py — chấm điểm nội bộ.

    final = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score

CẢNH BÁO ĐỌC TRƯỚC KHI DÙNG. Bốn chi tiết của công thức chính thức CHƯA được
BTC xác nhận (xem PRD tab 06 §6). Script này hiện thực cách hiểu hợp lý nhất và
để các cách hiểu khác sau cờ dòng lệnh:

  * ghép mention pred↔gold thế nào?  → --match overlap|order|text
  * WER tính per-mention hay gộp?     → --wer mean|joint
  * mention thừa/thiếu phạt ra sao?   → --unmatched zero|skip

ĐỪNG tuning tham số để tối đa hóa con số của chính script này trước khi BTC
chốt công thức. Nó là thước đo tương đối để so v0 với v1, không phải điểm thật.

Dùng:
    python -m smart_medic.score --pred data/output --gold data/gold
    python -m smart_medic.score --pred data/output --gold data/output   # validate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .schema import validate_file

ROOT = Path(__file__).resolve().parents[2]
W_TEXT, W_ASSERT, W_CAND = 0.3, 0.3, 0.4


# ── số học ────────────────────────────────────────────────────────────────────


def wer(ref: str, hyp: str) -> float:
    """Word Error Rate = (thêm + bớt + thay) / số từ đáp án."""
    r, h = ref.split(), hyp.split()
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def jaccard(a, b) -> float:
    """Quy ước của đề: cả hai rỗng → J = 1."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


# ── ghép mention ──────────────────────────────────────────────────────────────


def _iou(a: dict, b: dict) -> float:
    (s1, e1), (s2, e2) = a["position"], b["position"]
    inter = max(0, min(e1, e2) - max(s1, s2))
    union = max(e1, e2) - min(s1, s2)
    return inter / union if union else 0.0


def pair(gold: list[dict], pred: list[dict], mode: str) -> list[tuple[dict | None, dict | None]]:
    if mode == "order":
        n = max(len(gold), len(pred))
        return [
            (gold[i] if i < len(gold) else None, pred[i] if i < len(pred) else None)
            for i in range(n)
        ]
    if mode == "text":
        rest = list(pred)
        out: list[tuple[dict | None, dict | None]] = []
        for g in gold:
            hit = next((p for p in rest if p["text"] == g["text"]), None)
            if hit:
                rest.remove(hit)
            out.append((g, hit))
        out.extend((None, p) for p in rest)
        return out

    # overlap (mặc định): greedy theo IoU giảm dần
    scored = sorted(
        ((_iou(g, p), gi, pi) for gi, g in enumerate(gold) for pi, p in enumerate(pred)),
        key=lambda x: -x[0],
    )
    used_g: set[int] = set()
    used_p: set[int] = set()
    out = []
    for iou, gi, pi in scored:
        if iou <= 0 or gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        out.append((gold[gi], pred[pi]))
    out.extend((g, None) for i, g in enumerate(gold) if i not in used_g)
    out.extend((None, p) for i, p in enumerate(pred) if i not in used_p)
    return out


# ── chấm một file ─────────────────────────────────────────────────────────────


def score_file(gold: list[dict], pred: list[dict], *, match="overlap",
               wer_mode="mean", unmatched="zero") -> dict:
    if wer_mode == "joint":
        t_score = 1.0 - min(
            1.0,
            wer(" ".join(g["text"] for g in gold), " ".join(p["text"] for p in pred)),
        )
    else:
        t_score = None

    pairs = pair(gold, pred, match)
    ts, as_, cs = [], [], []
    for g, p in pairs:
        if g is None or p is None:
            if unmatched == "skip":
                continue
            ts.append(0.0)
            as_.append(0.0)
            cs.append(0.0)
            continue
        ts.append(1.0 - min(1.0, wer(g["text"], p["text"])))
        as_.append(jaccard(g.get("assertions", []), p.get("assertions", [])))
        cs.append(jaccard(g.get("candidates", []), p.get("candidates", [])))

    mean = lambda v: sum(v) / len(v) if v else 1.0   # noqa: E731
    if t_score is None:
        t_score = mean(ts)
    return {
        "text": t_score, "assertions": mean(as_), "candidates": mean(cs),
        "n_gold": len(gold), "n_pred": len(pred),
        "n_matched": sum(1 for g, p in pairs if g and p),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _load(d: Path) -> dict[str, list[dict]]:
    out = {}
    for f in sorted(d.glob("*.json")):
        if f.name in {"run_manifest.json", "explain.json"}:
            continue
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chấm điểm nội bộ Smart Medic")
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--src", type=Path, default=None,
                    help="thư mục .txt gốc để verify position")
    ap.add_argument("--match", default="overlap", choices=["overlap", "order", "text"])
    ap.add_argument("--wer", default="mean", choices=["mean", "joint"])
    ap.add_argument("--unmatched", default="zero", choices=["zero", "skip"])
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    gold, pred = _load(args.gold), _load(args.pred)
    keys = sorted(set(gold) | set(pred), key=lambda k: (int(k), "") if k.isdigit() else (10**9, k))
    if not keys:
        print("LỖI: không có file nào để chấm", file=sys.stderr)
        return 2

    # -- validate schema + verify position --
    errs: list[str] = []
    for k in sorted(pred):
        raw = None
        if args.src:
            p = args.src / f"{k}.txt"
            if p.exists():
                raw = p.read_text(encoding="utf-8")
        errs.extend(f"{k}.json {e}" for e in validate_file(pred[k], raw))

    per, missing = [], []
    for k in keys:
        if k not in gold or k not in pred:
            missing.append(k)
            continue
        r = score_file(gold[k], pred[k], match=args.match,
                       wer_mode=args.wer, unmatched=args.unmatched)
        r["file"] = k
        per.append(r)
        if args.verbose:
            print(f"  {k:>4}  text={r['text']:.4f}  assert={r['assertions']:.4f}  "
                  f"cand={r['candidates']:.4f}  ({r['n_matched']}/{r['n_gold']} khớp)")

    if not per:
        print("LỖI: không cặp file nào khớp giữa pred và gold", file=sys.stderr)
        return 2

    m = lambda key: sum(p[key] for p in per) / len(per)   # noqa: E731
    t, a, c = m("text"), m("assertions"), m("candidates")
    final = W_TEXT * t + W_ASSERT * a + W_CAND * c

    print(f"\n  files          : {len(per)}" + (f"  (thiếu {len(missing)})" if missing else ""))
    print(f"  text_score       ×0.3 : {t:.4f}")
    print(f"  assertions_score ×0.3 : {a:.4f}")
    print(f"  candidates_score ×0.4 : {c:.4f}")
    print(f"  {'─' * 34}")
    print(f"  FINAL_SCORE           : {final:.4f}")
    print(f"\n  Schema {'OK' if not errs else f'✗ {len(errs)} LỖI'}"
          f"{' (đã verify position)' if args.src else ''}")
    for e in errs[:15]:
        print(f"    {e}", file=sys.stderr)
    print("\n  Lưu ý: công thức chính thức chưa được BTC xác nhận — "
          "đây là thước đo TƯƠNG ĐỐI giữa các phiên bản.")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
