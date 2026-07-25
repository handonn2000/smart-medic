"""CLI for testing the medical concept extraction model.

Usage:
    python test.py -t "<input_text>"
    python test.py -f <input_file>
"""

import argparse
import json
import sys
from pathlib import Path

# Allow `python test.py` (from src/) and `python src/test.py` (from project root)
_SRC_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _SRC_DIR.parent
for path in (_ROOT_DIR, _SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from inference import MedicalExtractor, get_device


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
    parser.add_argument(
        "--model",
        default="pho_bert_crf_medical.pth",
        help="Path to trained model weights (default: pho_bert_crf_medical.pth)",
    )
    return parser.parse_args()


def load_input(args) -> str:
    if args.file is not None:
        path = Path(args.file)
        if not path.is_file():
            raise FileNotFoundError(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8")
    return args.text


def main():
    args = parse_args()
    text = load_input(args)

    extractor = MedicalExtractor(model_path=args.model, device=get_device())
    result = extractor.extract(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
