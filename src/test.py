"""CLI for testing the medical concept extraction model.

Usage:
    python test.py -t "<input_text>"
    python test.py -f <input_file>
    python test.py -d <input_dir> [-o <output_dir>]
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Allow `python test.py` (from src/) and `python src/test.py` (from project root)
_SRC_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _SRC_DIR.parent
for path in (_ROOT_DIR, _SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from inference import MedicalExtractor, get_device

DEFAULT_OUTPUT_DIR = _ROOT_DIR / "data" / "output"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test medical concept extraction on Vietnamese clinical text."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-t",
        dest="text",
        metavar="INPUT_TEXT",
        help="Free-text input to pass to the model",
    )
    group.add_argument(
        "-f",
        dest="file",
        metavar="INPUT_FILE",
        help="Path to a file containing the input text",
    )
    group.add_argument(
        "-d",
        dest="input_dir",
        metavar="INPUT_DIR",
        help="Folder of .txt records; writes one .json per record instead of printing",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="output_dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where -d writes its JSON (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model",
        default="pho_bert_crf_medical.pth",
        help="Path to trained model weights (default: pho_bert_crf_medical.pth)",
    )
    parser.add_argument(
        "--linker",
        choices=["rapidfuzz", "sapbert"],
        default="sapbert",
        help="ICD diagnosis matcher: sapbert (default) or rapidfuzz",
    )
    return parser.parse_args()


def load_input(args) -> str:
    if args.file is not None:
        path = Path(args.file)
        if not path.is_file():
            raise FileNotFoundError(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8")
    return args.text


def by_number(path: Path):
    """Order 1, 2, …, 10 rather than 1, 10, 2 — the test records are numbered."""
    return (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem)


def write_json(concepts, path: Path) -> None:
    path.write_text(json.dumps(concepts, ensure_ascii=False, indent=2), encoding="utf-8")


def run_folder(extractor, input_dir: Path, output_dir: Path) -> int:
    """Predict every .txt in `input_dir`, writing `<stem>.json` into `output_dir`."""
    files = sorted(input_dir.glob("*.txt"), key=by_number)
    if not files:
        raise SystemExit(f"No .txt files in {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    total = failed = misplaced = 0

    for number, path in enumerate(files, 1):
        raw = path.read_text(encoding="utf-8")
        clock = time.perf_counter()
        try:
            concepts = extractor.extract(raw)
        except Exception as err:  # one unreadable record must not lose the other 99
            failed += 1
            print(f"  [{number:3}/{len(files)}] {path.name:14} FAILED — {err}")
            continue

        # position is what the scorer pairs predictions on, so a span whose text is not
        # the input slice it claims cannot match anything. Cheap to check, hard to notice.
        misplaced += sum(1 for c in concepts
                         if raw[c["position"][0]:c["position"][1]] != c["text"])

        write_json(concepts, output_dir / f"{path.stem}.json")
        total += len(concepts)
        print(f"  [{number:3}/{len(files)}] {path.name:14} -> "
              f"{path.stem + '.json':14}{len(concepts):5} concepts  "
              f"{time.perf_counter() - clock:5.1f}s")

    print(f"\n  {len(files) - failed}/{len(files)} records -> {output_dir}")
    print(f"  {total} concepts, {total / max(1, len(files) - failed):.1f} per record, "
          f"{time.perf_counter() - started:.0f}s total")
    if misplaced:
        print(f"  WARNING: {misplaced} concepts whose text is not the slice at their "
              f"position — they cannot match any gold concept")

    stale = {p.stem for p in output_dir.glob("*.json")} - {p.stem for p in files}
    if stale:
        print(f"  WARNING: {len(stale)} older .json in {output_dir} have no record in "
              f"{input_dir} ({', '.join(sorted(stale)[:5])}…); delete before zipping")
    return 1 if failed else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    extractor = MedicalExtractor(
        model_path=args.model, device=get_device(), match_backend=args.linker
    )
    if args.input_dir:
        return run_folder(extractor, Path(args.input_dir), Path(args.output_dir))

    print(json.dumps(extractor.extract(load_input(args)), ensure_ascii=False, indent=2))
    return 0

# Usage:
# Test with testset: python src/test.py -d data/test -o data/output --model models/pho_bert_crf_medical.pth
# Test with holdout: python src/test.py -d data/holdout/text -o data/holdout/pred --model models/pho_bert_crf_medical.pth
# RapidFuzz ICD: python src/test.py -t "viêm phổi" --linker rapidfuzz --model models/pho_bert_crf_medical.pth
if __name__ == "__main__":
    sys.exit(main())
