#!/usr/bin/env python3
"""Đổi (văn bản + nhãn JSON) thành file BIO cho src/train.py.

    python scripts/prepare_training_data.py                    # gold restyled + batch2
    python scripts/prepare_training_data.py --holdout 24       # chừa 24 file để đo
    python src/train.py --data data/train_generated.txt --from-scratch -e 6
    python src/test.py -d data/holdout/text -o data/holdout/pred
    python scripts/evaluate.py --pred data/holdout/pred --gold data/holdout/gold \
                               --text-dir data/holdout/text

Đầu vào là đúng thứ gen_sample_data.py sinh ra: `<source>/text/X.txt` cùng
`<source>/annotations_gold/X.json` theo format nộp bài. Đầu ra là định dạng mà
src/dataset.py đọc — mỗi dòng một từ kèm nhãn BIO, khối cách nhau bằng dòng trống.

TÁCH TỪ DÙNG CHUNG VỚI LÚC SUY LUẬN: script này gọi cùng `segment_document` của
src/tokenization.py mà src/inference.py gọi, nên từ trong file huấn luyện và từ lúc dự
đoán được cắt y như nhau. Đây không phải chi tiết vụn: mô hình chỉ gán nhãn cho những
đơn vị nó từng thấy, tách từ hai đường khác nhau là dạy một thứ rồi hỏi một thứ khác.

NHÃN GẮN THEO ĐỘ CHỒNG LẤN: 96,1% span gold trùng khít ranh giới từ (đo trên 7.435 span
của bộ restyled). Với 3,9% còn lại thì một từ của segmenter nằm vắt qua biên hai span —
hay gặp nhất là tên xét nghiệm dính liền kết quả ("...nước tiểu dương tính"). BIO chỉ cho
mỗi từ một nhãn, nên từ đó về span chồng lấn nó nhiều nhất, và span nào không còn từ nào
thì bị bỏ. Không cắt từ ra để vừa span: lúc suy luận segmenter vẫn dính y như vậy, tạo
đích mà mô hình không bao giờ với tới được thì vô nghĩa.

CHUẨN HÓA NFC: 44/175 văn bản của bộ này ở dạng NFD (cố ý, để giống 20/100 file test).
Từ ghi ra đây luôn ở dạng NFC vì từ điển của PhoBERT là NFC — để nguyên NFD thì một phần
tư dữ liệu biến thành token lạ. Offset không có trong file BIO nên chuẩn hóa ở đây vô hại;
src/inference.py cũng chuẩn hóa NFC trước khi mã hóa, còn offset vẫn tính trên bản gốc.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
import unicodedata as ud
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from assertions import assertions_at  # noqa: E402
from labels import ENTITY_TYPE_MAP, LABELS, TYPE_TO_BIO  # noqa: E402
from tokenization import chunk_words, group_entities, segment_document  # noqa: E402

_GEN = REPO / "data" / "generated_medical_records"
DEFAULT_SOURCES = (
    _GEN / "restyled",
    _GEN / "batch2",
)
DEFAULT_OUT = REPO / "data" / "train_generated.txt"
DEFAULT_HOLDOUT_DIR = REPO / "data" / "holdout"

#: dataset.py cắt mỗi khối ở 256 subword. 80 từ tiếng Việt ~ 130–180 subword, còn dư chỗ
#: cho tên thuốc tiếng Anh bị BPE xé nhỏ, nên không khối nào bị cắt mất phần đuôi.
DEFAULT_MAX_WORDS = 80

SEED = 20260730


# ------------------------------------------------------------------ tách từ

def shown(path: Path) -> str:
    """Đường dẫn gọn để in, chạy từ thư mục nào cũng ra như nhau."""
    path = path.resolve()
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path)


def make_segmenter():
    """Trả về hàm tách từ cho một dòng, đúng hàm mà src/inference.py dùng."""
    try:
        from underthesea import word_tokenize
    except ImportError:
        sys.exit("cần underthesea (pip install -r requirements.txt) để tách từ "
                 "giống lúc suy luận")

    def segment_line(line: str) -> list[str]:
        # use_token_normalize sửa chính tả ("òa" -> "oà") làm token lệch khỏi văn bản gốc.
        try:
            return word_tokenize(line, use_token_normalize=False)
        except TypeError:
            return word_tokenize(line)

    return segment_line


# ------------------------------------------------------------------ đọc dữ liệu

def read_pairs(source: Path, ann_name: str, report: collections.Counter):
    """Ghép text/X.txt với <ann_name>/X.json, bỏ file thiếu một trong hai."""
    text_dir, ann_dir = source / "text", source / ann_name
    if not text_dir.is_dir():
        sys.exit(f"không có {text_dir}")
    if not ann_dir.is_dir():
        sys.exit(f"không có {ann_dir}")

    pairs = []
    for text_path in sorted(text_dir.glob("*.txt")):
        ann_path = ann_dir / f"{text_path.stem}.json"
        if not ann_path.is_file():
            report["file thiếu nhãn"] += 1
            continue
        raw = text_path.read_text(encoding="utf-8")
        anns = json.loads(ann_path.read_text(encoding="utf-8"))
        pairs.append((text_path.stem, raw, anns))
    return pairs


def usable_spans(raw: str, anns: list[dict], report: collections.Counter) -> list[dict]:
    """Bỏ span sai offset hoặc sai type — dạy sai còn tệ hơn không dạy."""
    out = []
    for ann in anns:
        start, end = ann["position"]
        if ud.normalize("NFC", raw[start:end]) != ud.normalize("NFC", ann["text"]):
            report["span lệch offset (bỏ)"] += 1
            continue
        if ann["type"] not in TYPE_TO_BIO:
            report["span sai type (bỏ)"] += 1
            continue
        out.append(ann)
    return out


# ------------------------------------------------------------- chừa file để đo

#: gen_sample_data.py đặt tên theo mẫu mtsamples_<khoa>_<số>_<kiểu trình bày>.
_STYLE = re.compile(r"_\d{3,}_(?P<style>.+)$")


def style_of(stem: str) -> str:
    found = _STYLE.search(stem)
    return found.group("style") if found else "khác"


def pick_holdout(stems: list[str], count: int, seed: int) -> set[str]:
    """Chọn file để chừa, chia theo kiểu trình bày chứ không bốc ngẫu nhiên thuần.

    Bốc thuần ngẫu nhiên 16 file trong 162 thì kiểu hiếm gần như chắc chắn vắng mặt:
    hoi_dap chỉ có 12 file trong bộ sinh, mà lại chiếm 42% bộ test. Bộ đo thiếu hẳn một
    kiểu vẫn cho ra một con số trung bình đẹp đẽ, chỗ yếu thì nằm ngoài tầm nhìn.
    """
    groups = collections.defaultdict(list)
    for stem in stems:
        groups[style_of(stem)].append(stem)

    order = sorted(groups, key=lambda name: (-len(groups[name]), name))
    quota = {name: min(len(groups[name]),
                       max(1, round(count * len(groups[name]) / len(stems))))
             for name in order}
    while sum(quota.values()) > count:
        quota[max(order, key=lambda name: (quota[name], len(groups[name])))] -= 1
    while sum(quota.values()) < count:
        room = [name for name in order if quota[name] < len(groups[name])]
        quota[max(room, key=lambda name: len(groups[name]) - quota[name])] += 1

    rng = random.Random(seed)
    held = set()
    for name in order:
        held.update(rng.sample(sorted(groups[name]), quota[name]))
    return held


def write_holdout(pairs, held: set[str], out_dir: Path):
    """Đổ file đã chừa ra text/ + gold/ để chấm được ngay, không phải gom tay.

    Xóa file thừa của lần chừa trước: đổi --holdout hay --seed rồi mà thư mục vẫn còn
    file cũ thì scripts/evaluate.py lặng lẽ chấm luôn cả những file vừa được đem đi
    huấn luyện, và điểm đo được sẽ cao một cách vô nghĩa.
    """
    text_dir, gold_dir = out_dir / "text", out_dir / "gold"
    for folder in (text_dir, gold_dir):
        folder.mkdir(parents=True, exist_ok=True)

    keep = {f"{stem}.txt" for stem in held} | {f"{stem}.json" for stem in held}
    stale = [path for folder, pattern in ((text_dir, "*.txt"), (gold_dir, "*.json"))
             for path in folder.glob(pattern) if path.name not in keep]
    for path in stale:
        path.unlink()

    for stem, raw, anns in pairs:
        if stem in held:
            # Ghi nguyên văn bản gốc, không chuẩn hóa: 44/175 file ở dạng NFD và offset
            # trong nhãn tính trên đúng dạng đó.
            (text_dir / f"{stem}.txt").write_text(raw, encoding="utf-8")
            (gold_dir / f"{stem}.json").write_text(
                json.dumps(anns, ensure_ascii=False, indent=2), encoding="utf-8")
    return text_dir, gold_dir, len(stale)


# ------------------------------------------------------------------ gắn nhãn

def label_words(words, anns, report: collections.Counter) -> list[str]:
    """Nhãn BIO cho từng từ; từ vắt qua hai span về span chồng lấn nó nhiều nhất."""
    owner: list[int | None] = []
    for _, word_start, word_end in words:
        best, best_overlap = None, 0
        for index, ann in enumerate(anns):
            start, end = ann["position"]
            overlap = min(word_end, end) - max(word_start, start)
            if overlap > best_overlap:
                best, best_overlap = index, overlap
        owner.append(best)

    claimed = collections.defaultdict(list)
    for word_index, ann_index in enumerate(owner):
        if ann_index is not None:
            claimed[ann_index].append(word_index)

    labels = ["O"] * len(words)
    for ann_index, ann in enumerate(anns):
        indices = claimed.get(ann_index)
        if not indices:
            report["span không còn từ nào (bỏ)"] += 1
            continue

        bio = TYPE_TO_BIO[ann["type"]]
        for n, word_index in enumerate(indices):
            labels[word_index] = ("B-" if n == 0 else "I-") + bio

        if indices != list(range(indices[0], indices[-1] + 1)):
            report["span bị ngắt giữa (nhãn vẫn ghi)"] += 1

        span = words[indices[0]][1], words[indices[-1]][2]
        if span != tuple(ann["position"]):
            report["span nới ra ranh giới từ"] += 1
            report["ký tự nới thêm"] += ((span[1] - span[0])
                                         - (ann["position"][1] - ann["position"][0]))

    return labels


def blocks_of(words, labels, max_words: int):
    """Cắt thành khối vừa 256 subword, không cắt ngang một khái niệm."""
    out = []
    for low, high in chunk_words(words, [1] * len(words), max_words):
        # chunk_words cắt ở dấu kết câu; nếu vẫn rơi vào giữa một span thì lùi về đầu span
        while low < high and labels[low].startswith("I-"):
            low += 1
        block = [(ud.normalize("NFC", surface), label)
                 for (surface, _, _), label in zip(words[low:high], labels[low:high])
                 if surface.strip()]
        if block:
            out.append(block)
    return out


# ------------------------------------------------------------------ ghi ra

def write_bio(blocks, out_path: Path) -> None:
    lines = []
    for block in blocks:
        for surface, label in block:
            # dataset.py đọc bằng rsplit(None, 1): từ được chứa khoảng trắng bên trong,
            # nhưng nhãn lạ thì lặng lẽ thành O, còn từ rỗng thì làm lệch cả khối.
            if label not in LABELS:
                sys.exit(f"nhãn {label!r} không có trong src/labels.py")
            if not surface.strip() or "\n" in surface:
                sys.exit(f"từ không ghi được thành một dòng: {surface!r}")
            lines.append(f"{surface} {label}")
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_bio(path: Path, report: collections.Counter):
    """Đọc lại một file BIO có sẵn để nối vào, hạ nhãn lạ xuống O.

    data/train.txt gán tay có những nhãn labels.py không khai (B-GIOI_TINH, B-PHAU_THUAT,
    B-LAB_VALUE…). dataset.py vẫn nhận file đó nhưng lặng lẽ đổi hết thành O; ở đây cũng
    đổi thành O, chỉ khác là có đếm và in ra, vì "biến mất không kèn trống" chính là cách
    một phần nhãn bị mất mà không ai hay.
    """
    blocks, block = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            if block:
                blocks.append(block)
                block = []
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            sys.exit(f"{shown(path)} dòng {number}: thiếu nhãn -> {line!r}")
        word, label = parts
        if label not in LABELS:
            report[f"--append: {label} -> O"] += 1
            label = "O"
        block.append((word, label))
    if block:
        blocks.append(block)
    return blocks


def write_audit(stem: str, raw: str, words, labels, out_dir: Path) -> None:
    """Ghi ra JSON mà một mô hình học thuộc lòng file BIO này sẽ dự đoán.

    Chấm thư mục này bằng scripts/evaluate.py là biết TRẦN của dữ liệu huấn luyện: cao
    nhất mô hình có thể tới nếu khớp hoàn hảo. Cột candidates không có nghĩa ở đây —
    normalizer không tham gia, nên chỉ đọc concept/WER và assertions.
    """
    out = []
    for bio, start, end in group_entities(words, labels):
        concept_type = ENTITY_TYPE_MAP.get(f"B-{bio}")
        if concept_type is None:
            continue
        out.append({
            "text": raw[start:end],
            "type": concept_type,
            "candidates": [],
            "assertions": assertions_at(raw, start, concept_type),
            "position": [start, end],
        })
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Nhãn JSON -> file BIO cho src/train.py.")
    parser.add_argument("--source", action="append", type=Path,
                        help="thư mục có text/ và annotations*/ (lặp được nhiều lần; "
                             "mặc định: restyled + batch2)")
    parser.add_argument("--annotations", default="annotations_gold",
                        help="tên thư mục nhãn trong mỗi --source "
                             "(mặc định: annotations_gold)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"file BIO ghi ra (mặc định: {DEFAULT_OUT.relative_to(REPO)})")
    parser.add_argument("--append", action="append", type=Path, default=[],
                        help="nối thêm một file BIO có sẵn, ví dụ data/train.txt")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS,
                        help=f"số từ tối đa mỗi khối (mặc định: {DEFAULT_MAX_WORDS})")
    parser.add_argument("--audit-out", type=Path,
                        help="ghi thêm nhãn BIO ra JSON format nộp bài để chấm trần của "
                             "dữ liệu bằng scripts/evaluate.py")
    parser.add_argument("--holdout", type=int, default=0,
                        help="chừa N file KHÔNG đưa vào huấn luyện, đổ ra "
                             "--holdout-dir để chấm bằng scripts/evaluate.py")
    parser.add_argument("--holdout-dir", type=Path, default=DEFAULT_HOLDOUT_DIR,
                        help=f"nơi đổ file đã chừa, gồm text/ và gold/ (mặc định: "
                             f"{DEFAULT_HOLDOUT_DIR.relative_to(REPO).as_posix()})")
    parser.add_argument("--seed", type=int, default=SEED,
                        help=f"hạt giống cho --holdout (mặc định: {SEED})")
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    sources = args.source or list(DEFAULT_SOURCES)
    report = collections.Counter()
    segment_line = make_segmenter()

    pairs = []
    for source in sources:
        found = read_pairs(source, args.annotations, report)
        print(f"  {shown(source)}/{args.annotations}: {len(found)} file")
        pairs += found
    if not pairs:
        sys.exit("không có cặp văn bản + nhãn nào")

    held = set()
    holdout_dirs = None
    if args.holdout:
        if args.holdout >= len(pairs):
            sys.exit(f"--holdout {args.holdout} >= {len(pairs)} file có nhãn")
        held = pick_holdout([stem for stem, _, _ in pairs], args.holdout, args.seed)
        text_dir, gold_dir, stale = write_holdout(pairs, held, args.holdout_dir)
        holdout_dirs = (text_dir, gold_dir)
        spread = collections.Counter(style_of(stem) for stem in held)
        print(f"  chừa {len(held)} file để đo -> {shown(text_dir)} + {shown(gold_dir)}"
              f"  [{', '.join(f'{k} {v}' for k, v in sorted(spread.items()))}]")
        if stale:
            print(f"    xóa {stale} file thừa của lần chừa trước")

    blocks, types = [], collections.Counter()
    for stem, raw, anns in pairs:
        if stem in held:
            continue
        words = segment_document(raw, segment_line)
        spans = usable_spans(raw, anns, report)
        labels = label_words(words, spans, report)
        blocks += blocks_of(words, labels, args.max_words)
        if args.audit_out:
            write_audit(stem, raw, words, labels, args.audit_out)
        report["file"] += 1
        report["từ"] += len(words)
        for ann in spans:
            types[ann["type"]] += 1

    for path in args.append:
        extra = read_bio(path, report)
        blocks += extra
        print(f"  nối thêm {shown(path)}: {len(extra)} khối, "
              f"{sum(len(b) for b in extra)} từ")

    write_bio(blocks, args.out)

    tokens = sum(len(block) for block in blocks)
    tagged = sum(1 for block in blocks for _, label in block if label != "O")
    print(f"\n  {shown(args.out)}: {len(blocks)} khối, {tokens} từ, "
          f"{tagged} từ có nhãn ({tagged / tokens:.1%})")
    print(f"  khối dài nhất: {max(len(b) for b in blocks)} từ "
          f"(dataset.py cắt ở 256 subword)")

    print("\n  span theo type:")
    for name, count in types.most_common():
        print(f"    {name:22} {count:5}  -> B-{TYPE_TO_BIO[name]}")

    if report:
        print("\n  ghi chú:")
        for key in sorted(report):
            if key not in ("file", "từ"):
                print(f"    {key:36} {report[key]}")

    print(f"\n  huấn luyện: python src/train.py --data {shown(args.out)} "
          f"--from-scratch -e 6")
    if holdout_dirs:
        text_dir, gold_dir = holdout_dirs
        pred_dir = args.holdout_dir / "pred"
        print(f"  rồi đo:     python src/test.py -d {shown(text_dir)} "
              f"-o {shown(pred_dir)}")
        print(f"              python scripts/evaluate.py --pred {shown(pred_dir)} "
              f"--gold {shown(gold_dir)} --text-dir {shown(text_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
