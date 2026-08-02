"""Entrypoint duy nhất: `smk`.

smk kb extract    raw → staging   (đắt, có cache)
smk kb normalize  staging → staging đã chuẩn hoá
smk kb load       staging → kb.sqlite
smk kb validate   chạy cổng chất lượng, fail hard
smk kb build      chạy cả 4 pha trên

smk solve         thư mục .txt → thư mục .json (bài nộp)
smk eval solve    chấm pipeline trên bộ gold, có bảng theo nhánh + CI bootstrap
smk eval compare  Δ theo cặp giữa hai báo cáo, có CI
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

SOURCE_CHOICES = ("icd", "rxnorm", "snomed", "all")


def _add_kb_parser(sub: argparse._SubParsersAction) -> None:
    kb = sub.add_parser("kb", help="Xây và truy vấn Knowledge Base")
    kb_sub = kb.add_subparsers(dest="kb_cmd", metavar="<lệnh>", required=True)

    p_extract = kb_sub.add_parser("extract", help="raw → staging (đắt, có cache)")
    p_extract.add_argument("--source", default="all", choices=SOURCE_CHOICES)
    p_extract.add_argument("--force", action="store_true", help="bỏ qua cache")

    kb_sub.add_parser("normalize", help="chuẩn hoá chuỗi trong staging")

    p_enrich = kb_sub.add_parser("enrich", help="sinh dòng CỘNG THÊM (Phase 3)")
    p_enrich.add_argument("--only", help="chỉ chạy các nguồn này, ngăn bằng dấu phẩy")
    p_enrich.add_argument("--skip", help="bỏ các nguồn này, ngăn bằng dấu phẩy")

    p_load = kb_sub.add_parser("load", help="staging → kb.sqlite")
    p_load.add_argument("--out", help="đường dẫn artifact (mặc định data/artifacts/kb.sqlite)")

    p_validate = kb_sub.add_parser("validate", help="chạy cổng chất lượng, fail hard")
    p_validate.add_argument("--db", help="artifact cần kiểm (mặc định data/artifacts/kb.sqlite)")

    p_build = kb_sub.add_parser("build", help="extract + normalize + load + validate")
    p_build.add_argument("--source", default="all", choices=SOURCE_CHOICES)
    p_build.add_argument("--force", action="store_true", help="bỏ qua cache")

    p_dense = kb_sub.add_parser("dense", help="dựng FAISS index từ kb.sqlite (Phase 5)")
    p_dense.add_argument("--db", help="artifact nguồn")
    p_dense.add_argument("--out", help="đường dẫn index")

    p_eval = kb_sub.add_parser("eval", help="đo Recall@k trên probe set")
    p_eval.add_argument("--db", help="artifact cần đo")
    p_eval.add_argument("--probe", help="probe set (mặc định data/probe/retrieval_probe.yaml)")
    p_eval.add_argument("--tiers", help="chỉ dùng term thuộc các tier này, ngăn bằng dấu phẩy")
    p_eval.add_argument("--max-fan-in", type=int, help="ngưỡng fan-in cho term mượn từ SNOMED")
    p_eval.add_argument("--save", help="ghi kết quả ra JSON để làm mốc so sánh")
    p_eval.add_argument("--compare", help="JSON mốc để in delta")
    p_eval.add_argument(
        "--rerank", action="store_true", help="bật re-rank nhánh thuốc (độ phủ token × TTY)"
    )


def _add_solve_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("solve", help="chạy pipeline giải bài: thư mục .txt → .json")
    p.add_argument("--input", default="data/test", help="thư mục chứa .txt")
    p.add_argument("--out", default="data/output", help="thư mục ghi .json")
    p.add_argument("--db", help="artifact KB (mặc định data/artifacts/kb.sqlite)")
    p.add_argument("--zip", dest="zip_path", help="đóng gói bài nộp ra file zip")


DEFAULT_GOLD_SETS = (
    "data/probe/gold_real",  # ★ cổng duy nhất
    "data/probe/gold",  # regression guard
    "data/probe/gold_batch1",  # khái quát hoá ngoài miền
)


def _add_eval_parser(sub: argparse._SubParsersAction) -> None:
    ev = sub.add_parser("eval", help="chấm pipeline giải bài trên bộ gold gán tay")
    ev_sub = ev.add_subparsers(dest="eval_cmd", metavar="<lệnh>", required=True)

    p_solve = ev_sub.add_parser("solve", help="chấm một hoặc nhiều bộ gold")
    p_solve.add_argument(
        "--gold",
        action="append",
        metavar="DIR",
        help="thư mục bộ gold; lặp lại để chấm nhiều bộ. Mặc định: cả ba bộ",
    )
    p_solve.add_argument("--report", help="ghi báo cáo JSON")
    p_solve.add_argument("--db", help="artifact KB (mặc định data/artifacts/kb.sqlite)")
    p_solve.add_argument(
        "--bootstrap",
        type=int,
        default=None,
        metavar="B",
        help="số lần lấy mẫu bootstrap (mặc định 10000; hạ xuống chỉ để chạy nhanh khi thử)",
    )

    p_cmp = ev_sub.add_parser("compare", help="Δ theo cặp giữa hai báo cáo, có CI")
    p_cmp.add_argument("--base", required=True, help="báo cáo mốc")
    p_cmp.add_argument("--new", required=True, help="báo cáo mới")
    p_cmp.add_argument("--report", help="ghi kết quả so sánh ra JSON")


def _add_synth_parser(sub: argparse._SubParsersAction) -> None:
    sy = sub.add_parser("synth", help="sinh corpus huấn luyện (chỉ chạy lúc BUILD)")
    sy_sub = sy.add_subparsers(dest="synth_cmd", metavar="<lệnh>", required=True)

    p_build = sy_sub.add_parser("build", help="sinh corpus + kiểm 4 bất biến + thống kê")
    p_build.add_argument("-n", "--docs", type=int, default=500, help="số tài liệu")
    p_build.add_argument("--out", default="data/synth/v1", help="thư mục đích")
    p_build.add_argument("--seed", type=int, default=20260802, help="seed, GHIM để tái lập")
    p_build.add_argument("--db", help="artifact KB")
    p_build.add_argument("--report", help="ghi thống kê ra JSON")

    p_freeze = sy_sub.add_parser("freeze", help="đóng băng nguồn ATC ra data/curated/")
    p_freeze.add_argument("--out", help="thư mục curated")


def _add_train_parser(sub: argparse._SubParsersAction) -> None:
    tr = sub.add_parser("train", help="huấn luyện tagger (cần nhóm dependency 'train')")
    tr_sub = tr.add_subparsers(dest="train_cmd", metavar="<lệnh>", required=True)
    p_tag = tr_sub.add_parser("tagger", help="XLM-R token classification trên corpus tổng hợp")
    p_tag.add_argument("--epochs", type=int, default=3)
    p_tag.add_argument("--batch-size", type=int, default=8)
    p_tag.add_argument("--lr", type=float, default=3e-5)
    p_tag.add_argument("--out", help="thư mục checkpoint")
    p_tag.add_argument("--report", help="ghi metadata ra JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smk",
        description="Smart Medic — Viettel AI Race 2026",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<nhóm>", required=True)
    _add_kb_parser(sub)
    _add_solve_parser(sub)
    _add_eval_parser(sub)
    _add_synth_parser(sub)
    _add_train_parser(sub)
    return parser


def _dispatch_kb(args: argparse.Namespace) -> int:
    # Import trong hàm: `smk kb --help` không nên phải nạp pymupdf/pyarrow.
    from smart_medic.kb import pipeline

    match args.kb_cmd:
        case "extract":
            return pipeline.run_extract(source=args.source, force=args.force)
        case "normalize":
            return pipeline.run_normalize()
        case "enrich":
            return pipeline.run_enrich(only=args.only, skip=args.skip)
        case "load":
            return pipeline.run_load(out=args.out)
        case "validate":
            return pipeline.run_validate(db=args.db)
        case "build":
            return pipeline.run_build(source=args.source, force=args.force)
        case "dense":
            return pipeline.run_dense(db=args.db, out=args.out)
        case "eval":
            return pipeline.run_eval(
                db=args.db,
                probe=args.probe,
                tiers=args.tiers,
                save=args.save,
                compare=args.compare,
                rerank=args.rerank,
            )
        case _:  # pragma: no cover — argparse đã chặn
            raise AssertionError(args.kb_cmd)


def _dispatch_solve(args: argparse.Namespace) -> int:
    from pathlib import Path

    from smart_medic.stages import solve
    from smart_medic.stages.flags import active_config

    # ★ In cấu hình ĐANG CHẠY ở mọi lần chạy. Thiếu `data/curated/` thì pipeline
    #   âm thầm tụt về C0 — bug container số 4, xem `flags.active_config`.
    cfg = active_config()
    src = cfg.pop("_source")
    ovr = cfg.pop("_overrides")
    print(f"  cấu hình: {cfg}")
    print(f"  nguồn:    {src}" + (f"  · ghi đè bằng env: {ovr}" if ovr else ""))
    if "DEFAULTS" in src:
        print("  ⚠ THIẾU data/curated/pipeline.v1.yaml — đang chạy cấu hình MẶC ĐỊNH,")
        print("    KHÔNG phải cấu hình đã chọn ở Phase 5. Điểm sẽ thấp hơn ~0,05.")

    stats = solve.run(
        input_dir=Path(args.input),
        out_dir=Path(args.out),
        db=Path(args.db) if args.db else None,
    )
    print(f"  {stats.n_docs} file → {args.out}")
    print(f"  {stats.n_entities} khái niệm")
    for k in sorted(stats.by_type, key=lambda x: -stats.by_type[x]):
        print(f"    {k:22s} {stats.by_type[k]:5d}")
    if stats.stale:
        print(f"  ⚠ {len(stats.stale)} file lạ trong {args.out} (sót từ lần chạy trước):")
        print(f"    {', '.join(stats.stale[:8])}")
        print("    → không được đưa vào bài nộp; dùng --zip để đóng gói đúng danh sách")
    if args.zip_path:
        n = solve.write_zip(Path(args.out), Path(args.zip_path), input_dir=Path(args.input))
        print(f"  → {args.zip_path} ({n} file)")
    return 0


def _dispatch_eval(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from smart_medic.eval import bootstrap, harness

    b = args.bootstrap if getattr(args, "bootstrap", None) else bootstrap.B_DEFAULT

    if args.eval_cmd == "compare":
        base = json.loads(Path(args.base).read_text(encoding="utf-8"))
        new = json.loads(Path(args.new).read_text(encoding="utf-8"))
        cmp = harness.compare_reports(base, new, b=b)
        print(harness.format_comparison(cmp))
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(
                json.dumps(cmp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"\n  → {args.report}")
        return 0

    db = Path(args.db) if args.db else None
    dirs = [Path(g) for g in (args.gold or DEFAULT_GOLD_SETS)]
    results = []
    for d in dirs:
        r = harness.score_gold_set(d, db=db, b=b)
        results.append(r)
        print(harness.format_set(r))
        print()

    if args.report:
        payload = harness.build_report(results, db=db)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  → {args.report}")
    # Vi phạm bất biến là BUG, không phải điểm thấp — phải làm fail lệnh.
    return 1 if any(r.invariant_errors for r in results) else 0


def _dispatch_synth(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from smart_medic.synth import export, render, stats
    from smart_medic.synth.surface import drug as drug_src

    if args.synth_cmd == "freeze":
        out = Path(args.out) if args.out else None
        counts = drug_src.freeze_curated(drug_src.load_ddd(), out)
        print(f"  đóng băng nguồn ATC: {counts}")
        return 0

    out_dir = Path(args.out)
    docs = render.generate(args.docs, seed=args.seed, db=Path(args.db) if args.db else None)
    manifest = export.write(docs, out_dir, seed=args.seed)
    manifest.update(export.write_splits(docs, out_dir, seed=args.seed))
    st = stats.measure(docs)

    print(f"  {st['n_docs']} tài liệu → {out_dir}")
    print(
        f"  {st['n_spans']} span · {st['n_distractors']} cụm gây nhiễu "
        f"({st['distractor_share']['value']:.1%})"
    )
    print(f"  độ dài trung vị {st['length']['median']} (đích {st['length']['target_median']})")
    print(f"  {'nhiễu':10}{'đích':>8}{'đo được':>10}{'Δ điểm %':>10}")
    for k, v in st["noise"].items():
        flag_ = "✓" if v["ok"] else "✗"
        print(f"  {k:10}{v['target']:>8.2f}{v['observed']:>10.2f}{v['delta_pp']:>+9.1f} {flag_}")
    print(f"  nhãn: {st['by_type']}")
    print(f"  assertion: {st['assertions']}")
    print(f"  sha256 corpus {manifest['corpus_sha256'][:16]}…")

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps({"manifest": manifest, "stats": st}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  → {args.report}")
    return 0


def _dispatch_train(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    try:
        from smart_medic.train.train_tagger import TrainConfig, run
    except ImportError:
        print("  ✗ thiếu nhóm dependency 'train'. Cài: pip install -e '.[train]'")
        return 1

    meta = run(
        TrainConfig(epochs=args.epochs, batch_size=args.batch_size, lr=args.lr),
        out_dir=Path(args.out) if args.out else None,
    )
    print(f"  dev F1 {meta['dev'].get('span_f1')} · corpus sha256 {meta['corpus_sha256'][:16]}…")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  → {args.report}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "kb":
        return _dispatch_kb(args)
    if args.cmd == "solve":
        return _dispatch_solve(args)
    if args.cmd == "eval":
        return _dispatch_eval(args)
    if args.cmd == "synth":
        return _dispatch_synth(args)
    if args.cmd == "train":
        return _dispatch_train(args)
    raise AssertionError(args.cmd)  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
