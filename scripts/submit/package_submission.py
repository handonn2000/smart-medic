#!/usr/bin/env python3
"""Build `output.zip` and the immutable run record. Build-time, not inference.

    python3 scripts/submit/package_submission.py
    python3 scripts/submit/package_submission.py --pred data/output --probe A

What it produces:

    output.zip                                  the file that gets uploaded
    runs/<ISO8601>_<git-sha7>/
        output/1.json … 100.json                exactly as submitted
        output.zip                              byte-identical copy
        manifest.json                           the 10 required fields

Three decisions worth knowing about:

1. **It stages, it does not zip `data/output` in place.** `data/output/` also holds
   `run_manifest.json`, `explain.json` and two `metric_*.json` sidecars. Our own
   `load_dir()` skips non-record files by shape; the organisers' scorer may not.
   `-x '*/.*'` only excludes dotfiles, so it would carry all four into the archive.
   Records are re-emitted through `validate.emit_json` into a clean staging
   directory, and the archive is built from that.

2. **It writes the archive with `zipfile`, not the `zip` binary.** `zip` stores
   mtimes and walks the filesystem in directory order, so two runs of identical
   predictions never produce identical archives. `runs/README.md` asks for a
   reproducibility rehearsal that ends in `cmp /tmp/out.zip runs/<ts>/output.zip`
   — that comparison is only meaningful if the writer is deterministic. Members
   are written in numeric order with a fixed timestamp. The archive *structure* is
   the documented one: `output/` sits inside the archive.

3. **It verifies the archive it just wrote**, reading the members back out of the
   zip rather than trusting the variables that produced them. Seven checks; any
   failure is a non-zero exit and no upload.

It never submits. That is a human decision, five per day.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from smart_medic import validate                              # noqa: E402
from smart_medic.eval.scoring import MetricConfig             # noqa: E402
from smart_medic.io import (                                  # noqa: E402
    ConfigError,
    Document,
    kb_paths,
    load_models,
    load_yaml,
    read_raw,
)

RECORD = re.compile(r"^\d+$")
#: Fixed member timestamp, so identical predictions give a byte-identical archive.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
#: Anything matching these must never reach the archive.
FORBIDDEN = ("run_manifest.json", "metric_internal.json", ".DS_Store", "__pycache__")


# ──────────────────────────────── helpers ────────────────────────────────
def rel(path: Path) -> str:
    """Repo-relative when it can be; absolute otherwise (rehearsals run elsewhere)."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def sh(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPO, text=True, capture_output=True, check=False
    ).stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kb_hashes() -> dict[str, str]:
    """sha256 of every KB file, cached on (size, mtime) — RXNREL alone is 527MB."""
    root = kb_paths()["root"]
    cache_path = REPO / "data" / "artifacts" / "kb_hashes.json"
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )
    out: dict[str, str] = {}
    dirty = False
    for p in sorted(root.glob("*")):
        if not p.is_file():
            continue
        stat = p.stat()
        key = f"{p.name}:{stat.st_size}:{int(stat.st_mtime)}"
        if key not in cache:
            cache[key] = sha256_file(p)
            dirty = True
        out[p.name] = cache[key]
    if dirty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out


def config_hashes() -> dict[str, str]:
    out = {}
    for folder in ("configs", "resources"):
        for p in sorted((REPO / folder).rglob("*.yaml")):
            out[str(p.relative_to(REPO))] = sha256_file(p)
    return out


def numbered(directory: Path, suffix: str) -> list[Path]:
    return sorted(
        (p for p in directory.glob(f"*{suffix}") if RECORD.match(p.stem)),
        key=lambda p: int(p.stem),
    )


# ─────────────────────────────── staging ───────────────────────────────
def stage(pred_dir: Path, source_dir: Path, stage_dir: Path, codes) -> validate.EmitReport:
    """Re-emit every record through the hard gate into a clean directory."""
    sources = {p.stem: p for p in numbered(source_dir, ".txt")}
    items = []
    for record in numbered(pred_dir, ".json"):
        src = sources.get(record.stem)
        if src is None:
            raise SystemExit(
                f"{record} has no matching {source_dir}/{record.stem}.txt — refusing "
                f"to package a prediction whose source cannot be verified"
            )
        entities = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(entities, list):
            raise SystemExit(f"{record}: top level must be a JSON list")
        items.append((Document(doc_id=record.stem, raw=read_raw(src)), entities))

    expected = sorted(sources, key=int)
    missing = [i for i in expected if i not in {d.doc_id for d, _ in items}]
    for doc_id in missing:
        # a hole is a zero, not a skip: emit an explicit empty list
        items.append((Document(doc_id=doc_id, raw=read_raw(sources[doc_id])), []))
    if missing:
        print(f"  !! {len(missing)} document(s) had no prediction: {missing[:10]}")
        print("     wrote an explicit empty list for each (a missing FILE scores 0)")

    items.sort(key=lambda pair: int(pair[0].doc_id))
    return validate.emit_corpus(items, stage_dir, codes=codes, expect_ids=expected)


def write_zip(stage_dir: Path, zip_path: Path) -> None:
    """`output/` inside the archive, members in numeric order, fixed timestamps."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for record in numbered(stage_dir, ".json"):
            info = zipfile.ZipInfo(f"{stage_dir.name}/{record.name}", ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, record.read_bytes())


# ─────────────────────────────── verification ───────────────────────────────
def verify_archive(zip_path: Path, source_dir: Path, expect: int, codes) -> list[str]:
    """Seven checks, read back out of the archive. Any failure blocks the upload."""
    errs: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # 1 · exactly `expect` members
        if len(names) != expect:
            errs.append(f"[1] archive holds {len(names)} members, expected {expect}")

        # 2 · every member is output/<int>.json
        shape = re.compile(r"^output/\d+\.json$")
        for n in names:
            if not shape.match(n):
                errs.append(f"[2] member {n!r} is not output/<n>.json")

        # 3 · ids are exactly 1..expect, no holes, no duplicates
        ids = sorted(
            int(Path(n).stem) for n in names if shape.match(n)
        )
        if ids != list(range(1, expect + 1)):
            have = set(ids)
            errs.append(
                f"[3] ids are not 1..{expect}: missing "
                f"{sorted(set(range(1, expect + 1)) - have)[:10]}, "
                f"duplicates {sorted({i for i in ids if ids.count(i) > 1})[:10]}"
            )

        # 4 · no sidecars, dotfiles or caches
        for n in names:
            base = Path(n).name
            if base.startswith(".") or any(f in n for f in FORBIDDEN):
                errs.append(f"[4] forbidden member in archive: {n!r}")

        # 5 · valid UTF-8 JSON list, no BOM, newline at end
        payloads: dict[str, list] = {}
        for n in names:
            if not shape.match(n):
                continue
            blob = zf.read(n)
            if blob.startswith(b"\xef\xbb\xbf"):
                errs.append(f"[5] {n} starts with a UTF-8 BOM")
                continue
            if not blob.endswith(b"\n"):
                errs.append(f"[5] {n} has no newline at end of file")
            try:
                obj = json.loads(blob.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errs.append(f"[5] {n}: {exc}")
                continue
            if not isinstance(obj, list):
                errs.append(f"[5] {n}: top level must be a list")
                continue
            payloads[Path(n).stem] = obj

        # 6 · byte-exact offsets against the untouched sources
        # 7 · the full schema, including codes and nesting
        for stem, entities in sorted(payloads.items(), key=lambda kv: int(kv[0])):
            src = source_dir / f"{stem}.txt"
            if not src.exists():
                errs.append(f"[6] {stem}.json has no source {src}")
                continue
            raw = read_raw(src)
            for e in validate.offsets.check(raw, entities, f"{stem}.json"):
                errs.append(f"[6] {e}")
            for e in validate.schema.check(entities, raw, codes, f"{stem}.json"):
                errs.append(f"[7] {e}")
    return errs


# ─────────────────────────────── manifest ───────────────────────────────
def build_manifest(
    *,
    probe: str,
    report: validate.EmitReport,
    freeze: bool,
) -> dict:
    models = load_models()
    budget_ok = models.params_enabled < models.budget
    manifest_sha = REPO / "tests" / "data_test_manifest.json"
    return {
        # 1
        "git_sha": sh("git", "rev-parse", "HEAD"),
        "git_dirty": bool(sh("git", "status", "--porcelain")),
        # 2
        "metric_config_hash": MetricConfig().hash(),
        # 3
        "models": models.manifest_entries(),
        # 4
        "params_total": models.params_enabled,
        "params_budget": models.budget,
        "params_budget_ok": budget_ok,
        # 5
        "seed": load_yaml("models.yaml").get("seed"),
        # 6
        "lib_versions": (
            sh(sys.executable, "-m", "pip", "freeze").splitlines() if freeze else []
        ),
        # 7
        "input_manifest_sha256": (
            sha256_file(manifest_sha) if manifest_sha.exists() else None
        ),
        # 8
        "kb_versions": kb_hashes(),
        # 9
        "config_files_sha256": config_hashes(),
        # 10
        "probe_variant": probe,
        # context the run record is useless without
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "entity_counts": report.entity_counts,
        "entities_total": report.total_entities,
        "entity_density_per_file": round(report.density(), 4),
        "enforcement": {
            k: v for k, v in vars(report.enforce).items() if k != "notes"
        },
    }


# ────────────────────────────────── main ──────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pred", default=REPO / "data" / "output", type=Path)
    ap.add_argument("--source", default=REPO / "data" / "test", type=Path)
    ap.add_argument("--out", default=REPO / "output.zip", type=Path)
    ap.add_argument("--expect", default=100, type=int)
    ap.add_argument(
        "--probe", default="full", help="which probe this run answers, or 'full'"
    )
    ap.add_argument(
        "--no-freeze", action="store_true", help="skip pip freeze (faster, worse record)"
    )
    ap.add_argument(
        "--no-kb-check",
        action="store_true",
        help="skip 'code exists in KB' — only if the KB is genuinely unavailable",
    )
    ap.add_argument("--run-dir", type=Path, help="override runs/<ts>_<sha> (rehearsals)")
    ap.add_argument(
        "--no-run-record",
        action="store_true",
        help="write only the zip, no runs/ record — for the container rehearsal",
    )
    args = ap.parse_args(argv)

    try:
        codes = None if args.no_kb_check else validate.load_code_index()
    except ConfigError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2
    if codes is None:
        print("  !! code-in-KB check DISABLED (--no-kb-check)")

    sha7 = sh("git", "rev-parse", "--short=7", "HEAD") or "nogit"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
    if args.run_dir:
        run_dir = args.run_dir
    else:
        # runs/ is never overwritten. The stamp has minute resolution, so a second
        # build inside the same minute gets a suffix rather than clobbering.
        run_dir = REPO / "runs" / f"{stamp}_{sha7}"
        n = 1
        while run_dir.exists():
            n += 1
            run_dir = REPO / "runs" / f"{stamp}_{sha7}-{n}"
    stage_dir = run_dir / "output"

    print(f"run        : {rel(run_dir)}")
    print(f"predictions: {rel(args.pred)}  ->  staging")
    try:
        report = stage(args.pred, args.source, stage_dir, codes)
    except validate.OffsetViolation as exc:
        # Never a data quirk: some stage computed an offset on a normalised copy
        # and skipped to_raw(). Refuse to package rather than ship silent zeros.
        print(f"\n!! OFFSET GATE FAILED — nothing packaged.\n{exc}", file=sys.stderr)
        return 1
    print(f"  {report.summary()}")
    if report.enforce.notes:
        for note in report.enforce.notes[:10]:
            print(f"    - {note}")

    run_zip = run_dir / "output.zip"
    write_zip(stage_dir, run_zip)

    errs = verify_archive(run_zip, args.source, args.expect, codes)
    if errs:
        print(f"\n!! {len(errs)} archive violation(s) — NOT writing {args.out.name}:")
        for e in errs[:25]:
            print("   ", e.replace("\n", "\n    "))
        return 1

    args.out.write_bytes(run_zip.read_bytes())
    manifest = build_manifest(probe=args.probe, report=report, freeze=not args.no_freeze)
    if not args.no_run_record:
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print("\n✓ 7/7 archive checks passed")
    print(f"  {rel(args.out)}  ({args.out.stat().st_size:,} bytes)")
    if not args.no_run_record:
        print(f"  {rel(run_dir / 'manifest.json')}")
    if manifest["git_dirty"]:
        print("\n  !! WORKING TREE IS DIRTY — this build must NOT be submitted.")
        print("     runs/README.md: a dirty tree means the run cannot be reproduced.")
    if not manifest["params_budget_ok"]:
        print("\n  !! PARAMETER BUDGET EXCEEDED — do not submit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
