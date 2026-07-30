"""The inference entry point. `python3 -m smart_medic.cli run --input DIR --output DIR`

This is wiring, not logic: it walks the eight layers in order and holds no rule,
no threshold and no pattern of its own. `notebooks/runbook.ipynb` cells 4 and 5
call exactly this command, and `pyproject.toml` exposes it as `smart-medic`.

    io/ → layout/ → extract/ → decision/ → validate/

At P1 only lane R of `extract/` exists, so no checkpoint is loaded and no GPU is
touched. `assertion/` (P4) and `linking/` (P5) are not in the chain yet; every
record therefore carries empty `assertions` and `candidates`, which is the correct
answer for the two lab types and a score of 0 — the same 0 a wrong guess earns.

Two things it prints on every run because they are inputs, not decoration:

* **entity density per file** — the key into `decision.emit_threshold`
* **the emit threshold it selected**, and from which row

Writing goes through `validate/emit_json.py` and nowhere else. That module raises
on an offset mismatch rather than repairing it, which is the whole point: setting
`text = raw[start:end]` would make the check pass by construction and hide the NFC
bug it exists to catch.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .decision import emit
from .extract import RecallFloorReport, recall_floor
from .io.corpus import load_documents
from .io.document import Document
from .layout.kv import split_units
from .layout.lines import split_lines
from .layout.outline import SectionIndex, build_outline
from .validate import emit_json, schema

__all__ = ["main", "run"]


def run(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    numbered: bool = True,
    check_codes: bool = True,
    quiet: bool = False,
) -> tuple[RecallFloorReport, emit_json.EmitReport, emit.ThresholdChoice]:
    """Extract, decide, validate, write. Returns the three reports.

    Runs in two passes on purpose. The emit threshold is keyed by the density of
    *this* run, so the candidate density has to be known before anything can be
    gated — a single streaming pass would have to guess it.
    """
    docs = load_documents(input_dir, numbered=numbered)
    if not docs:
        raise FileNotFoundError(f"no .txt documents under {input_dir}")

    def say(*a) -> None:
        if not quiet:
            print(*a)

    # ── pass 1 · propose ──────────────────────────────────────────────────────
    t0 = time.perf_counter()
    report = RecallFloorReport()
    proposals: list[tuple[Document, list, object]] = []
    for doc in docs:
        lines = split_lines(doc)
        units = split_units(doc, lines)
        # The outline is built here rather than inside `finalize` because the
        # assertion scope needs the SECTION a span sits in, not the nearest
        # heading above it: a section closes when a same-or-shallower heading
        # arrives, so "Tiền sử bệnh nội khoa" stops governing at the next
        # top-level heading instead of leaking isHistorical down the document.
        section_at = SectionIndex(build_outline(lines, len(doc.raw)))
        proposals.append((doc, recall_floor(doc, lines, units, report), section_at))
    extract_s = time.perf_counter() - t0
    say(f"extract    : {report.summary()}")
    say(f"             {extract_s:.1f}s, no checkpoint loaded")

    # ── pass 2 · decide ───────────────────────────────────────────────────────
    choice = emit.select_threshold(report.density())
    say(f"decision   : {choice.summary()}")
    if choice.warning():
        say(choice.warning())

    records = [
        (doc, emit.finalize(doc, spans, choice, section_at))
        for doc, spans, section_at in proposals
    ]

    flat = [r for _, rs in records for r in rs]
    flagged = sum(1 for r in flat if r["assertions"])
    say(
        f"assertion  : {flagged}/{len(flat)} entities flagged "
        f"({flagged / max(len(flat), 1):.1%}) · "
        f"isNegated {sum(1 for r in flat if 'isNegated' in r['assertions'])} · "
        f"isHistorical {sum(1 for r in flat if 'isHistorical' in r['assertions'])}"
    )
    # A rate outside the band means we are spending points we already hold, so it
    # stops the run rather than warning into a log nobody reads before submitting.
    rate_warning = emit.assertion_rate_check(flat)
    if rate_warning:
        raise ValueError(rate_warning)

    # ── validate + write ──────────────────────────────────────────────────────
    codes = schema.load_code_index() if check_codes else None
    written = emit_json.emit_corpus(
        records,
        output_dir,
        codes=codes,
        expect_ids=[d.doc_id for d in docs],
    )
    say(f"validate   : {written.summary()}")
    say(f"total      : {time.perf_counter() - t0:.1f}s → {output_dir}")
    return report, written, choice


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m smart_medic.cli",
        description=__doc__.split("\n")[0],
    )
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="extract → decide → validate → write")
    r.add_argument("--input", required=True, type=Path, help="directory of *.txt")
    r.add_argument("--output", required=True, type=Path, help="directory for *.json")
    r.add_argument(
        "--any-name",
        action="store_true",
        help="accept non-numbered filenames (gold corpora); default expects 1.txt…N.txt",
    )
    r.add_argument(
        "--no-kb-check",
        action="store_true",
        help="skip 'every code resolves in the packaged KB' — only if the KB is absent",
    )
    r.add_argument("--quiet", action="store_true")

    args = ap.parse_args(argv)
    if args.command != "run":
        ap.error(f"unknown command {args.command!r}")

    try:
        run(
            args.input,
            args.output,
            numbered=not args.any_name,
            check_codes=not args.no_kb_check,
            quiet=args.quiet,
        )
    except Exception as exc:  # noqa: BLE001 — a CLI reports, it does not traceback
        print(f"\n✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
