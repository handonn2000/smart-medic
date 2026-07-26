#!/usr/bin/env python3
"""Verify the deployable v3 bundle without Git metadata or raw KB sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}"
        )
    return result.stdout


def numeric_outputs(directory: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(directory.glob("*.json"))
        if path.stem.isdigit()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a clean Smart Medic bundle")
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[1],
        help="repository root to bundle",
    )
    args = parser.parse_args(argv)
    source = args.source.resolve()

    with tempfile.TemporaryDirectory(prefix="smart-medic-v3-") as tmp:
        bundle = Path(tmp) / "bundle"
        bundle.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
        shutil.copytree(source / "src", bundle / "src", ignore=ignore)
        shutil.copytree(source / "data/kb", bundle / "data/kb", ignore=ignore)
        fixture = source / "tests/fixtures/v3_metric"
        shutil.copytree(fixture, bundle / "fixture", ignore=ignore)

        forbidden = bundle / "data/knowledge_base"
        if forbidden.exists():
            raise RuntimeError(f"raw knowledge source leaked into bundle: {forbidden}")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(bundle / "src")
        manifests: list[dict] = []
        zip_paths: list[Path] = []
        output_dirs: list[Path] = []
        for number in (1, 2):
            output = bundle / f"run{number}"
            archive = bundle / f"submission{number}.zip"
            output_dirs.append(output)
            zip_paths.append(archive)
            run([
                sys.executable, "-m", "smart_medic.infer",
                "--extractor", "v3",
                "--input", str(bundle / "fixture/input"),
                "--output", str(output),
                "--kb", str(bundle / "data/kb"),
                "--zip", str(archive),
                "--explain",
            ], cwd=bundle, env=env)
            manifests.append(json.loads(
                (output / "run_manifest.json").read_text(encoding="utf-8")
            ))

        if numeric_outputs(output_dirs[0]) != numeric_outputs(output_dirs[1]):
            raise RuntimeError("numeric inference output changed between identical runs")
        if (output_dirs[0] / "explain.json").read_bytes() != (
            output_dirs[1] / "explain.json"
        ).read_bytes():
            raise RuntimeError("explain output changed between identical runs")
        if sha256(zip_paths[0]) != sha256(zip_paths[1]):
            raise RuntimeError("submission ZIP changed between identical runs")
        for manifest, archive in zip(manifests, zip_paths):
            if manifest["submission"]["sha256"] != sha256(archive):
                raise RuntimeError("run manifest does not match submission ZIP")
        if manifests[0]["output_sha256"] != manifests[1]["output_sha256"]:
            raise RuntimeError("output fingerprint changed between identical runs")
        if any(manifest["git_sha"] != "unknown" for manifest in manifests):
            raise RuntimeError("Git metadata leaked into the clean deployment bundle")

        metric_path = bundle / "metric.json"
        run([
            sys.executable, "-m", "smart_medic.metric_simulator",
            "--explain", str(output_dirs[0] / "explain.json"),
            "--gold", str(bundle / "fixture/gold"),
            "--start", "0.80", "--stop", "0.80", "--step", "0.05",
            "--output", str(metric_path),
        ], cwd=bundle, env=env)
        metric = json.loads(metric_path.read_text(encoding="utf-8"))
        point = metric["points"][0]
        if metric["mode"] != "gold" or point["final_score"] != 1.0:
            raise RuntimeError(f"curated metric regression: {point}")

        print(
            "CLEAN_SMOKE_OK "
            f"files={manifests[0]['n_files']} "
            f"mentions={manifests[0]['n_mentions']} "
            f"output_sha256={manifests[0]['output_sha256']} "
            f"zip_sha256={sha256(zip_paths[0])} "
            f"metric={point['final_score']:.4f} raw_kb=absent"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
