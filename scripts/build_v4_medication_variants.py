#!/usr/bin/env python3
"""Build controlled strict/hierarchical v4 medication artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FROZEN_V3_OUTPUT_SHA256 = (
    "253026321c4b116ac81047dcf2ba66ed922fbc87282d9b4b3b6fe9d6a993fc24"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build controlled v4 medication-specificity variants"
    )
    parser.add_argument("--input", type=Path, default=ROOT / "data/test")
    parser.add_argument("--kb", type=Path, default=ROOT / "data/kb")
    parser.add_argument(
        "--destination", type=Path, default=ROOT / "data/v4_medication_variants"
    )
    parser.add_argument(
        "--specificities", nargs="+", choices=("strict", "hierarchical"),
        default=("strict", "hierarchical"),
    )
    parser.add_argument(
        "--drug-aliases", type=Path, default=None,
        help="optional reviewed alias CSV; checksum is recorded by inference",
    )
    args = parser.parse_args(argv)
    args.destination.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    summary: dict[str, dict] = {}
    for specificity in args.specificities:
        output = args.destination / specificity / "output"
        archive = args.destination / f"output_v4_med_{specificity}.zip"
        command = [
            sys.executable, "-m", "smart_medic.infer",
            "--extractor", "v4",
            "--rxnorm-specificity", specificity,
            "--input", str(args.input),
            "--output", str(output),
            "--kb", str(args.kb),
            "--zip", str(archive),
            "--explain",
        ]
        if args.drug_aliases is not None:
            command.extend(["--drug-aliases", str(args.drug_aliases)])
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        manifest = json.loads(
            (output / "run_manifest.json").read_text(encoding="utf-8")
        )
        if (
            specificity == "strict"
            and args.drug_aliases is None
            and manifest["output_sha256"] != FROZEN_V3_OUTPUT_SHA256
        ):
            raise RuntimeError(
                "v4 strict no longer reproduces the frozen v3.3 numeric output: "
                f"{manifest['output_sha256']}"
            )
        summary[specificity] = {
            "archive": str(archive),
            "archive_sha256": sha256(archive),
            "output_sha256": manifest["output_sha256"],
            "files": manifest["n_files"],
            "mentions": manifest["n_mentions"],
            "with_candidates": manifest["with_candidates"],
            "by_link_path": manifest["by_link_path"],
        }

    report = args.destination / "variants.json"
    report.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
