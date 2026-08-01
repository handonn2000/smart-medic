"""Entrypoint duy nhất: `smk`.

smk kb extract    raw → staging   (đắt, có cache)
smk kb normalize  staging → staging đã chuẩn hoá
smk kb load       staging → kb.sqlite
smk kb validate   chạy cổng chất lượng, fail hard
smk kb build      chạy cả 4 pha trên
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smk",
        description="Smart Medic — Viettel AI Race 2026",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<nhóm>", required=True)
    _add_kb_parser(sub)
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
            )
        case _:  # pragma: no cover — argparse đã chặn
            raise AssertionError(args.kb_cmd)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "kb":
        return _dispatch_kb(args)
    raise AssertionError(args.cmd)  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
