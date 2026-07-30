#!/usr/bin/env python3
"""Dựng tập dev gán tay từ data/test — bọc dấu 〔 〕 rồi biên dịch ra nhãn JSON.

    python scripts/annotate.py skeleton --n 15     # bốc file để gán, tạo bản nháp
    python scripts/annotate.py status              # xem đã gán tới đâu
    python scripts/annotate.py compile             # nháp -> data/dev/gold/*.json
    python scripts/evaluate.py --pred data/output --gold data/dev/gold --text-dir data/test

VÌ SAO BỌC DẤU CHỨ KHÔNG GÕ OFFSET: gõ tay `position` là cách chắc chắn sai — mỗi lần
đếm lệch một ký tự là một span không ghép được với dự đoán, và theo luật của đề thì mất
điểm HAI lần. Bọc dấu thì offset do code tính đúng lúc bóc dấu, sai số bằng 0 theo cách
dựng. Đây cũng đúng cách gen_sample_data.py giữ offset cho dữ liệu sinh.

CÁCH GÁN — mở data/dev/marked/N.txt, bọc từng khái niệm, KHÔNG sửa gì khác trong văn bản:

    〔LOẠI|nguyên văn〕                     span không mã, không assertion
    〔LOẠI|nguyên văn|mã〕                  kèm mã chuẩn (chỉ CHẨN_ĐOÁN và THUỐC)
    〔LOẠI|nguyên văn|mã1,mã2|isNegated〕   nhiều mã, kèm assertion

Các vế sau `nguyên văn` không cần đúng thứ tự: vế nào là tên assertion thì tính là
assertion, còn lại tính là mã. LOẠI gõ tắt cho nhanh:

    DX  = CHẨN_ĐOÁN      SYM = TRIỆU_CHỨNG   DRUG = THUỐC
    TEST = TÊN_XÉT_NGHIỆM               RES = KẾT_QUẢ_XÉT_NGHIỆM

Assertion chỉ có ở CHẨN_ĐOÁN / THUỐC / TRIỆU_CHỨNG, tên đúng là `isNegated`,
`isFamily`, `isHistorical`. Mã chỉ có ở CHẨN_ĐOÁN (ICD-10) và THUỐC (RxNorm).

`compile` đối chiếu văn bản sau khi bóc dấu với data/test/N.txt và CHỈ ghi nhãn khi hai
bên giống nhau từng ký tự, nên mọi sửa chữa vô tình vào phần chữ đều bị chặn tại đây.
Cạm bẫy hay gặp nhất: 20/100 file test ở dạng Unicode NFD, editor lưu lại thành NFC là
đổi độ dài chuỗi và lệch toàn bộ offset — compile nhận ra và nói rõ trường hợp này.

KHÔNG mồi sẵn span bằng model: tập dev tồn tại để bắt lỗi của chính model, mồi sẵn thì
người gán chỉ xác nhận lại những gì model đã đoán và tập dev mất giá trị đó.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import re
import sys
import unicodedata as ud
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_DIR = REPO / "data" / "test"
DEV_DIR = REPO / "data" / "dev"
MARKED_DIR = DEV_DIR / "marked"
GOLD_DIR = DEV_DIR / "gold"
KB_DIR = REPO / "data" / "knowledge_base"

#: Bảng ICD-10 2020 của Bộ Y tế. Đổi ở đây thì src/normalizer.py và
#: scripts/gen_sample_data.py cũng phải đổi theo — ba script đọc bảng này riêng.
ICD10_NAME = "ICD10_VN.csv"
ICD10_CODE_COLUMNS = ("mã bệnh", "mã", "ma", "code")

SEED = 20260730

ENTITY_TYPES = ("CHẨN_ĐOÁN", "TRIỆU_CHỨNG", "THUỐC",
                "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM")
ASSERTION_TYPES = ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG")
CODEABLE_TYPES = ("CHẨN_ĐOÁN", "THUỐC")
ASSERTIONS = ("isNegated", "isFamily", "isHistorical")

#: Gõ tắt cho người gán. Giữ đúng bộ mã của gen_sample_data.py để hai đường (gán tay
#: và sinh tự động) dùng chung một quy ước dấu.
TYPE_ALIASES = {
    "DX": "CHẨN_ĐOÁN", "SYM": "TRIỆU_CHỨNG", "DRUG": "THUỐC",
    "TEST": "TÊN_XÉT_NGHIỆM", "RES": "KẾT_QUẢ_XÉT_NGHIỆM",
}

#: Dấu bọc. Cho phép tối đa 300 ký tự bên trong để chứa cả mã và assertion; không cho
#: lồng nhau (span lồng nhau không có trong gold, và bóc dấu lồng thì offset lệch).
MARK = re.compile(r"〔([^〔〕]{1,300})〕")

#: Tỉ lệ hai cái bẫy đo trên data/test: 30/100 file có tên thuốc bị che ***, 20/100 file
#: ở dạng NFD. Bốc ngẫu nhiên trơn thì lô 15 file dễ trượt sạch cả hai.
MASK_RATE, NFD_RATE = 0.30, 0.20


# --------------------------------------------------------------------- bốc file

def traits(raw: str) -> dict[str, bool]:
    return {"mask": "***" in raw, "nfd": raw != ud.normalize("NFC", raw)}


def by_number(path: Path) -> tuple[int, str]:
    """Thứ tự 1,2,…,10 chứ không 1,10,2 — tên file test là số."""
    return (int(path.stem) if path.stem.isdigit() else 0, path.stem)


def source_files() -> list[Path]:
    files = sorted(SRC_DIR.glob("*.txt"), key=by_number)
    if not files:
        sys.exit(f"không có file .txt nào trong {SRC_DIR.relative_to(REPO)}")
    return files


def choose(files: list[Path], n: int, seed: int) -> list[Path]:
    """Bốc n file, ưu tiên đủ hạn mức file có bẫy *** và file dạng NFD."""
    marks = {f: traits(f.read_text(encoding="utf-8")) for f in files}
    pool = list(files)
    random.Random(seed).shuffle(pool)

    picked: list[Path] = []
    for key, want in (("mask", round(MASK_RATE * n)), ("nfd", round(NFD_RATE * n))):
        for f in pool:
            if len(picked) >= n or sum(marks[p][key] for p in picked) >= want:
                break
            if f not in picked and marks[f][key]:
                picked.append(f)
    for f in pool:
        if len(picked) >= n:
            break
        if f not in picked:
            picked.append(f)

    picked.sort(key=by_number)
    return picked


def cmd_skeleton(args) -> int:
    files = choose(source_files(), args.n, args.seed)
    MARKED_DIR.mkdir(parents=True, exist_ok=True)

    written, kept = [], []
    for src in files:
        dest = MARKED_DIR / src.name
        if dest.exists():
            kept.append(dest.name)          # không bao giờ ghi đè công gán tay
            continue
        # Sao y từng byte: compile đối chiếu lại đúng chuỗi này, nên không thêm tiêu đề
        # hướng dẫn vào file, và không đổi dạng chuẩn hóa Unicode.
        dest.write_bytes(src.read_bytes())
        written.append(dest.name)

    print(f"\n  {len(written)} file nháp mới ở {MARKED_DIR.relative_to(REPO)}")
    if kept:
        print(f"  {len(kept)} file đã có, giữ nguyên: {', '.join(kept[:10])}"
              f"{' …' if len(kept) > 10 else ''}")
    print(f"\n  lô đã bốc: {', '.join(f.stem for f in files)}")
    marks = {f: traits(f.read_text(encoding="utf-8")) for f in files}
    print(f"    có bẫy ***: {sum(m['mask'] for m in marks.values())}/{len(files)}"
          f"   (data/test: 30/100)")
    print(f"    dạng NFD:   {sum(m['nfd'] for m in marks.values())}/{len(files)}"
          f"   (data/test: 20/100)")
    print(f"\n  Cách gán: bọc từng khái niệm trong 〔LOẠI|nguyên văn|mã|assertion〕,"
          f" KHÔNG sửa phần chữ.")
    print(f"  Gõ tắt: {'  '.join(f'{k}={v}' for k, v in TYPE_ALIASES.items())}")
    print(f"  Xong thì chạy: python scripts/annotate.py compile\n")
    return 0


# ------------------------------------------------------------------ bóc dấu

def parse_marked(marked: str) -> tuple[str, list[dict], list[str]]:
    """Bóc dấu 〔 〕 -> (văn bản sạch, span, lỗi). Offset tính ngay lúc bóc."""
    parts: list[str] = []
    records: list[dict] = []
    errors: list[str] = []
    pos = 0

    for m in MARK.finditer(marked):
        parts.append(marked[pos:m.start()])
        offset = sum(len(p) for p in parts)
        pos = m.end()

        fields = [f.strip() for f in m.group(1).split("|")]
        if len(fields) < 2 or not fields[1]:
            errors.append(f"dấu thiếu vế: 〔{m.group(1)[:40]}〕"
                          f" — cần 〔LOẠI|nguyên văn〕")
            parts.append(fields[-1] if fields else "")
            continue

        tag, surface, extras = fields[0], fields[1], [f for f in fields[2:] if f]
        parts.append(surface)

        ctype = TYPE_ALIASES.get(tag.upper(), tag if tag in ENTITY_TYPES else None)
        if ctype is None:
            errors.append(f"loại lạ {tag!r} ở 〔{m.group(1)[:40]}〕"
                          f" — dùng {'/'.join(TYPE_ALIASES)} hoặc tên đầy đủ")
            continue

        assertions, candidates = [], []
        for extra in extras:
            for item in (x.strip() for x in extra.split(",") if x.strip()):
                if item in ASSERTIONS:
                    assertions.append(item)
                elif item.startswith("is"):
                    errors.append(f"tên assertion sai {item!r} ở {surface!r}"
                                  f" — chỉ có {', '.join(ASSERTIONS)}")
                else:
                    candidates.append(item)

        if assertions and ctype not in ASSERTION_TYPES:
            errors.append(f"{ctype} không có assertion (ở {surface!r})")
            assertions = []
        if candidates and ctype not in CODEABLE_TYPES:
            errors.append(f"{ctype} không có mã chuẩn (ở {surface!r}) — gold để rỗng")
            candidates = []

        records.append({"text": surface, "type": ctype,
                        "candidates": sorted(set(candidates)),
                        "assertions": sorted(set(assertions)),
                        "position": [offset, offset + len(surface)]})

    parts.append(marked[pos:])
    return "".join(parts), records, errors


def diff_report(clean: str, original: str) -> str | None:
    """Nói rõ vì sao văn bản sau khi bóc dấu không còn khớp bản gốc."""
    if clean == original:
        return None
    if ud.normalize("NFC", clean) == ud.normalize("NFC", original):
        form = "NFD" if original != ud.normalize("NFC", original) else "NFC"
        return (f"editor đã đổi dạng chuẩn hóa Unicode — bản gốc là {form},"
                f" lưu lại đúng dạng đó (độ dài chuỗi đổi thì mọi offset lệch)")
    at = next((i for i, (a, b) in enumerate(zip(clean, original)) if a != b),
              min(len(clean), len(original)))
    return (f"phần chữ bị sửa ở khoảng ký tự {at}:"
            f" nháp {clean[max(0, at - 25):at + 25]!r}"
            f" vs gốc {original[max(0, at - 25):at + 25]!r}")


# ------------------------------------------------------------------- tra mã

def load_codes() -> tuple[set[str], set[str]]:
    """Mã ICD-10 và RxNorm để soát mã gõ sai. Trả về tập rỗng nếu thiếu bảng."""
    icd: set[str] = set()
    path = KB_DIR / ICD10_NAME
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        # Dò dòng header thay vì đếm dòng tiêu đề: ICD10_VN.csv có 2 dòng tiêu đề còn
        # ICD10.csv có 4. Tên cột khớp CHÍNH XÁC, vì bản VN có MÃ CHƯƠNG, MÃ NHÓM CHÍNH,
        # MÃ NHÓM PHỤ 1/2 và MÃ LOẠI đứng trước MÃ BỆNH.
        at = None
        for header_at, row in enumerate(rows):
            lowered = [cell.strip().lower() for cell in row]
            at = next((lowered.index(name) for name in ICD10_CODE_COLUMNS
                       if name in lowered), None)
            if at is not None:
                for data in rows[header_at + 1:]:
                    if len(data) > at and data[at].strip():
                        icd.add(data[at].strip())
                break
        if at is None:
            print(f"  [!] {path.name}: không thấy cột mã bệnh — bỏ qua bước soát mã ICD")

    rx: set[str] = set()
    path = KB_DIR / "RXNORM.csv"
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("rxcui") or "").strip()
                if code:
                    rx.add(code)
    return icd, rx


# ------------------------------------------------------------------ compile

def cmd_compile(args) -> int:
    marked_files = sorted(MARKED_DIR.glob("*.txt"), key=by_number)
    if not marked_files:
        sys.exit(f"chưa có file nháp nào trong {MARKED_DIR.relative_to(REPO)}"
                 f" — chạy skeleton trước")

    marked_text = {p: p.read_text(encoding="utf-8") for p in marked_files}
    todo = [p for p in marked_files if "〔" in marked_text[p]]
    blank = [p.stem for p in marked_files if p not in todo]

    # Tra bảng mã chỉ khi thật sự có gì để biên dịch: RXNORM.csv là 638k dòng, đọc
    # không cũng mất vài giây mỗi lần chạy.
    icd, rx = (set(), set()) if args.skip_code_check or not todo else load_codes()
    if icd or rx:
        print(f"\n  bảng mã: {len(icd)} ICD-10, {len(rx)} RxNorm")

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    by_type: collections.Counter = collections.Counter()
    n_written = n_span = n_code = n_assert = 0
    broken = []

    if todo:
        print(f"\n  {'file':10}{'span':>6}{'mã':>5}{'asrt':>6}   ghi chú")
    for path in todo:
        original = (SRC_DIR / path.name).read_text(encoding="utf-8")
        clean, records, errors = parse_marked(marked_text[path])
        mismatch = diff_report(clean, original)
        if mismatch:
            errors.insert(0, mismatch)

        for rec in records:
            if clean[rec["position"][0]:rec["position"][1]] != rec["text"]:
                errors.append(f"offset lệch ở {rec['text']!r}")
            if rec["type"] in CODEABLE_TYPES and not rec["candidates"]:
                errors.append(f"{rec['type']} chưa có mã: {rec['text']!r}"
                              f" (gold hầu như luôn có — để rỗng nếu thật sự không tra được)")
            for code in rec["candidates"]:
                if (icd or rx) and code not in icd and code not in rx:
                    errors.append(f"mã không tra được trong bảng BTC: {code}"
                                  f" (ở {rec['text']!r})")

        fatal = [e for e in errors if "chưa có mã" not in e and "không tra được" not in e]
        note = ""
        if fatal:
            broken.append(path.stem)
            note = "KHÔNG ghi nhãn"
        else:
            records.sort(key=lambda r: r["position"])
            (GOLD_DIR / f"{path.stem}.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            n_written += 1
            n_span += len(records)
            n_code += sum(bool(r["candidates"]) for r in records)
            n_assert += sum(bool(r["assertions"]) for r in records)
            by_type.update(r["type"] for r in records)

        print(f"  {path.stem:10}{len(records):>6}"
              f"{sum(bool(r['candidates']) for r in records):>5}"
              f"{sum(bool(r['assertions']) for r in records):>6}   {note}")
        for err in errors:
            print(f"      - {err}")

    print(f"\n  đã ghi {n_written} file nhãn -> {GOLD_DIR.relative_to(REPO)}")
    if n_written:
        print(f"  {n_span} span ({n_span / n_written:.1f}/file, gold trung vị 48)"
              f" · {100 * n_code / max(n_span, 1):.0f}% có mã"
              f" · {100 * n_assert / max(n_span, 1):.0f}% có assertion")
        print(f"  theo loại: {dict(by_type)}")
    if blank:
        print(f"  chưa gán ({len(blank)}): {', '.join(blank)}")
    if broken:
        print(f"  còn lỗi, chưa ghi ({len(broken)}): {', '.join(broken)}")
    print()
    return 1 if broken else 0


# -------------------------------------------------------------------- status

def cmd_status(args) -> int:
    marked = sorted(MARKED_DIR.glob("*.txt"), key=by_number) if MARKED_DIR.is_dir() else []
    gold = sorted(GOLD_DIR.glob("*.json"), key=by_number) if GOLD_DIR.is_dir() else []
    done = {p.stem for p in gold}

    print(f"\n  nháp:  {len(marked):3d} file  ({MARKED_DIR.relative_to(REPO)})")
    print(f"  nhãn:  {len(gold):3d} file  ({GOLD_DIR.relative_to(REPO)})\n")
    if not marked:
        print("  chưa có gì — chạy: python scripts/annotate.py skeleton --n 15\n")
        return 0

    for path in marked:
        raw = path.read_text(encoding="utf-8")
        n_mark = len(MARK.findall(raw))
        tag = "đã biên dịch" if path.stem in done else ("chưa biên dịch" if n_mark
                                                       else "chưa gán")
        print(f"  {path.stem:10}{n_mark:>4} dấu   {tag}")
    print()
    return 0


# ----------------------------------------------------------------------- CLI

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="Dựng tập dev gán tay từ data/test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("CÁCH GÁN")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("skeleton", help="bốc file từ data/test, tạo bản nháp để gán")
    s.add_argument("--n", type=int, default=15, help="số file cần gán (mặc định 15)")
    s.add_argument("--seed", type=int, default=SEED)

    c = sub.add_parser("compile", help="nháp có dấu 〔 〕 -> data/dev/gold/*.json")
    c.add_argument("--skip-code-check", action="store_true",
                   help=f"bỏ bước tra mã trong {ICD10_NAME} / RXNORM.csv")

    sub.add_parser("status", help="xem đã gán tới đâu")

    args = ap.parse_args()
    return {"skeleton": cmd_skeleton, "compile": cmd_compile,
            "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
