#!/usr/bin/env python3
"""
medical_name_checker.py

Nhập một chuỗi -> kiểm tra:
  * có phải TÊN THUỐC theo RxNorm không  (trả RxCUI)
  * có phải TÊN BỆNH theo ICD-10 không   (trả mã ICD)

Cách chạy:
  python medical_name_checker.py                      # chế độ REPL (gõ liên tục)
  python medical_name_checker.py -q "amlodipine 10 mg po daily"
  python medical_name_checker.py --rxnorm RXNORM.csv --icd ICD10_VN.csv

Khớp theo 2 mức:
  1) exact (chuẩn hoá): match tuyệt đối sau khi hạ chữ thường + gộp khoảng trắng
     (với thuốc còn thử thêm bản đã bỏ route/tần suất: 'po','bid','q6h:prn'...).
  2) fuzzy: nếu không exact -> trả top ứng viên gần nhất kèm điểm, để bạn thấy nó
     "suýt" là gì. `match=True` khi exact, hoặc fuzzy >= ngưỡng (mặc định 90).

Phụ thuộc: pip install pandas rapidfuzz
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict

from rapidfuzz import process, fuzz

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


# --------------------------------------------------------------------------
# Nạp dữ liệu
# --------------------------------------------------------------------------
class Vocab:
    """Giữ: exact dict (folded -> mã), danh sách tên, và token-index để block fuzzy."""
    def __init__(self):
        self.exact = defaultdict(list)     # folded_name -> [code, ...]
        self.names = []                    # (folded_name, display_name, code)
        self.token_index = defaultdict(list)
        self._seen = set()                 # (folded_name, code) đã thêm

    def add(self, name: str, code: str):
        if not name or not code:
            return
        fn = fold(name)
        if not fn or (fn, code) in self._seen:
            return
        self._seen.add((fn, code))
        self.exact[fn].append(code)
        self.names.append((fn, name, code))

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


# --------------------------------------------------------------------------
# In kết quả
# --------------------------------------------------------------------------
def report(query: str, rx: Vocab, icd: Vocab, cutoff: int):
    d = rx.lookup(query, extra_forms=[strip_dose_admin(query)], cutoff=cutoff)
    s = icd.lookup(query, cutoff=cutoff)
    print(f'\n>>> "{query}"')
    _line("THUỐC (RxNorm)", d, "RxCUI")
    _line("BỆNH  (ICD-10)", s, "ICD")


def _line(label, res, code_label):
    if res["match"]:
        top = res["candidates"][0]
        tag = "✓ khớp" if res["method"] == "exact" else f"~ gần khớp ({top['score']})"
        print(f"  {label}: {tag}  [{code_label} {top['code']}] {top['name']}")
    else:
        print(f"  {label}: ✗ không phải")
        for c in res["candidates"][:3]:
            print(f"        · gần: [{code_label} {c['code']}] {c['name']} ({c['score']})")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rxnorm", default="data/knowledge_base/RXNORM.csv")
    ap.add_argument("--icd", default="data/knowledge_base/ICD10_VN.csv")
    ap.add_argument("-q", "--query", default=None)
    ap.add_argument("--cutoff", type=int, default=90,
                    help="ngưỡng điểm fuzzy để coi là 'khớp' (0-100)")
    args = ap.parse_args()

    print("Đang nạp RxNorm...", file=sys.stderr)
    rx = load_rxnorm(args.rxnorm)
    print(f"  {len(rx.names):,} tên thuốc.", file=sys.stderr)
    print("Đang nạp ICD-10...", file=sys.stderr)
    icd = load_icd(args.icd)
    print(f"  {len(icd.names):,} tên bệnh.", file=sys.stderr)

    if args.query is not None:
        report(args.query, rx, icd, args.cutoff)
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
            report(q, rx, icd, args.cutoff)


if __name__ == "__main__":
    main()