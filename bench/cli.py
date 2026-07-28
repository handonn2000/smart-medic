"""CLI benchmark.

    python3 -m bench selftest                      # kiểm chứng chính benchmark
    python3 -m bench score   --pred DIR [--pred DIR2 ...]
    python3 -m bench compare --pred A --pred B     # A/B kèm p-value
    python3 -m bench diagnose --pred DIR           # điểm mất ở đâu
    python3 -m bench policy                        # ngưỡng tối ưu theo metric
    python3 -m bench simulate                      # bảng hệ giả lập tham chiếu
    python3 -m bench corpus  --corpus NAME:ANN:TXT # thẩm định một tập nhãn mới
    python3 -m bench robust  --pred DIR            # chẩn đoán có bền qua các gold không

Gold mặc định là ``data/dev_gold_consensus``. Mọi lệnh nhận ``--json OUT`` để
ghi kết quả máy đọc được, dùng cho CI hoặc dựng biểu đồ.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .decision import (
    best_candidate_set,
    emission_threshold,
    empty_rate_by_type,
    gold_set_sizes,
)
from .degrade import PROFILES, degrade
from .diagnose import error_taxonomy, oracle_ablations, recall_sweep
from .metric import decompose, score_corpus
from .stats import bootstrap_ci, mde, paired_permutation

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "data" / "dev_gold_consensus"
SKIP = {"run_manifest.json", "explain.json"}


def load_dir(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in sorted(path.glob("*.json")):
        if f.name in SKIP:
            continue
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    if not out:
        raise SystemExit(f"LỖI: không có .json nào trong {path}")
    return out


def _restrict(gold, pred, *, label="pred"):
    """Chỉ chấm trên các file gold có mặt — pred có thể phủ cả 100 file test.

    File gold mà pred thiếu VẪN được chấm (như pred rỗng): bỏ qua chúng sẽ
    thưởng cho hệ nào crash trên file khó. Nhưng nếu **không file nào** giao
    nhau thì đó không phải điểm 0, đó là dùng sai lệnh — thường là chấm output
    của ``data/test`` với gold của một corpus khác. Báo lỗi thay vì in 0,0000.
    """
    common = set(gold) & set(pred)
    if not common:
        raise SystemExit(
            f"LỖI: {label} không có file nào trùng tên với gold.\n"
            f"  gold: {len(gold)} file, ví dụ {sorted(gold)[:3]}\n"
            f"  {label}: {len(pred)} file, ví dụ {sorted(pred)[:3]}\n"
            f"  Tập nhãn sinh là các TÀI LIỆU MỚI — muốn chấm trên chúng thì phải "
            f"chạy inference trên thư mục text tương ứng trước."
        )
    return gold, {k: v for k, v in pred.items() if k in gold}


def _bar(value: float, width: int = 28, vmax: float = 1.0) -> str:
    filled = int(round(max(0.0, min(1.0, value / vmax)) * width))
    return "█" * filled + "·" * (width - filled)


# ── lệnh ──────────────────────────────────────────────────────────────────────


def cmd_score(args) -> int:
    gold = load_dir(args.gold)
    rows = []
    for path in args.pred:
        _, pred = _restrict(gold, load_dir(path), label=path.name)
        results = {}
        for match in ("greedy", "hungarian"):
            results[match] = score_corpus(gold, pred, match=match, unmatched=args.unmatched)
        corpus = results["greedy"]
        d = decompose(corpus)
        point, lo, hi = bootstrap_ci(
            corpus.per_file,
            lambda u: (
                0.3 * sum(x.text for x in u)
                + 0.3 * sum(x.assertions for x in u)
                + 0.4 * sum(x.candidates for x in u)
            )
            / len(u),
            seed=args.seed,
        )
        rows.append(
            {
                "name": path.name,
                "final": corpus.final,
                "ci": [lo, hi],
                "final_hungarian": results["hungarian"].final,
                "mde": mde(corpus.per_file, lambda u: sum(
                    0.3 * x.text + 0.3 * x.assertions + 0.4 * x.candidates for x in u) / len(u),
                    seed=args.seed),
                **d,
            }
        )

    print(f"\n  gold: {args.gold}  ({len(gold)} file, "
          f"{sum(len(v) for v in gold.values())} mention)\n")
    head = (f"  {'hệ thống':<26}{'final':>8}{'  KTC 95%':>18}{'hung.':>8}"
            f"{'q_pair':>8}{'phủ':>7}{'recall':>8}{'prec':>7}")
    print(head)
    print("  " + "─" * (len(head) - 2))
    for r in rows:
        print(f"  {r['name']:<26}{r['final']:>8.4f}"
              f"  [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}]"
              f"{r['final_hungarian']:>8.4f}{r['q_pair']:>8.3f}"
              f"{r['coverage']:>7.3f}{r['recall']:>8.1%}{r['precision']:>7.1%}")
    print()
    for r in rows:
        gap = abs(r["final"] - r["final_model"])
        print(f"  {r['name']}")
        print(f"    final = q_pair {r['q_pair']:.3f} × phủ {r['coverage']:.3f} "
              f"= {r['final_model']:.4f}   (thực đo {r['final']:.4f}, lệch {gap:.4f})")
        print(f"    q_text {r['q_text']:.3f} · q_assert {r['q_assert']:.3f} · "
              f"q_cand {r['q_cand']:.3f} · IoU cặp khớp {r['q_iou']:.3f}")
        print(f"    mật độ gold {r['density_gold']:.1f}/file · pred {r['density_pred']:.1f}/file"
              f" · MDE ±{r['mde']:.3f}")
        print(f"    ngưỡng phát mention tối ưu p* = {emission_threshold(r['final'], r['q_pair']):.3f}"
              f"   (ngưỡng F1 sẽ là 0.500)")
        print()
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {args.json}")
    return 0


def cmd_compare(args) -> int:
    if len(args.pred) != 2:
        raise SystemExit("compare cần đúng 2 --pred")
    gold = load_dir(args.gold)
    a_name, b_name = args.pred[0].name, args.pred[1].name
    _, a = _restrict(gold, load_dir(args.pred[0]), label=a_name)
    _, b = _restrict(gold, load_dir(args.pred[1]), label=b_name)
    keys = sorted(gold, key=lambda k: (int(k), "") if k.isdigit() else (10**9, k))
    sa = score_corpus(gold, a, keys=keys).per_file
    sb = score_corpus(gold, b, keys=keys).per_file

    agg = lambda u: sum(0.3 * x.text + 0.3 * x.assertions + 0.4 * x.candidates  # noqa: E731
                        for x in u) / len(u)
    diff, p = paired_permutation(sa, sb, agg, seed=args.seed)
    _, lo_a, hi_a = bootstrap_ci(sa, agg, seed=args.seed)
    _, lo_b, hi_b = bootstrap_ci(sb, agg, seed=args.seed)

    print(f"\n  {a_name:<26}{agg(sa):.4f}  [{lo_a:.3f}, {hi_a:.3f}]")
    print(f"  {b_name:<26}{agg(sb):.4f}  [{lo_b:.3f}, {hi_b:.3f}]")
    print(f"\n  chênh lệch (A − B) : {diff:+.4f}")
    print(f"  p-value hoán vị    : {p:.4f}   ({'CÓ' if p < 0.05 else 'CHƯA'} ý nghĩa ở α = 0,05)")
    wins = sum(1 for x, y in zip(sa, sb) if agg([x]) > agg([y]))
    print(f"  A thắng            : {wins}/{len(sa)} file")
    if p >= 0.05:
        print(f"\n  ⚠ Với {len(sa)} file, MDE ≈ ±{mde(sa, agg, seed=args.seed):.3f}. "
              "Chênh lệch nhỏ hơn mức đó không đọc được từ dev set này.")
    print()
    return 0


def cmd_diagnose(args) -> int:
    gold = load_dir(args.gold)
    _, pred = _restrict(gold, load_dir(args.pred[0]), label=args.pred[0].name)

    tax = error_taxonomy(gold, pred)
    print(f"\n── phân loại lỗi · {args.pred[0].name} ─────────────────────────────")
    labels = {
        "MISS_DETECT": "gold bỏ sót — KHÔNG có pred chồng lấn (lỗi phát hiện)",
        "MISS_BOUNDARY": "gold bỏ sót — CÓ pred chồng lấn (lỗi BIÊN SPAN)",
        "SPUR_INVENT": "pred thừa — không chồng lấn gold nào",
        "SPUR_BOUNDARY": "pred thừa — chồng lấn gold đã ghép nơi khác",
        "TEXT_INEXACT": "cặp khớp nhưng text lệch (mất điểm WER)",
        "TYPE_WRONG": "cặp khớp nhưng sai type",
        "CAND_ABSTAIN": "gold có mã, ta bỏ trắng (J = 0)",
        "CAND_SPURIOUS": "gold rỗng, ta gắn mã (J = 0)",
        "CAND_WRONG": "hai bên có mã, không giao nhau",
        "CAND_PARTIAL": "hai bên có mã, giao một phần",
        "ASSERT_MISS": "thiếu cờ assertion",
        "ASSERT_OVER": "thừa cờ assertion",
    }
    total_gold = sum(len(v) for v in gold.values())
    for k, label in labels.items():
        n = tax.counts.get(k, 0)
        if n:
            print(f"  {n:>5}  {n / total_gold:>6.1%}  {label}")
    print(f"\n  (mẫu số = {total_gold} mention gold)")

    def stats(v):
        return sum(v) / len(v) if v else 0.0

    print(f"\n  độ dài span trung bình  gold {stats(tax.span_words_gold):.2f} từ  ·  "
          f"pred {stats(tax.span_words_pred):.2f} từ  ·  "
          f"lệch {stats(tax.span_words_pred) - stats(tax.span_words_gold):+.2f}")
    for t in sorted(tax.span_words_gold_by_type):
        g = stats(tax.span_words_gold_by_type[t])
        p = stats(tax.span_words_pred_by_type.get(t, []))
        print(f"    {t:<22} gold {g:5.2f}  pred {p:5.2f}  lệch {p - g:+5.2f}")

    cols = {
        "MISS_BOUNDARY": ("gold bỏ sót", "pred chồng lấn gần nhất"),
        "MISS_DETECT": ("gold bỏ sót", "pred gần nhất (không chồng lấn)"),
        "CAND_ABSTAIN": ("mention", "mã gold ta đã bỏ trắng"),
        "TEXT_INEXACT": ("gold", "pred"),
    }
    for bucket, (la, lb) in cols.items():
        ex = tax.examples.get(bucket, [])
        if ex:
            print(f"\n  ví dụ · {bucket}   ({la}  →  {lb})")
            for f, g, p in ex[:6]:
                print(f"    [{f:>3}] {g!r:<50} → {p!r}")

    print("\n── oracle ablation (trần điểm mỗi module) ──────────────────────────")
    abl = oracle_ablations(gold, pred)
    base = abl["baseline"].final
    for name, corpus in abl.items():
        delta = corpus.final - base
        print(f"  {name:<28}{corpus.final:>8.4f}  {delta:>+8.4f}  {_bar(corpus.final)}")

    print("\n── điểm theo recall (bơm dần gold còn thiếu) ───────────────────────")
    for frac, value in recall_sweep(gold, pred, steps=args.steps):
        print(f"  +{frac:>5.0%} gold thiếu → {value:.4f}  {_bar(value)}")
    print()
    return 0


def cmd_policy(args) -> int:
    gold = load_dir(args.gold)
    print(f"\n── chính sách tối ưu suy ra từ metric · gold {args.gold.name} ──────\n")
    sizes = gold_set_sizes(gold)
    print(f"  phân phối |gold candidates| : {sizes}")
    if max(sizes) <= 1:
        print("  ⇒ gold KHÔNG BAO GIỜ có 2 mã. Mọi k ≥ 2 bị chi phối tuyệt đối bởi k = 1.")
        print("    Lời khuyên 'trả 1–2 mã khi lưỡng lự' làm GIẢM điểm trên gold này.\n")

    print("  ngưỡng phát mã theo type (phát top-1 khi p₁ vượt ngưỡng):")
    for policy in sorted(empty_rate_by_type(gold).values(), key=lambda x: -x.n):
        print(f"    {policy}")

    print("\n  ngưỡng phát MENTION p* = S/(q̄ + S), với q̄ = 0,85:")
    print(f"    {'điểm hiện tại S':<20}{'p* tối ưu':>12}   diễn giải")
    for s in (0.15, 0.2154, 0.30, 0.40, 0.5597, 0.70, 0.85):
        t = emission_threshold(s, 0.85)
        note = "phát gần như mọi thứ" if t < 0.25 else (
            "vẫn nới tay" if t < 0.40 else "bắt đầu cần lọc")
        print(f"    {s:<20.4f}{t:>12.3f}   {note}")
    print("    (ngưỡng tối ưu F1 là 0,500 ở MỌI mức điểm — đó là chỗ sai)")

    print("\n  ví dụ chọn k tối ưu bằng E[Jaccard] (xác suất đã hiệu chuẩn):")
    for probs in ([0.9, 0.05, 0.02], [0.5, 0.45, 0.03], [0.35, 0.3, 0.25], [0.1, 0.08, 0.05]):
        k, ev = best_candidate_set(probs)
        print(f"    p = {probs}  → k = {k}, E[J] = {ev:.3f}")
    print()
    return 0


def cmd_simulate(args) -> int:
    gold = load_dir(args.gold)
    print(f"\n── hệ giả lập trên gold {args.gold.name} "
          f"({len(gold)} file, {sum(len(v) for v in gold.values())} mention) ──\n")
    head = (f"  {'hồ sơ':<26}{'final':>8}{'  KTC 95%':>18}{'q_pair':>8}"
            f"{'phủ':>7}{'recall':>8}{'prec':>7}")
    print(head)
    print("  " + "─" * (len(head) - 2))
    rows = []
    for profile in PROFILES:
        pred = degrade(gold, profile, seed=args.seed)
        corpus = score_corpus(gold, pred)
        d = decompose(corpus)
        agg = lambda u: sum(0.3 * x.text + 0.3 * x.assertions + 0.4 * x.candidates  # noqa: E731
                            for x in u) / len(u)
        _, lo, hi = bootstrap_ci(corpus.per_file, agg, seed=args.seed, n_resamples=2000)
        print(f"  {profile.name:<26}{corpus.final:>8.4f}  [{lo:.3f}, {hi:.3f}]"
              f"{d['q_pair']:>8.3f}{d['coverage']:>7.3f}{d['recall']:>8.1%}{d['precision']:>7.1%}")
        rows.append({"name": profile.name, "final": corpus.final, "ci": [lo, hi], **d})
    print("\n  Đọc bảng: so 'v4-like' với 'biên span hoàn hảo' để thấy giá của lỗi biên;")
    print("  so 'v4-like' với 'luôn trả 2 mã' để thấy giá của việc rải mã;")
    print("  so 'recall cao' với 'precision cao' để thấy metric ưu ái bên nào.\n")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {args.json}")
    return 0


#: Các tập nhãn thẩm định mặc định — "tên:thư mục nhãn:thư mục văn bản".
DEFAULT_CORPORA = [
    "dev_gold:data/dev_gold_consensus:data/test",
    "gen/synthetic:data/generated_medical_records/synthetic/annotations"
    ":data/generated_medical_records/synthetic/text",
    "gen/translated:data/generated_medical_records/translated/annotations"
    ":data/generated_medical_records/translated/text",
    "gen/restyled:data/generated_medical_records/restyled/annotations"
    ":data/generated_medical_records/restyled/text",
]


def cmd_corpus(args) -> int:
    from .corpus import compare, load_pairs, profile

    specs = args.corpus or DEFAULT_CORPORA
    profiles = []
    for spec in specs:
        name, ann, txt = spec.split(":", 2)
        ann_dir, txt_dir = ROOT / ann, ROOT / txt
        if not ann_dir.is_dir():
            print(f"  bỏ qua {name}: không có {ann}")
            continue
        if not txt_dir.is_dir():
            print(f"  bỏ qua {name}: không có {txt}")
            continue
        docs = load_pairs(ann_dir, txt_dir)
        if not docs:
            print(f"  bỏ qua {name}: không ghép được nhãn với văn bản")
            continue
        profiles.append(profile(name, docs))
    if not profiles:
        raise SystemExit("LỖI: không thẩm định được tập nào")
    print(compare(profiles[0], profiles[1:]))
    print("\n  Đọc bảng: cột Δ độ dài span quyết định tập có dùng làm TRAIN được không")
    print("  (lệch âm dạy model cắt cụt span, và WER phạt theo từ);")
    print("  cột 'vượt nền' ở độ đầy đủ quyết định tập có dạy model BỎ SÓT không;")
    print("  bảng candidates quyết định tập có dùng để hiệu chuẩn ngưỡng phát mã không.\n")
    return 0


#: Các biến thể gold để kiểm độ bền của chẩn đoán.
DEFAULT_GOLDS = [
    "data/dev_gold_consensus",
    "data/dev_gold_sonnet5",
    "data/dev_gold_opus5",
    "data/dev_gold_prefill",
]


def cmd_robust(args) -> int:
    """Chạy oracle ablation trên NHIỀU gold — kiểm chẩn đoán có phụ thuộc gold không.

    Bài học đắt nhất của dự án nằm ở lệnh này: chấm trên **một** gold do LLM sinh
    rồi kết luận "nút thắt là X" có thể sai hoàn toàn, vì cách dựng gold quyết
    định luôn dấu của kết luận. Gold ``consensus`` là **phần giao** của hai model
    nên nó bỏ ~30% mention; những mention nó bỏ lại chính là các dự đoán ĐÚNG của
    hệ, và chúng bị đếm thành "thừa" ⇒ precision tụt giả tạo ⇒ oracle
    ``+precision`` phồng lên. Trên các gold đầy đủ hơn, kết luận đảo chiều.
    """
    golds = args.golds or DEFAULT_GOLDS
    preds = {p.name: load_dir(p) for p in args.pred}
    if not preds:
        raise SystemExit("LỖI: robust cần ít nhất một --pred DIR")

    head = (f"  {'gold':<16}{'n':>6}   " +
            "".join(f"{n:<10}" for n in preds) +
            f"{'rec':>7}{'prec':>7}{'+prec':>9}{'+recall':>9}  nút thắt")
    print(f"\n── chẩn đoán theo từng gold ──\n")
    print(head)
    print("  " + "─" * (len(head) - 2))

    verdicts = []
    for gdir in golds:
        path = ROOT / gdir
        if not path.is_dir():
            print(f"  bỏ qua {gdir}: không tồn tại")
            continue
        gold = load_dir(path)
        cells = []
        for name, pred in preds.items():
            p = {k: v for k, v in pred.items() if k in gold}
            cells.append(f"{score_corpus(gold, p).final:<10.4f}")
        # chẩn đoán tính trên --pred ĐẦU TIÊN
        main = {k: v for k, v in next(iter(preds.values())).items() if k in gold}
        d = decompose(score_corpus(gold, main))
        abl = oracle_ablations(gold, main)
        base = abl["baseline"].final
        dp = abl["+precision (bỏ pred thừa)"].final - base
        dr = abl["+recall (thêm gold thiếu)"].final - base
        winner = "PRECISION" if dp > dr else "recall"
        ratio = max(dp, dr) / max(min(dp, dr), 1e-9)
        verdicts.append(winner)
        print(f"  {path.name:<16}{sum(len(v) for v in gold.values()):>6}   "
              + "".join(cells)
              + f"{d['recall']:>6.1%}{d['precision']:>7.1%}{dp:>+9.4f}{dr:>+9.4f}"
              f"  {winner} ({ratio:.1f}×)")

    print()
    if len(set(verdicts)) > 1:
        print("  ⚠ CHẨN ĐOÁN KHÔNG BỀN: các gold cho kết luận NGƯỢC NHAU về nút thắt.")
        print("    Không được kết luận nút thắt từ một gold duy nhất. Việc cần làm là")
        print("    gán tay một tập gold nhỏ để chốt, không phải chọn gold nào hợp ý.")
    elif verdicts:
        print(f"  ✓ Chẩn đoán bền: mọi gold đều cho '{verdicts[0]}'.")
    print()
    return 0


def cmd_selftest(args) -> int:
    """Kiểm chứng benchmark: các bất biến phải đúng trước khi tin bất kỳ con số nào."""
    gold = load_dir(args.gold)
    checks: list[tuple[str, bool, str]] = []

    perfect = score_corpus(gold, gold)
    checks.append(("gold chấm với chính nó = 1.0", abs(perfect.final - 1.0) < 1e-9,
                   f"{perfect.final:.6f}"))

    empty = score_corpus(gold, {k: [] for k in gold})
    checks.append(("pred rỗng = 0.0", abs(empty.final) < 1e-9, f"{empty.final:.6f}"))

    g = score_corpus(gold, degrade(gold, PROFILES[2], seed=1))
    h = score_corpus(gold, degrade(gold, PROFILES[2], seed=1), match="hungarian")
    checks.append(("Hungarian ≥ greedy (ghép tối ưu không tệ hơn)",
                   h.final >= g.final - 1e-9, f"greedy {g.final:.4f} vs hung {h.final:.4f}"))

    a = score_corpus(gold, degrade(gold, PROFILES[2], seed=7)).final
    b = score_corpus(gold, degrade(gold, PROFILES[2], seed=7)).final
    checks.append(("tất định: cùng seed → cùng điểm", abs(a - b) < 1e-12, f"{a:.10f}"))

    from .decision import expected_jaccard
    ok = abs(expected_jaccard([1.0], 1) - 1.0) < 1e-9 and abs(expected_jaccard([0.0], 0) - 1.0) < 1e-9
    checks.append(("E[J]: chắc chắn đúng = 1; cả hai rỗng = 1", ok, ""))
    ok2 = abs(expected_jaccard([0.5], 1) - 0.5) < 1e-9
    checks.append(("E[J]: p=0.5, k=1 → 0.5", ok2, f"{expected_jaccard([0.5], 1):.4f}"))

    # mô hình xấp xỉ final ≈ q_pair × phủ phải bám sát thực đo
    d = decompose(score_corpus(gold, degrade(gold, PROFILES[2], seed=3)))
    gap = abs(d["final"] - d["final_model"])
    checks.append(("công thức xấp xỉ lệch < 0.02", gap < 0.02,
                   f"lệch {gap:.4f} ({d['final']:.4f} vs {d['final_model']:.4f})"))

    # recall cao hơn phải cho điểm cao hơn, giữ nguyên phần còn lại
    from .degrade import Profile
    lo = score_corpus(gold, degrade(gold, Profile("lo", recall=0.4), seed=5)).final
    hi = score_corpus(gold, degrade(gold, Profile("hi", recall=0.8), seed=5)).final
    checks.append(("recall 0.8 > recall 0.4", hi > lo, f"{hi:.4f} > {lo:.4f}"))

    print()
    failed = 0
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        failed += not ok
        print(f"  {mark} {name:<46}{detail}")
    print(f"\n  {len(checks) - failed}/{len(checks)} kiểm tra đạt\n")
    return 1 if failed else 0


# ── entry ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--pred", type=Path, action="append", default=[])
    ap.add_argument("--unmatched", default="zero", choices=["zero", "skip"])
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--steps", type=int, default=11)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--corpus", action="append", default=[],
                    help="lệnh corpus: 'tên:thư_mục_nhãn:thư_mục_văn_bản'; "
                         "tập ĐẦU TIÊN là tham chiếu. Bỏ trống thì dùng mặc định.")
    ap.add_argument("--golds", action="append", default=[],
                    help="lệnh robust: thư mục gold (lặp lại được). Bỏ trống thì "
                         "dùng 4 biến thể trong data/gold_variants/.")
    ap.add_argument("cmd", choices=["score", "compare", "diagnose", "policy",
                                    "simulate", "selftest", "corpus", "robust"])
    args = ap.parse_args(argv)

    if args.cmd in {"score", "compare", "diagnose", "robust"} and not args.pred:
        raise SystemExit(f"LỖI: lệnh '{args.cmd}' cần ít nhất một --pred DIR")

    return {
        "score": cmd_score,
        "compare": cmd_compare,
        "diagnose": cmd_diagnose,
        "policy": cmd_policy,
        "simulate": cmd_simulate,
        "selftest": cmd_selftest,
        "corpus": cmd_corpus,
        "robust": cmd_robust,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
