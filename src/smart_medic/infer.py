"""infer.py — entrypoint chạy pipeline trên một thư mục .txt.

    python -m smart_medic.infer --input data/test --output data/output

Ghi kèm ``run_manifest.json`` — ĐÂY CHÍNH LÀ artifact reproducibility mà BTC
cần để chạy lại và ra đúng con số của ta.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .kb.store import KBError, load_kb
from .pipeline import Pipeline, PipelineConfig, RunStats
from .schema import dumps, validate_file
from .stages.extract import (
    CompositeExtractor,
    GazetteerExtractor,
    IcdCueExtractor,
    RxNormExtractor,
)
from .textref import read_textref

ROOT = Path(__file__).resolve().parents[2]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _sorted_txt(d: Path) -> list[Path]:
    def key(p: Path) -> tuple[int, str]:
        stem = p.stem
        return (int(stem), "") if stem.isdigit() else (10**9, stem)

    return sorted(d.glob("*.txt"), key=key)


def package_zip(outdir: Path, zpath: Path) -> int:
    """Đóng gói output/N.json → output.zip đúng cấu trúc BTC quy định."""
    files = sorted(
        outdir.glob("*.json"),
        key=lambda p: (int(p.stem), "") if p.stem.isdigit() else (10**9, p.stem),
    )
    files = [f for f in files if f.name not in {"run_manifest.json", "explain.json"}]
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, arcname=f"output/{f.name}")
    return len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Smart Medic — inference")
    ap.add_argument("--input", type=Path, default=ROOT / "data/test")
    ap.add_argument("--output", type=Path, default=ROOT / "data/output")
    ap.add_argument("--kb", type=Path, default=ROOT / "data/kb")
    ap.add_argument("--zip", type=Path, default=None, help="đóng gói ra output.zip")
    ap.add_argument("--extractor", default="v2", choices=["gazetteer", "v2"])
    ap.add_argument("--max-candidates", type=int, default=2)
    ap.add_argument("--candidate-threshold", type=float, default=0.80)
    ap.add_argument("--retrieval-threshold", type=float, default=0.80)
    ap.add_argument("--drug-threshold", type=float, default=0.84)
    ap.add_argument("--ambiguity-margin", type=float, default=0.04)
    ap.add_argument("--rxnorm-output-mode", default="current",
                    choices=["current", "legacy", "both"])
    ap.add_argument("--keep-risk-short", action="store_true",
                    help="giữ alias ICD ≤6 ký tự (mặc định loại — xem store.py)")
    ap.add_argument("--no-assertions", action="store_true")
    ap.add_argument("--explain", action="store_true", help="ghi kèm provenance")
    args = ap.parse_args(argv)

    try:
        kb = load_kb(args.kb, drop_risk_short=not args.keep_risk_short)
    except KBError as exc:
        print(f"LỖI KB: {exc}", file=sys.stderr)   # fail loud lúc start
        return 2

    cfg = PipelineConfig(
        max_candidates=args.max_candidates,
        candidate_threshold=args.candidate_threshold,
        ambiguity_margin=args.ambiguity_margin,
        enable_negated=not args.no_assertions,
        enable_historical=not args.no_assertions,
        enable_family=False,
        rxnorm_output_mode=args.rxnorm_output_mode,
    )
    gazetteer = GazetteerExtractor(kb, max_candidates=args.max_candidates)
    extractor = gazetteer
    if args.extractor == "v2":
        extractor = CompositeExtractor(
            gazetteer,
            IcdCueExtractor(kb, threshold=args.retrieval_threshold),
            RxNormExtractor(
                kb,
                threshold=args.drug_threshold,
                max_candidates=args.max_candidates,
            ),
        )
    pipe = Pipeline(kb, extractor, cfg)

    files = _sorted_txt(args.input)
    if not files:
        print(f"LỖI: không thấy file .txt nào trong {args.input}", file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    stats = RunStats()
    schema_errors: list[str] = []
    explain: dict[str, list] = {}

    for path in files:
        try:
            tref = read_textref(path)
            mentions = pipe.run(tref, stats)
        except Exception as exc:                       # noqa: BLE001
            stats.errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            mentions, tref = [], None                  # vẫn ghi file rỗng hợp lệ

        payload = dumps(mentions)
        (args.output / f"{path.stem}.json").write_text(payload, encoding="utf-8")

        if tref is not None:
            errs = validate_file(json.loads(payload), tref.raw)
            schema_errors.extend(f"{path.name} {e}" for e in errs)
        if args.explain:
            explain[path.name] = [
                {**m.to_dict(), "_provenance": asdict(m.provenance)} for m in mentions
            ]

    manifest = {
        "git_sha": _git_sha(),
        "kb_manifest": kb.manifest.get("built_at"),
        "normalizer_version": kb.manifest.get("normalizer_version"),
        "extractor": pipe.extractor.name,
        "config": {
            "max_candidates": cfg.max_candidates,
            "candidate_threshold": cfg.candidate_threshold,
            "retrieval_threshold": args.retrieval_threshold,
            "drug_threshold": args.drug_threshold,
            "ambiguity_margin": cfg.ambiguity_margin,
            "enable_negated": cfg.enable_negated,
            "enable_historical": cfg.enable_historical,
            "enable_family": cfg.enable_family,
            "rxnorm_output_mode": cfg.rxnorm_output_mode,
            "drop_risk_short": not args.keep_risk_short,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_files": stats.files,
        "n_mentions": stats.mentions,
        "by_type": stats.by_type,
        "by_assertion": stats.by_assertion,
        "with_candidates": stats.with_candidates,
        "dropped_invariant": stats.dropped_invariant,
        "dropped_overlap": stats.dropped_overlap,
        "dropped_threshold": stats.dropped_threshold,
        "by_link_path": stats.by_link_path,
        "schema_errors": len(schema_errors),
        "errors": stats.errors,
    }
    (args.output / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.explain:
        (args.output / "explain.json").write_text(
            json.dumps(explain, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"{stats.files} file · {stats.mentions} mention "
          f"· {stats.with_candidates} có candidates")
    print(f"  theo type      : {stats.by_type}")
    print(f"  theo assertion : {stats.by_assertion or '{}'}")
    print(f"  loại (bất biến): {stats.dropped_invariant} · "
          f"(chồng lấn): {stats.dropped_overlap} · "
          f"(ngưỡng): {stats.dropped_threshold}")

    if schema_errors:
        print(f"\n✗ {len(schema_errors)} LỖI SCHEMA:", file=sys.stderr)
        for e in schema_errors[:20]:
            print(f"    {e}", file=sys.stderr)
        return 1
    print("  schema         : OK")

    if stats.errors:
        print(f"\n! {len(stats.errors)} file gặp lỗi (đã ghi file rỗng hợp lệ):")
        for e in stats.errors[:10]:
            print(f"    {e}")

    if args.zip:
        n = package_zip(args.output, args.zip)
        print(f"  đóng gói       : {args.zip} ({n} file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
