#!/usr/bin/env python3
"""KB lookup helper for annotation QA.

Usage:
  python kb.py build                     # build indexes (once, ~1 min)
  python kb.py icd CODE [CODE ...]       # ICD-10 code -> Vietnamese label
  python kb.py icdfind "vietnamese text" # fuzzy search ICD-10 VN labels
  python kb.py icden CODE                # English ICD-10-CM descriptions for code/prefix
  python kb.py rx CUI [CUI ...]          # RxCUI -> tty + names
  python kb.py rxfind "drug name"        # search RxNorm names (IN/PIN/MIN/BN/SCD/SBD)
  python kb.py ing CUI                   # brand CUI -> ingredient CUI(s)
"""
import csv, json, os, pickle, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

csv.field_size_limit(10**9)
ROOT = REPO + "/data/knowledge_base"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_index.pkl")


def norm(s):
    s = unicodedata.normalize("NFC", s or "").lower().strip()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s))


def build():
    icd_code, icd_name = {}, {}
    with open(os.path.join(ROOT, "ICD10.csv"), encoding="utf-8-sig") as f:
        for r in csv.reader(f):
            if len(r) < 4 or not r[1] or not re.match(r"^[A-Z]\d", r[1].strip()):
                continue
            code, name, grp = r[1].strip(), r[2].strip(), r[3].strip()
            icd_code.setdefault(code, []).append(name)
            icd_name.setdefault(norm(name), set()).add(code)

    icd_en = {}
    p = os.path.join(ROOT, "icd10cm-code-descriptions-2027", "icd10cm-codes-2027.txt")
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            c, _, d = line.partition(" ")
            icd_en.setdefault(c.strip(), d.strip())

    rx_cui, rx_name = {}, {}
    keep = {"IN", "PIN", "MIN", "BN", "SCD", "SBD", "SCDC", "BPCK", "GPCK", "PSN", "SY"}
    with open(os.path.join(ROOT, "RXNORM.csv"), encoding="utf-8") as f:
        for x in csv.DictReader(f):
            if x["sab"] != "RXNORM" or x["tty"] not in keep or x["suppress"] not in ("", "N"):
                continue
            cui, tty, s = x["rxcui"], x["tty"], x["str"]
            rx_cui.setdefault(cui, []).append((tty, s))
            rx_name.setdefault(norm(s), set()).add((cui, tty))

    b2i = {}
    bp = os.path.join(ROOT, "brand_to_ingredient.json")
    if os.path.exists(bp):
        b2i = json.load(open(bp, encoding="utf-8"))

    idx = dict(icd_code=icd_code, icd_name={k: sorted(v) for k, v in icd_name.items()},
               icd_en=icd_en, rx_cui=rx_cui,
               rx_name={k: sorted(v) for k, v in rx_name.items()}, b2i=b2i)
    with open(CACHE, "wb") as f:
        pickle.dump(idx, f)
    print(f"built: icd {len(icd_code)} codes / {len(icd_name)} names; "
          f"icd_en {len(icd_en)}; rx {len(rx_cui)} cuis / {len(rx_name)} names; b2i {len(b2i)}")
    return idx


def load():
    if not os.path.exists(CACHE):
        return build()
    with open(CACHE, "rb") as f:
        return pickle.load(f)


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "build":
        build(); return
    K = load()

    if cmd == "icd":
        for c in args:
            c = c.strip().upper()
            hit = K["icd_code"].get(c)
            print(f"{c}: " + (" | ".join(dict.fromkeys(hit)) if hit else "*** NOT IN ICD10.csv ***"))
            if not hit:
                sub = [k for k in K["icd_code"] if k.startswith(c + ".")][:6]
                if sub:
                    print(f"   children present: {sub}")
    elif cmd == "icdfind":
        q = norm(" ".join(args))
        toks = [t for t in q.split() if len(t) > 1]
        scored = []
        for n, codes in K["icd_name"].items():
            if q and q in n:
                scored.append((100 + 20 / (1 + len(n)), n, codes)); continue
            hits = sum(1 for t in toks if t in n)
            if hits >= max(1, len(toks) - 1):
                scored.append((hits + 10 / (1 + len(n)), n, codes))
        scored.sort(reverse=True)
        for _, n, codes in scored[:20]:
            for c in codes:
                print(f"{c}\t{K['icd_code'][c][0]}")
    elif cmd == "icden":
        for c in args:
            c = c.strip().upper().replace(".", "")
            for k, v in K["icd_en"].items():
                if k.startswith(c):
                    print(f"{k}\t{v}")
    elif cmd == "rx":
        for c in args:
            c = c.strip()
            hit = K["rx_cui"].get(c)
            if not hit:
                print(f"{c}: *** NOT FOUND (sab=RXNORM, active) ***"); continue
            ttys = sorted({t for t, _ in hit})
            best = next((s for t, s in hit if t in ("IN", "PIN", "MIN", "BN", "SCD", "SBD")), hit[0][1])
            print(f"{c}\ttty={','.join(ttys)}\t{best}")
            ing = K["b2i"].get(c)
            if ing:
                print(f"   brand->ingredient: {ing}")
    elif cmd == "rxfind":
        q = norm(" ".join(args))
        order = {"IN": 0, "PIN": 1, "MIN": 2, "BN": 3, "SCD": 4, "SBD": 5}
        out = []
        for n, pairs in K["rx_name"].items():
            if n == q:
                sc = 0
            elif n.startswith(q + " ") or f" {q} " in f" {n} ":
                sc = 1
            elif q and q in n:
                sc = 2
            else:
                continue
            for cui, tty in pairs:
                out.append((sc, order.get(tty, 9), len(n), cui, tty, n))
        out.sort()
        seen = set()
        for sc, _, _, cui, tty, n in out:
            if (cui, tty) in seen:
                continue
            seen.add((cui, tty))
            names = K["rx_cui"][cui]
            disp = next((s for t, s in names if t == tty), n)
            print(f"{cui}\t{tty}\t{disp}")
            if len(seen) >= 25:
                break
    elif cmd == "ing":
        for c in args:
            print(f"{c} -> {K['b2i'].get(c.strip(), 'no brand->ingredient mapping')}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
