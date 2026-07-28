#!/usr/bin/env python3
"""Build controlled v3.3 RxNorm-version submission variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build current/legacy/both RxNorm variants for v3.3"
    )
    parser.add_argument("--input", type=Path, default=ROOT / "data/test")
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "data/v3_3_variants",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("current", "legacy", "both"),
        default=("current", "legacy", "both"),
    )
    args = parser.parse_args(argv)
    args.destination.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    summary: dict[str, dict[str, str | int]] = {}
    for mode in args.modes:
        output = args.destination / mode / "output"
        archive = args.destination / f"output_v3_3_{mode}.zip"
        command = [
            sys.executable,
            "-m",
            "smart_medic.infer",
            "--extractor",
            "v3",
            "--input",
            str(args.input),
            "--output",
            str(output),
            "--zip",
            str(archive),
            "--rxnorm-output-mode",
            mode,
            "--explain",
        ]
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        manifest = json.loads(
            (output / "run_manifest.json").read_text(encoding="utf-8")
        )
        summary[mode] = {
            "archive": str(archive),
            "sha256": sha256(archive),
            "files": manifest["n_files"],
            "mentions": manifest["n_mentions"],
            "with_candidates": manifest["with_candidates"],
        }

    report = args.destination / "variants.json"
    report.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

