#!/usr/bin/env python3
"""
medical_name_checker.py

Nhập một chuỗi -> kiểm tra:
  * có phải TÊN THUỐC theo RxNorm không  (trả RxCUI)
  * có phải TÊN BỆNH theo ICD-10 không   (trả mã ICD)

Hoặc với --code: nhập mã (RxCUI / ICD) -> trả tên thực thể.

Cách chạy:
  python medical_name_checker.py                      # REPL, kiểm cả thuốc + bệnh
  python medical_name_checker.py -q "amlodipine"
  python medical_name_checker.py --rxnorm -q "amlodipine"   # chỉ thuốc
  python medical_name_checker.py --icd -q "viêm phổi"       # chỉ bệnh
  python medical_name_checker.py --code --rxnorm -q 17767   # RxCUI -> tên thuốc
  python medical_name_checker.py --code --icd -q J18.9      # ICD -> tên bệnh
  python medical_name_checker.py --linker sapbert --icd -q "viêm phổi"
  python medical_name_checker.py --rxnorm-path RXNORM.csv --icd-path ICD10_VN.csv

Khớp theo 2 mức (chế độ tên, RapidFuzz):
  1) exact (chuẩn hoá): match tuyệt đối sau khi hạ chữ thường + gộp khoảng trắng
     (với thuốc còn thử thêm bản đã bỏ route/tần suất: 'po','bid','q6h:prn'...).
  2) fuzzy: nếu không exact -> trả top ứng viên gần nhất kèm điểm.
     `match=True` khi exact, hoặc fuzzy >= ngưỡng (mặc định 90 RapidFuzz / 50 SapBERT).

Phụ thuộc: pip install pandas rapidfuzz
         (+ transformers torch cho --linker sapbert)
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from rapidfuzz import process, fuzz

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RXNORM = _ROOT / "data" / "knowledge_base" / "RXNORM.csv"
_DEFAULT_ICD = _ROOT / "data" / "knowledge_base" / "ICD10_VN.csv"
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --------------------------------------------------------------------------
# Chuẩn hoá
# --------------------------------------------------------------------------
_ROUTE = {"po", "iv", "im", "sc", "sq", "sl", "pr", "top", "inh", "ng",
          "pv", "id", "neb", "ophth", "otic", "nasal", "buccal", "rectal"}
_FREQ = {"daily", "bid", "tid", "qid", "qd", "qod", "qhs", "qam", "qpm",
         "prn", "once", "weekly", "monthly", "hs", "ac", "pc", "stat"}
_FREQ_RE = re.compile(r"^q\d+h$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").lower().strip()
    return re.sub(r"\s+", " ", s)


def fold(s: str) -> str:
    """Bỏ dấu tiếng Việt để khớp khoan dung (người gõ hay thiếu dấu)."""
    s = unicodedata.normalize("NFD", norm(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def strip_dose_admin(text: str) -> str:
    """Bỏ đường dùng / tần suất, giữ 'ingredient strength form' cho khớp RxNorm."""
    out = []
    for tok in norm(text).split():
        tok = tok.split(":")[0]
        if not tok or tok in _ROUTE or tok in _FREQ or _FREQ_RE.match(tok):
            continue
        out.append(tok)
    return " ".join(out).strip()


def norm_code(code: str) -> str:
    """Chuẩn hoá mã để tra ngược: bỏ khoảng trắng, chấm, chữ hoa."""
    return re.sub(r"[\s.]", "", (code or "").strip()).upper()


# --------------------------------------------------------------------------
# Nạp dữ liệu
# --------------------------------------------------------------------------
class Vocab:
    """Giữ: exact dict (folded -> mã), danh sách tên, token-index, và code -> names."""
    def __init__(self):
        self.exact = defaultdict(list)     # folded_name -> [code, ...]
        self.names = []                    # (folded_name, display_name, code)
        self.token_index = defaultdict(list)
        self.by_code = defaultdict(list)   # norm_code -> [display_name, ...]
        self._seen = set()                 # (folded_name, code) đã thêm
        self._seen_code_name = set()       # (norm_code, display_name)

    def add(self, name: str, code: str):
        if not name or not code:
            return
        fn = fold(name)
        code = str(code).strip()
        if not fn or (fn, code) in self._seen:
            return
        self._seen.add((fn, code))
        self.exact[fn].append(code)
        self.names.append((fn, name, code))
        ck = norm_code(code)
        if ck and (ck, name) not in self._seen_code_name:
            self._seen_code_name.add((ck, name))
            self.by_code[ck].append(name)

    def build_index(self):
        for i, (fn, _, _) in enumerate(self.names):
            for tok in set(fn.split()):
                self.token_index[tok].append(i)

    def lookup(self, query: str, extra_forms=None, limit=5, cutoff=90):
        forms = [query] + list(extra_forms or [])
        # 1) exact trên các biến thể chuẩn hoá
        for f in forms:
            key = fold(f)
            if key and key in self.exact:
                return {"match": True, "method": "exact", "score": 100.0,
                        "code": self.exact[key][0],
                        "matched": key,
                        "candidates": [{"code": self.exact[key][0], "name": key, "score": 100.0}]}
        # 2) fuzzy có blocking theo token
        q = fold(next((f for f in forms if fold(f)), query))
        cand_ids = set()
        for tok in set(q.split()):
            cand_ids.update(self.token_index.get(tok, ()))
        if not cand_ids:
            return {"match": False, "method": "fuzzy", "candidates": []}
        choices = {i: self.names[i][0] for i in cand_ids}
        res = process.extract(q, choices, scorer=fuzz.token_sort_ratio, limit=limit)
        cands = [{"code": self.names[k][2], "name": self.names[k][1], "score": round(sc, 1)}
                 for (_, sc, k) in res]
        best = cands[0]["score"] if cands else 0
        return {"match": best >= cutoff, "method": "fuzzy", "candidates": cands}

    def lookup_code(self, code: str):
        """Tra ngược: mã -> danh sách tên. Exact theo mã đã chuẩn hoá."""
        key = norm_code(code)
        names = self.by_code.get(key, [])
        if names:
            return {"match": True, "method": "exact", "code": code.strip(),
                    "names": names,
                    "candidates": [{"code": code.strip(), "name": n, "score": 100.0}
                                   for n in names]}
        return {"match": False, "method": "exact", "code": code.strip(),
                "names": [], "candidates": []}


def load_rxnorm(path: str) -> Vocab:
    v = Vocab()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v.add(row.get("str", ""), row.get("rxcui", ""))
    v.build_index()
    return v


def load_icd(path: str) -> Vocab:
    import pandas as pd
    # 2 dòng đầu là tiêu đề rác; dòng thứ 3 (index 2) mới là header thật
    df = pd.read_csv(path, skiprows=2, dtype=str, keep_default_na=False)
    v = Vocab()
    for _, r in df.iterrows():
        leaf = r.get("MÃ BỆNH", "").strip()
        if leaf:                                  # mã lá + tên VI/EN
            v.add(r.get("TÊN BỆNH", ""), leaf)
            v.add(r.get("DISEASE NAME", ""), leaf)
        cat = r.get("MÃ LOẠI", "").strip()        # cấp loại (mã 3 ký tự)
        if cat:
            v.add(r.get("TÊN LOẠI", ""), cat)
            v.add(r.get("TYPE NAME", ""), cat)
    v.build_index()
    return v


def load_icd_linker(path: str, backend: str, device: str = "cpu"):
    """SapBERT / RapidFuzz ICD linker sharing inference's factory."""
    try:
        from src.entity_linker import build_icd_linker
        from src.normalizer import read_icd10
    except ImportError:
        from entity_linker import build_icd_linker
        from normalizer import read_icd10
    alias_rows = [{"code": c, "name": n} for c, n in read_icd10(Path(path))]
    return build_icd_linker(alias_rows, backend=backend, device=device)


def lookup_via_linker(linker, query: str, cutoff: float, limit: int = 5):
    """Adapt linker.suggest_for_text -> Vocab.lookup-shaped dict (scores 0-100)."""
    sugs = linker.suggest_for_text(query, k=limit)
    if not sugs:
        return {"match": False, "method": "dense", "candidates": []}
    cands = [{"code": c, "name": n, "score": round(s, 1)} for c, n, s in sugs]
    best = cands[0]["score"]
    method = "exact" if best >= 99.9 else "dense"
    return {"match": best >= cutoff, "method": method, "candidates": cands}


# --------------------------------------------------------------------------
# In kết quả
# --------------------------------------------------------------------------
def report(query: str, rx, icd, cutoff: int, by_code: bool = False, icd_linker=None):
    print(f'\n>>> "{query}"')
    if by_code:
        if rx is not None:
            _line_code("THUỐC (RxNorm)", rx.lookup_code(query), "RxCUI")
        if icd is not None:
            _line_code("BỆNH  (ICD-10)", icd.lookup_code(query), "ICD")
        return
    if rx is not None:
        d = rx.lookup(query, extra_forms=[strip_dose_admin(query)], cutoff=cutoff)
        _line("THUỐC (RxNorm)", d, "RxCUI")
    if icd_linker is not None:
        s = lookup_via_linker(icd_linker, query, cutoff=cutoff)
        _line("BỆNH  (ICD-10)", s, "ICD", show_score=True)
    elif icd is not None:
        s = icd.lookup(query, cutoff=cutoff)
        _line("BỆNH  (ICD-10)", s, "ICD", show_score=True)


def _line(label, res, code_label, show_score=False):
    if res["match"]:
        top = res["candidates"][0]
        if show_score:
            tag = "✓ khớp" if res["method"] == "exact" else "~ gần khớp"
            print(f"  {label}: {tag}  [{code_label} {top['code']}] {top['name']} ({top['score']})")
        else:
            tag = "✓ khớp" if res["method"] == "exact" else f"~ gần khớp ({top['score']})"
            print(f"  {label}: {tag}  [{code_label} {top['code']}] {top['name']}")
    else:
        print(f"  {label}: ✗ không phải")
        for c in res["candidates"][:3]:
            print(f"        · gần: [{code_label} {c['code']}] {c['name']} ({c['score']})")


def _line_code(label, res, code_label):
    if res["match"]:
        names = res["names"]
        print(f"  {label}: ✓ tìm thấy  [{code_label} {res['code']}]")
        for n in names[:10]:
            print(f"        · {n}")
        if len(names) > 10:
            print(f"        … và {len(names) - 10} tên khác")
    else:
        print(f"  {label}: ✗ không có mã [{code_label} {res['code']}]")


# --------------------------------------------------------------------------
def _ensure_utf8_stdio():
    """Tránh UnicodeEncodeError trên Windows console (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main():
    _ensure_utf8_stdio()
    ap = argparse.ArgumentParser(
        description="Kiểm tra tên thuốc (RxNorm) / tên bệnh (ICD-10), "
                    "hoặc tra ngược mã -> tên với --code.")
    ap.add_argument("--rxnorm", action="store_true",
                    help="chỉ kiểm tra thuốc (RxNorm). Bỏ cả --rxnorm và --icd = kiểm cả hai")
    ap.add_argument("--icd", action="store_true",
                    help="chỉ kiểm tra bệnh (ICD-10). Bỏ cả --rxnorm và --icd = kiểm cả hai")
    ap.add_argument("--code", action="store_true",
                    help="query là mã (RxCUI / ICD), trả về tên thực thể thay vì tra tên -> mã")
    ap.add_argument("--linker", choices=["rapidfuzz", "sapbert"], default="rapidfuzz",
                    help="cách khớp TÊN BỆNH (ICD): rapidfuzz (mặc định) hoặc sapbert; "
                         "không ảnh hưởng --code / RxNorm")
    ap.add_argument("--rxnorm-path", default=str(_DEFAULT_RXNORM),
                    help="đường dẫn RXNORM.csv")
    ap.add_argument("--icd-path", default=str(_DEFAULT_ICD),
                    help="đường dẫn ICD10_VN.csv")
    ap.add_argument("-q", "--query", default=None)
    ap.add_argument("--cutoff", type=int, default=None,
                    help="ngưỡng điểm để coi là 'khớp' (0-100); "
                         "mặc định 90 (rapidfuzz) hoặc 50 (sapbert); bỏ qua khi --code")
    args = ap.parse_args()

    if args.cutoff is None:
        args.cutoff = 50 if args.linker == "sapbert" else 90

    # --rxnorm / --icd chọn phạm vi; bỏ cả hai (hoặc bật cả hai) = kiểm cả hai
    if args.rxnorm or args.icd:
        check_rx = bool(args.rxnorm)
        check_icd = bool(args.icd)
    else:
        check_rx = check_icd = True

    rx = icd = icd_linker = None
    if check_rx:
        print("Đang nạp RxNorm...", file=sys.stderr)
        rx = load_rxnorm(args.rxnorm_path)
        print(f"  {len(rx.names):,} tên thuốc / {len(rx.by_code):,} RxCUI.", file=sys.stderr)
    if check_icd:
        print("Đang nạp ICD-10...", file=sys.stderr)
        icd = load_icd(args.icd_path)
        print(f"  {len(icd.names):,} tên bệnh / {len(icd.by_code):,} mã ICD.", file=sys.stderr)
        # SapBERT (and shared RapidFuzz linker) only needed for name -> code.
        if not args.code and args.linker == "sapbert":
            print("Đang nạp SapBERT ICD linker...", file=sys.stderr)
            icd_linker = load_icd_linker(args.icd_path, backend="sapbert")
        elif not args.code and args.linker == "rapidfuzz":
            # Keep Vocab path (token-blocked fuzzy) — same as before.
            icd_linker = None

    mode = "mã -> tên" if args.code else "tên -> mã"
    scopes = []
    if check_rx:
        scopes.append("RxNorm")
    if check_icd:
        scopes.append(f"ICD-10/{args.linker}")
    print(f"Chế độ: {mode} | phạm vi: {', '.join(scopes)}", file=sys.stderr)

    if args.query is not None:
        report(args.query, rx, icd, args.cutoff, by_code=args.code, icd_linker=icd_linker)
        return
    print('Gõ chuỗi để kiểm tra (Ctrl-D hoặc "quit" để thoát):', file=sys.stderr)
    while True:
        try:
            q = input("\nchuỗi> ").strip()
        except EOFError:
            break
        if q.lower() in {"quit", "exit"}:
            break
        if q:
            report(q, rx, icd, args.cutoff, by_code=args.code, icd_linker=icd_linker)


if __name__ == "__main__":
    main()
