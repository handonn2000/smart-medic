#!/usr/bin/env python3
"""Cross-file consistency audit of annotations_gold/.

Same surface form should get the same type and the same code across the corpus.
Reports disagreements ranked by how often the phrase occurs.
"""
import json, os, sys, collections, unicodedata, re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

ROOT = REPO + "/data/generated_medical_records/restyled"
GOLD = os.path.join(ROOT, "annotations_gold")


def norm(s):
    s = unicodedata.normalize("NFC", s).lower().strip()
    return re.sub(r"\s+", " ", s)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 25
    types = collections.defaultdict(collections.Counter)
    codes = collections.defaultdict(collections.Counter)
    assertions = collections.defaultdict(collections.Counter)
    where = collections.defaultdict(set)
    for f in sorted(os.listdir(GOLD)):
        if not f.endswith(".json"):
            continue
        for e in json.load(open(os.path.join(GOLD, f), encoding="utf-8")):
            k = norm(e["text"])
            types[k][e["type"]] += 1
            where[k].add(f[:-5])
            if e["type"] in ("CHẨN_ĐOÁN", "THUỐC"):
                codes[(k, e["type"])][tuple(sorted(e["candidates"]))] += 1
            if e["type"] in ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG"):
                assertions[(k, e["type"])][tuple(sorted(e["assertions"]))] += 1

    tconf = [(sum(c.values()), k, c) for k, c in types.items() if len(c) > 1]
    tconf.sort(reverse=True)
    print(f"=== TYPE không nhất quán: {len(tconf)} cụm ===")
    for n, k, c in tconf[:limit]:
        print(f"  {n:>3}x  “{k}”  →  {dict(c)}   (vd: {sorted(where[k])[:2]})")

    cconf = [(sum(c.values()), k, c) for k, c in codes.items() if len(c) > 1]
    cconf.sort(reverse=True)
    print(f"\n=== CANDIDATES không nhất quán: {len(cconf)} cụm ===")
    for n, (k, t), c in cconf[:limit]:
        opts = {(", ".join(v) or "∅"): n2 for v, n2 in c.items()}
        print(f"  {n:>3}x  [{t}] “{k}”  →  {opts}")

    # phrases coded in some files but left empty in others
    print(f"\n=== Bỏ trống candidates dù nơi khác có mã ===")
    shown = 0
    for (k, t), c in sorted(codes.items(), key=lambda kv: -sum(kv[1].values())):
        if len(c) < 2 or () not in c:
            continue
        nonempty = {v: n for v, n in c.items() if v}
        if not nonempty:
            continue
        print(f"  “{k}” [{t}]: rỗng {c[()]}x  vs  " +
              ", ".join(f"{', '.join(v)} {n}x" for v, n in nonempty.items()))
        shown += 1
        if shown >= limit:
            break

    aconf = [(sum(c.values()), k, c) for k, c in assertions.items() if len(c) > 1]
    aconf.sort(reverse=True)
    print(f"\n=== ASSERTIONS không nhất quán: {len(aconf)} cụm ===")
    for n, (k, t), c in aconf[:limit]:
        opts = {(", ".join(v) or "∅"): n2 for v, n2 in c.items()}
        print(f"  {n:>3}x  [{t}] “{k}”  →  {opts}")


if __name__ == "__main__":
    main()
