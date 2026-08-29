#!/usr/bin/env python3
"""Gán nhãn gazetteer (ICD10_VN + RXNORM + cụm triệu chứng/xét nghiệm) lên data/test,
rồi ghi ra BIO để xem dạng huấn luyện — KHÔNG dùng để train.

    python scripts/build_bio_from_test.py
    -> data/bio_generated_no_train.txt
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from gen_sample_data import (  # noqa: E402
    RESULT_PHRASES,
    build_term_mapping,
    load_icd,
    load_rxnorm,
    remove_overlapping_spans,
    sweep_gazetteers,
    _phrase_gazetteer,
    TOKEN_RE,
)
from prepare_training_data import (  # noqa: E402
    blocks_of,
    label_words,
    make_segmenter,
    usable_spans,
    write_bio,
)
from tokenization import segment_document  # noqa: E402

TEST_DIR = REPO / "data" / "test"
OUT = REPO / "data" / "bio_generated_no_train.txt"


def by_number(path: Path) -> tuple[int, str]:
    return (int(path.stem) if path.stem.isdigit() else 0, path.stem)


def sweep_results(text: str) -> list[dict]:
    """Bổ sung KẾT_QUẢ_XÉT_NGHIỆM từ RESULT_PHRASES (không có trong sweep_gazetteers)."""
    found = []
    for start, end, _ in _phrase_gazetteer("RES", RESULT_PHRASES).find_all(text):
        if len(TOKEN_RE.findall(text[start:end])) < 2:
            continue
        found.append({
            "text": text[start:end],
            "type": "KẾT_QUẢ_XÉT_NGHIỆM",
            "candidates": [],
            "assertions": [],
            "position": [start, end],
            "_src": 1,
        })
    return found


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(TEST_DIR.glob("*.txt"), key=by_number)
    if not files:
        sys.exit(f"không có file trong {TEST_DIR}")

    print("  đang nạp ICD10_VN.csv + RXNORM.csv …")
    icd_gaz, rx_gaz = build_term_mapping(load_icd(), load_rxnorm())
    print(f"  gazetteer: {len(icd_gaz.exact)} cụm ICD | {len(rx_gaz.exact)} tên thuốc")

    segment_line = make_segmenter()
    report = collections.Counter()
    types = collections.Counter()
    blocks = []

    for path in files:
        raw = path.read_text(encoding="utf-8")
        anns = remove_overlapping_spans(
            sweep_gazetteers(raw, icd_gaz, rx_gaz) + sweep_results(raw)
        )
        for ann in anns:
            ann.pop("_src", None)

        words = segment_document(raw, segment_line)
        spans = usable_spans(raw, anns, report)
        labels = label_words(words, spans, report)
        blocks += blocks_of(words, labels, 80)
        report["file"] += 1
        for ann in spans:
            types[ann["type"]] += 1
        print(f"  {path.name:8} {len(spans):3} spans")

    write_bio(blocks, OUT)
    tokens = sum(len(b) for b in blocks)
    tagged = sum(1 for b in blocks for _, lab in b if lab != "O")
    print(f"\n  {OUT.relative_to(REPO)}: {len(files)} file test -> "
          f"{len(blocks)} khối, {tokens} từ, {tagged} có nhãn ({tagged / max(tokens, 1):.1%})")
    print("  span theo type:")
    for name, count in types.most_common():
        print(f"    {name:22} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
