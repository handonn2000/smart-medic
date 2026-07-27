"""infer.py — entrypoint chạy pipeline trên một thư mục .txt.

    python -m smart_medic.infer --input data/test --output data/output

Ghi kèm ``run_manifest.json`` — ĐÂY CHÍNH LÀ artifact reproducibility mà BTC
cần để chạy lại và ra đúng con số của ta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .batch import BatchResolutionStats, CrossDocumentMaskResolver
from .kb.store import KBError, load_kb
from .pipeline import Pipeline, PipelineConfig, RunStats
from .schema import Mention, dumps, validate_file
from .stages.extract import (
    CompositeExtractor,
    GazetteerExtractor,
    IcdCueExtractor,
    RxNormExtractor,
)
from .stages.clinical import ClinicalSymptomExtractor
from .stages.lab import LabObservationExtractor
from .textref import TextRef, read_textref

ROOT = Path(__file__).resolve().parents[2]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _files_fingerprint(files: list[Path]) -> str:
    """Hash file names and bytes in caller-provided deterministic order."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _sorted_txt(d: Path) -> list[Path]:
    def key(p: Path) -> tuple[int, str]:
        stem = p.stem
        return (int(stem), "") if stem.isdigit() else (10**9, stem)

    return sorted(d.glob("*.txt"), key=key)


def package_zip(outdir: Path, zpath: Path, files: list[Path] | None = None) -> int:
    """Package numeric JSON files with stable order and ZIP metadata."""
    selected = sorted(
        outdir.glob("*.json") if files is None else files,
        key=lambda p: (int(p.stem), "") if p.stem.isdigit() else (10**9, p.stem),
    )
    selected = [
        path for path in selected
        if path.stem.isdigit() and path.suffix == ".json" and path.is_file()
    ]
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as z:
        for f in selected:
            info = zipfile.ZipInfo(f"output/{f.name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, f.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                       compresslevel=9)
    return len(selected)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Smart Medic — inference")
    ap.add_argument("--input", type=Path, default=ROOT / "data/test")
    ap.add_argument("--output", type=Path, default=ROOT / "data/output")
    ap.add_argument("--kb", type=Path, default=ROOT / "data/kb")
    ap.add_argument("--zip", type=Path, default=None, help="đóng gói ra output.zip")
    ap.add_argument("--extractor", default="v3", choices=["gazetteer", "v2", "v3"])
    ap.add_argument("--max-candidates", type=int, default=2)
    ap.add_argument("--candidate-threshold", type=float, default=0.80)
    ap.add_argument("--retrieval-threshold", type=float, default=0.80)
    ap.add_argument("--drug-threshold", type=float, default=0.84)
    ap.add_argument("--ambiguity-margin", type=float, default=0.0,
                    help="q/(1-q): P(gold thật sự có 2 mã anh em). PLACEHOLDER")
    ap.add_argument("--a1-top1-accuracy", type=float, default=0.5,
                    help="a₁ = P(mã đầu bảng đúng). PLACEHOLDER, chờ dev gold")
    ap.add_argument("--type-confidence-floor", type=float, default=0.0,
                    help="sàn cứng thêm cho p_t, chồng lên 1/(1+a₁)")
    ap.add_argument("--rxnorm-output-mode", default="current",
                    choices=["current", "legacy", "both"])
    ap.add_argument("--keep-risk-short", action="store_true",
                    help="giữ alias ICD ≤6 ký tự (mặc định loại — xem store.py)")
    ap.add_argument("--no-assertions", action="store_true")
    ap.add_argument(
        "--no-batch-mask-resolution",
        action="store_true",
        help="tắt resolver mask liên văn bản của v3",
    )
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
        a1_top1_accuracy=args.a1_top1_accuracy,
        type_confidence_floor=args.type_confidence_floor,
        enable_negated=not args.no_assertions,
        enable_historical=not args.no_assertions,
        enable_family=False,
        rxnorm_output_mode=args.rxnorm_output_mode,
    )
    gazetteer = GazetteerExtractor(
        kb,
        max_candidates=args.max_candidates,
        contextual_ambiguity=args.extractor == "v3",
    )
    extractor = gazetteer
    if args.extractor in {"v2", "v3"}:
        extras = [
            IcdCueExtractor(kb, threshold=args.retrieval_threshold),
            RxNormExtractor(
                kb,
                threshold=args.drug_threshold,
                max_candidates=args.max_candidates,
                contextual_analytes=args.extractor == "v3",
            ),
        ]
        if args.extractor == "v3":
            extras.extend([ClinicalSymptomExtractor(), LabObservationExtractor()])
        extractor = CompositeExtractor(
            gazetteer,
            *extras,
            name=f"{args.extractor}_composite",
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
    results: dict[str, tuple[Path, TextRef | None, list[Mention]]] = {}

    for path in files:
        try:
            tref = read_textref(path)
            mentions = pipe.run(tref, stats)
        except Exception as exc:                       # noqa: BLE001
            stats.errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            mentions, tref = [], None                  # vẫn ghi file rỗng hợp lệ

        results[path.name] = (path, tref, mentions)

    batch_resolution = BatchResolutionStats()
    if args.extractor == "v3" and not args.no_batch_mask_resolution:
        batch_resolution = CrossDocumentMaskResolver().resolve({
            filename: (tref, mentions)
            for filename, (_, tref, mentions) in results.items()
            if tref is not None
        })

    stats.recount(
        (mentions for _, _, mentions in results.values()),
        files=len(files),
    )

    for path in files:
        _, tref, mentions = results[path.name]
        payload = dumps(mentions)
        (args.output / f"{path.stem}.json").write_text(payload, encoding="utf-8")

        if tref is not None:
            errs = validate_file(json.loads(payload), tref.raw)
            schema_errors.extend(f"{path.name} {e}" for e in errs)
        if args.explain:
            explain[path.name] = [
                {**m.to_dict(), "_provenance": asdict(m.provenance)} for m in mentions
            ]

    if args.explain:
        (args.output / "explain.json").write_text(
            json.dumps(explain, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    output_files = sorted(
        (args.output / f"{path.stem}.json" for path in files),
        key=lambda path: (int(path.stem), "") if path.stem.isdigit() else (10**9, path.stem),
    )
    packaged: tuple[int, str] | None = None
    if args.zip:
        n = package_zip(args.output, args.zip, output_files)
        packaged = (n, _sha256(args.zip))

    manifest = {
        "manifest_version": 2,
        "pipeline_version": __version__,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "kb_manifest": kb.manifest.get("built_at"),
        "normalizer_version": kb.manifest.get("normalizer_version"),
        "kb_artifacts": kb.manifest.get("artifacts", {}),
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "extractor": pipe.extractor.name,
        "config": {
            "max_candidates": cfg.max_candidates,
            "candidate_threshold": cfg.candidate_threshold,
            "retrieval_threshold": args.retrieval_threshold,
            "drug_threshold": args.drug_threshold,
            "ambiguity_margin": cfg.ambiguity_margin,
            "a1_top1_accuracy": cfg.a1_top1_accuracy,
            "type_confidence_floor": cfg.type_confidence_floor,
            "min_type_confidence": cfg.min_type_confidence,
            "enable_negated": cfg.enable_negated,
            "enable_historical": cfg.enable_historical,
            "enable_family": cfg.enable_family,
            "rxnorm_output_mode": cfg.rxnorm_output_mode,
            "batch_mask_resolution": (
                args.extractor == "v3" and not args.no_batch_mask_resolution
            ),
            "drop_risk_short": not args.keep_risk_short,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_sha256": _files_fingerprint(files),
        "output_sha256": _files_fingerprint(output_files),
        "submission": None if packaged is None else {
            "path": args.zip.name,
            "files": packaged[0],
            "sha256": packaged[1],
        },
        "n_files": stats.files,
        "n_mentions": stats.mentions,
        "by_type": stats.by_type,
        "by_assertion": stats.by_assertion,
        "with_candidates": stats.with_candidates,
        "dropped_invariant": stats.dropped_invariant,
        "dropped_overlap": stats.dropped_overlap,
        "dropped_threshold": stats.dropped_threshold,
        "dropped_type_confidence": stats.dropped_type_confidence,
        "batch_mask_resolution": asdict(batch_resolution),
        "by_link_path": stats.by_link_path,
        "schema_errors": len(schema_errors),
        "errors": stats.errors,
    }
    (args.output / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{stats.files} file · {stats.mentions} mention "
          f"· {stats.with_candidates} có candidates")
    print(f"  theo type      : {stats.by_type}")
    print(f"  theo assertion : {stats.by_assertion or '{}'}")
    print(f"  loại (bất biến): {stats.dropped_invariant} · "
          f"(chồng lấn): {stats.dropped_overlap} · "
          f"(cắt tập): {stats.dropped_threshold} · "
          f"(p_t thấp): {stats.dropped_type_confidence}")
    if args.extractor == "v3" and not args.no_batch_mask_resolution:
        print(
            "  mask liên VB   : "
            f"{batch_resolution.resolved} resolve · "
            f"{batch_resolution.conflicts} conflict"
        )

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

    if args.zip and packaged is not None:
        print(f"  đóng gói       : {args.zip} ({packaged[0]} file, "
              f"sha256={packaged[1][:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
