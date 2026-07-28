#!/usr/bin/env python3
"""Chuyển dữ liệu sinh ra ở cây thư mục CŨ sang cây MỚI của gen_sample_data.py.

    data/synth/work/bundles.jsonl    -> .../synthetic/intermediate/entity_bundles.jsonl
    data/synth/work/composed.jsonl   -> .../synthetic/intermediate/composed_texts.jsonl
    data/synth/work/prompts.jsonl    -> .../synthetic/intermediate/prompts.jsonl
    data/train_input/cmpNNNN.txt     -> .../synthetic/text/synthetic_NNNN.txt
    data/synth/cmpNNNN.json          -> .../synthetic/annotations/synthetic_NNNN.json

Trường "id" bên trong hai file jsonl cũng được đổi theo (cmp0007 -> synthetic_0007),
nếu không thì emit chạy lại sẽ không khớp bundle với bản viết.

Mặc định CHÉP chứ không di chuyển: dữ liệu cũ còn nguyên để đối chiếu, chạy lại
được nhiều lần. Thêm --move khi đã kiểm xong và muốn dọn chỗ cũ.

    python scripts/migrate_to_new_structure.py --dry-run
    python scripts/migrate_to_new_structure.py
    python scripts/migrate_to_new_structure.py --move
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OLD_WORK = REPO / "data" / "synth" / "work"
OLD_LABELS = REPO / "data" / "synth"
OLD_TEXT = REPO / "data" / "train_input"

NEW_BASE = REPO / "data" / "generated_medical_records" / "synthetic"
NEW_WORK = NEW_BASE / "intermediate"
NEW_TEXT = NEW_BASE / "text"
NEW_ANNOTATIONS = NEW_BASE / "annotations"

#: Tên file trung gian đổi sang tên tự mô tả — "bundles"/"composed" không nói được
#: đó là bundle của cái gì khi thư mục có thêm lô dịch nằm cạnh.
WORK_RENAMES = {
    "bundles.jsonl": "entity_bundles.jsonl",
    "composed.jsonl": "composed_texts.jsonl",
    "prompts.jsonl": "prompts.jsonl",
}

ID_RE = re.compile(r"^cmp(\d+)$")


def new_id(old: str) -> str:
    """cmp0007 -> synthetic_0007; id lạ thì giữ nguyên."""
    m = ID_RE.match(old)
    return f"synthetic_{int(m.group(1)):04d}" if m else old


def move_or_copy(src: Path, dst: Path, move: bool, dry: bool) -> None:
    if dry:
        print(f"  {'mv' if move else 'cp'} {src.relative_to(REPO)} -> {dst.relative_to(REPO)}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(src, dst)


def migrate_jsonl(src: Path, dst: Path, move: bool, dry: bool) -> int:
    """Chép file jsonl và đổi trường id bên trong."""
    if dry:
        print(f"  {'mv' if move else 'cp'} {src.relative_to(REPO)} -> {dst.relative_to(REPO)}"
              f"  (đổi id bên trong)")
        return sum(1 for _ in src.open(encoding="utf-8"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with dst.open("w", encoding="utf-8") as fh:
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row.get("id"), str):
                row["id"] = new_id(row["id"])
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    if move:
        src.unlink()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--move", action="store_true",
                    help="di chuyển thay vì chép (mặc định chép, giữ nguyên chỗ cũ)")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in ra sẽ làm gì")
    args = ap.parse_args()

    if not OLD_LABELS.exists() and not OLD_TEXT.exists():
        print("không thấy cây thư mục cũ (data/synth, data/train_input) — không cần migrate")
        return 0

    print(f"chế độ: {'DI CHUYỂN' if args.move else 'CHÉP'}"
          f"{' (dry-run)' if args.dry_run else ''}\n")

    # 1. file trung gian
    n_work = 0
    if OLD_WORK.exists():
        print("file trung gian:")
        for old_name, new_name in WORK_RENAMES.items():
            src = OLD_WORK / old_name
            if not src.exists():
                continue
            n_work += migrate_jsonl(src, NEW_WORK / new_name, args.move, args.dry_run)
        if not n_work:
            print("  (không có)")

    # 2. nhãn
    labels = sorted(OLD_LABELS.glob("cmp*.json"))
    print(f"\nnhãn: {len(labels)} file")
    for src in labels:
        move_or_copy(src, NEW_ANNOTATIONS / f"{new_id(src.stem)}.json",
                     args.move, args.dry_run and len(labels) < 5)

    # 3. văn bản
    texts = sorted(OLD_TEXT.glob("cmp*.txt")) if OLD_TEXT.exists() else []
    print(f"văn bản: {len(texts)} file")
    for src in texts:
        move_or_copy(src, NEW_TEXT / f"{new_id(src.stem)}.txt",
                     args.move, args.dry_run and len(texts) < 5)

    if args.dry_run:
        print("\n(dry-run — chưa đụng vào file nào)")
        return 0

    # Kiểm lại: mỗi nhãn phải có văn bản đi kèm, nếu không thì verify sẽ báo lỗi.
    got_txt = {p.stem for p in NEW_TEXT.glob("*.txt")}
    orphan = [p.stem for p in NEW_ANNOTATIONS.glob("*.json") if p.stem not in got_txt]
    print(f"\nxong -> {NEW_BASE.relative_to(REPO)}")
    print(f"  intermediate: {n_work} dòng jsonl")
    print(f"  annotations:  {len(list(NEW_ANNOTATIONS.glob('*.json')))} file")
    print(f"  text:         {len(got_txt)} file")
    if orphan:
        print(f"  ⚠️  {len(orphan)} nhãn không có file văn bản: {orphan[:5]}")
    if not args.move:
        print("\n  dữ liệu cũ vẫn còn ở data/synth và data/train_input.")
        print("  kiểm bằng: python scripts/gen_sample_data.py verify")
        print("  ưng rồi thì chạy lại với --move, hoặc xoá tay hai thư mục cũ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
