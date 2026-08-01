#!/usr/bin/env python3
"""Reconstruct entity phrases from a BIO tagging file.

    python scripts/bio_to_text.py data/train_generated.txt
    python scripts/bio_to_text.py data/train_generated.txt -o entities.txt

Input: one ``token label`` per line (token may contain spaces; label is the last
field), blank line between samples — same as src/dataset.py.

Output: one entity per line, tokens joined exactly as they appear in the file::

    đại tiện B-TRIEU_CHUNG
    ra I-TRIEU_CHUNG
    máu I-TRIEU_CHUNG
    đỏ I-TRIEU_CHUNG
    tươi I-TRIEU_CHUNG

becomes::

    đại tiện ra máu đỏ tươi -> TRIEU_CHUNG, line 89247 -> 89251
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_bio_line(line: str) -> tuple[str, str] | None:
    """Return (token, label) with the token kept as written, or None if blank."""
    line = line.rstrip("\n\r")
    if not line.strip():
        return None
    # rsplit so multi-word tokens like "đại tiện" stay intact
    parts = line.rsplit(None, 1)
    if len(parts) != 2:
        raise ValueError(f"missing label: {line!r}")
    return parts[0], parts[1]


def bio_type(label: str) -> str | None:
    if label.startswith(("B-", "I-")) and len(label) > 2:
        return label[2:]
    return None

def bio_type_drug_diagnose(label: str) -> str | None:
    if label.startswith(("B-", "I-")) and len(label) > 2:
        ent = label[2:]
        if ent in ('BENH', 'THUOC'):
            return ent
    return None


def reconstruct_entities(path: Path):
    """Yield one ``<tokens> -> <TYPE>, line <start> -> <end>`` per BIO span."""
    tokens: list[str] = []
    etype: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    def emit() -> str | None:
        nonlocal etype, start_line, end_line
        if etype is None or not tokens or start_line is None or end_line is None:
            tokens.clear()
            etype = start_line = end_line = None
            return None
        # join with a single space; do not alter token text
        line = (
            f"{' '.join(tokens)} -> {etype}, line {start_line} -> {end_line}"
        )
        tokens.clear()
        etype = start_line = end_line = None
        return line

    with path.open(encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            try:
                parsed = parse_bio_line(raw)
            except ValueError as exc:
                raise SystemExit(f"{path}:{number}: {exc}") from exc

            if parsed is None:
                out = emit()
                if out:
                    yield out
                continue

            word, label = parsed
            kind = bio_type_drug_diagnose(label)

            if kind is None:  # O or unknown
                out = emit()
                if out:
                    yield out
                continue

            if label.startswith("I-") and etype == kind:
                tokens.append(word)
                end_line = number
            else:
                out = emit()
                if out:
                    yield out
                tokens.append(word)
                etype = kind
                start_line = end_line = number

    out = emit()
    if out:
        yield out


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reconstruct BIO entities to one "
                    "'text -> TYPE, line START -> END' line each.")
    parser.add_argument("input", type=Path, help="BIO input file")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="write here (default: stdout)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        sys.exit(f"file not found: {args.input}")

    lines = list(reconstruct_entities(args.input))
    text = "\n".join(lines) + ("\n" if lines else "")

    if args.out is None:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {len(lines)} entities -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
