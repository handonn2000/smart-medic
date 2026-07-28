#!/usr/bin/env python3
"""Score a prediction directory under every unconfirmed reading of the metric.

Vì sao script này tồn tại: công thức chính thức của BTC được trích từ một tấm
ảnh và tự mâu thuẫn — chấm một bộ dự đoán hoàn hảo chỉ ra 0,336 thay vì 1,0.
``score.py`` để ba chỗ mập mờ sau cờ dòng lệnh:

    --match     overlap | order | text   ghép mention pred↔gold thế nào
    --wer       mean | joint             WER per-mention hay gộp cả file
    --unmatched zero | skip              mention thừa/thiếu bị phạt hay bỏ qua

Chênh lệch giữa các cách hiểu lên tới 0,27 điểm — đủ để đảo thứ hạng. Không thể
tuning gì có ý nghĩa khi chưa biết mình đang tối ưu hàm nào.

Script này chấm CÙNG một cặp thư mục dưới cả 12 tổ hợp và in bảng so sánh, để
kiểm chứng một giả thuyết cụ thể (báo cáo v4 §1.2):

    Điểm leaderboard 21,5450 chỉ giải thích được nếu mention không ghép được
    bị tính ZERO. Dưới ``--unmatched skip`` chính output đó phải ra ~88.

Nếu bảng dưới cho `skip` ≫ `zero` trên gold dev thật, giả thuyết đó được củng cố
và chiến lược đúng là recall-first, không phải precision-first.

Dùng:
    PYTHONPATH=src python3 scripts/metric_sweep.py \
        --pred data/output --gold data/dev_gold

    # so sánh hai artifact dưới cùng một cách đọc metric
    PYTHONPATH=src python3 scripts/metric_sweep.py \
        --pred data/output --gold data/dev_gold --per-file
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from smart_medic.score import W_ASSERT, W_CAND, W_TEXT, score_file  # noqa: E402

MATCH_MODES = ("overlap", "order", "text")
WER_MODES = ("mean", "joint")
UNMATCHED_MODES = ("zero", "skip")

#: Các file report do infer sinh ra, không phải submission — bỏ qua khi nạp.
NON_RECORD_FILES = frozenset({"run_manifest.json", "explain.json"})


def load_dir(directory: Path) -> dict[str, list[dict]]:
    """Nạp {stem: records}. Giống ``score._load`` nhưng báo lỗi rõ hơn."""
    out: dict[str, list[dict]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name in NON_RECORD_FILES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ⚠ bỏ qua {path.name}: JSON hỏng ({exc})", file=sys.stderr)
            continue
        if isinstance(data, list):
            out[path.stem] = data
    return out


def sweep(gold: dict[str, list[dict]], pred: dict[str, list[dict]],
          keys: list[str]) -> list[dict]:
    """Chấm mọi tổ hợp trên đúng phần giao của hai thư mục."""
    rows: list[dict] = []
    for match in MATCH_MODES:
        for wer_mode in WER_MODES:
            for unmatched in UNMATCHED_MODES:
                per = [
                    score_file(gold[k], pred[k], match=match,
                               wer_mode=wer_mode, unmatched=unmatched)
                    for k in keys
                ]
                mean = lambda field: sum(p[field] for p in per) / len(per)  # noqa: E731
                text, assertions, candidates = (
                    mean("text"), mean("assertions"), mean("candidates")
                )
                rows.append(
                    {
                        "match": match,
                        "wer": wer_mode,
                        "unmatched": unmatched,
                        "text": text,
                        "assertions": assertions,
                        "candidates": candidates,
                        "final": W_TEXT * text + W_ASSERT * assertions + W_CAND * candidates,
                        "n_gold": sum(p["n_gold"] for p in per),
                        "n_pred": sum(p["n_pred"] for p in per),
                        "n_matched": sum(p["n_matched"] for p in per),
                    }
                )
    return rows


def _sort_key(stem: str) -> tuple[int, str]:
    return (int(stem), "") if stem.isdigit() else (10**9, stem)


def print_table(rows: list[dict]) -> None:
    print(f"  {'match':<8} {'wer':<6} {'unmatched':<10} "
          f"{'text':>7} {'assert':>7} {'cand':>7} {'final':>8} {'×100':>8}")
    print(f"  {'─' * 72}")
    last_match = None
    for row in rows:
        if last_match is not None and row["match"] != last_match:
            print(f"  {'·' * 72}")
        last_match = row["match"]
        print(
            f"  {row['match']:<8} {row['wer']:<6} {row['unmatched']:<10} "
            f"{row['text']:>7.4f} {row['assertions']:>7.4f} {row['candidates']:>7.4f} "
            f"{row['final']:>8.4f} {row['final'] * 100:>8.2f}"
        )


def print_hypothesis(rows: list[dict], leaderboard: float | None) -> None:
    """So sánh zero↔skip — lý do chính script này tồn tại."""
    zero = next(r for r in rows
                if r["match"] == "overlap" and r["wer"] == "mean" and r["unmatched"] == "zero")
    skip = next(r for r in rows
                if r["match"] == "overlap" and r["wer"] == "mean" and r["unmatched"] == "skip")

    print(f"\n  Giả thuyết trung tâm — mention không ghép được bị phạt hay không?")
    print(f"  {'─' * 72}")
    print(f"  gold {zero['n_gold']} mention · pred {zero['n_pred']} · "
          f"ghép {zero['n_matched']}")
    if zero["n_gold"]:
        print(f"  recall    = {zero['n_matched'] / zero['n_gold']:.1%}")
    if zero["n_pred"]:
        print(f"  precision = {zero['n_matched'] / zero['n_pred']:.1%}")
    print(f"\n  --unmatched zero (phạt) : {zero['final'] * 100:>7.2f}")
    print(f"  --unmatched skip  (bỏ)  : {skip['final'] * 100:>7.2f}")
    print(f"  chênh lệch              : {(skip['final'] - zero['final']) * 100:>7.2f} điểm")

    if leaderboard is not None:
        d_zero = abs(zero["final"] * 100 - leaderboard)
        d_skip = abs(skip["final"] * 100 - leaderboard)
        closer = "zero" if d_zero <= d_skip else "skip"
        print(f"\n  leaderboard thật        : {leaderboard:>7.2f}")
        print(f"  |zero − leaderboard|    : {d_zero:>7.2f}")
        print(f"  |skip − leaderboard|    : {d_skip:>7.2f}")
        print(f"  → cách đọc gần thực tế hơn: --unmatched {closer}")
        print("\n  Cảnh báo: dev set 20 file không cùng phân phối với private test;"
              "\n  đây là bằng chứng gián tiếp, không phải xác nhận của BTC.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sweep mọi cách đọc metric trên cùng một cặp pred/gold",
    )
    parser.add_argument("--pred", type=Path, default=ROOT / "data/output")
    parser.add_argument("--gold", type=Path, default=ROOT / "data/dev_gold")
    parser.add_argument("--leaderboard", type=float, default=None,
                        help="điểm leaderboard thật để đối chiếu, ví dụ 21.5450")
    parser.add_argument("--per-file", action="store_true",
                        help="in thêm chi tiết từng file dưới cách đọc mặc định")
    parser.add_argument("--json", type=Path, default=None,
                        help="ghi toàn bộ bảng ra JSON")
    args = parser.parse_args(argv)

    if not args.gold.is_dir():
        print(f"LỖI: không có thư mục gold {args.gold}", file=sys.stderr)
        return 2
    if not args.pred.is_dir():
        print(f"LỖI: không có thư mục pred {args.pred}", file=sys.stderr)
        return 2

    gold, pred = load_dir(args.gold), load_dir(args.pred)
    keys = sorted(set(gold) & set(pred), key=_sort_key)
    if not keys:
        print("LỖI: pred và gold không có file nào chung", file=sys.stderr)
        return 2

    # Gold dev thường ÍT file hơn output (20 vs 100) — chấm phần giao và nói rõ.
    only_gold = sorted(set(gold) - set(pred), key=_sort_key)
    only_pred = sorted(set(pred) - set(gold), key=_sort_key)
    print(f"\n  chấm {len(keys)} file chung: {', '.join(keys)}")
    if only_pred:
        print(f"  bỏ qua {len(only_pred)} file chỉ có trong pred (không có gold)")
    if only_gold:
        print(f"  ⚠ {len(only_gold)} file chỉ có trong gold, thiếu pred: "
              f"{', '.join(only_gold)}")
    print()

    rows = sweep(gold, pred, keys)
    print_table(rows)
    print_hypothesis(rows, args.leaderboard)

    if args.per_file:
        print(f"\n  Chi tiết từng file (match=overlap, wer=mean, unmatched=zero)")
        print(f"  {'─' * 72}")
        print(f"  {'file':>5} {'gold':>5} {'pred':>5} {'khớp':>5} "
              f"{'text':>7} {'assert':>7} {'cand':>7} {'final':>8}")
        for k in keys:
            r = score_file(gold[k], pred[k])
            final = W_TEXT * r["text"] + W_ASSERT * r["assertions"] + W_CAND * r["candidates"]
            print(f"  {k:>5} {r['n_gold']:>5} {r['n_pred']:>5} {r['n_matched']:>5} "
                  f"{r['text']:>7.4f} {r['assertions']:>7.4f} {r['candidates']:>7.4f} "
                  f"{final:>8.4f}")

    if args.json:
        args.json.write_text(
            json.dumps({"files": keys, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n  → {args.json}")

    print("\n  Lưu ý: công thức chính thức chưa được BTC xác nhận. Bảng này đo "
          "\n  ĐỘ NHẠY của kết luận với cách đọc metric, không phải điểm thật.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
