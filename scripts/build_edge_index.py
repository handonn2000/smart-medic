#!/usr/bin/env python3
"""Precompute `data/artifacts/edge_index.json` from the RxNorm drops.

    python3 scripts/build_edge_index.py

`linking/edge_verify.py` needs two facts about an RxCUI: has it been retired in
favour of a successor (RXNCUI.RRF), and does it carry semantic type T200
(RXNSTY.RRF). It was reading both raw files at inference time, which is 22 MB of
licence-gated input for two lookups — and those files are gitignored, so a clean
checkout raised `ConfigError` on the first drug span. Under PRD §5 an
un-rerunnable submission is disqualified.

The columns actually used are 22.330 retirement pairs and 249.563 T200 RxCUIs.
As JSON that is ~2.4 MB, small enough to track in git, so the organisers get a
repository that runs without the raw drops.

Build-time only: `src/` never imports `scripts/`. Re-run after refreshing the
RxNorm release, and commit the result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from smart_medic.io.config import kb_paths, load_pipeline, require  # noqa: E402

OUT = REPO / "data" / "artifacts" / "edge_index.json"


def build() -> dict:
    root = Path(kb_paths()["root"])

    retired: dict[str, str] = {}
    path = root / "RXNCUI.RRF"
    if not path.is_file():
        raise SystemExit(f"{path} not found — this is a build-time script; it needs "
                         f"the raw RxNorm drop that inference no longer reads.")
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("|")
            if len(f) > 4 and f[0] and f[4] and f[0] != f[4]:
                retired[f[0]] = f[4]

    # The excluded semantic types come from the config, not from a literal here:
    # `linking.exclude_sty` is a reviewable knob (ADR 0001 argues T200 and
    # explicitly rejects a T109/T121 whitelist), and baking T200 into the builder
    # would silently freeze it. The runtime checks that the index it loads was
    # built for the config it is running under.
    exclude = sorted(str(s) for s in require(load_pipeline(), "linking.exclude_sty"))

    excluded: set[str] = set()
    path = root / "RXNSTY.RRF"
    if not path.is_file():
        raise SystemExit(f"{path} not found")
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            f = line.split("|")
            if len(f) > 1 and f[1] in exclude:
                excluded.add(f[0])

    return {
        "_source": "RXNCUI.RRF + RXNSTY.RRF, built by scripts/build_edge_index.py",
        "exclude_sty": exclude,
        "retired": dict(sorted(retired.items())),
        "excluded_sty_rxcui": sorted(excluded),
    }


if __name__ == "__main__":
    index = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a fixed separator: this file is committed, so a rebuild
    # that only reorders it would produce a meaningless diff.
    OUT.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"{OUT.relative_to(REPO)}: {len(index['retired'])} retired pairs, "
        f"{len(index['excluded_sty_rxcui'])} excluded-STY codes, {OUT.stat().st_size / 1048576:.1f} MB"
    )
