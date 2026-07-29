#!/usr/bin/env python3
"""Resolve drug spans to SCD using the rule read off the PRD gold, with a
strength-preserving index. Validated against the 8 dose-bearing PRD gold spans
before being trusted on the corpus.
"""
import json, os, re, pickle, collections, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

GOLD = REPO + "/data/generated_medical_records/restyled/annotations_gold"
IX = pickle.load(open(os.path.join(HERE, "scd_index.pkl"), "rb"))
BY, NAME = IX["by_key"], IX["cui_name"]
KB = pickle.load(open(os.path.join(HERE, "kb_index.pkl"), "rb"))
B2I = KB["b2i"]

# strength: first number of a range wins ("325-650 mg" -> 325)
STRENGTH = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*-\s*\d+(?:[.,]\d+)?)?\s*"
                      r"(mg|mcg|µg|ug|g|ml|iu|unt|unit|%|meq)\b", re.I)
UNIT = {"µg": "MCG", "ug": "MCG", "unit": "UNT", "iu": "UNT"}
FORM_CUES = [
    (r"\b(viên nang|nang|capsule)\b", "oral capsule"),
    (r"\b(hỗn dịch|suspension)\b", "oral suspension"),
    (r"\b(dung dịch uống|siro|syrup|solution)\b", "oral solution"),
    (r"\b(tiêm|injection|tĩnh mạch|iv\b)", "injection"),
    (r"\b(xịt|hít|inhal)", "inhal"),
    (r"\b(nhỏ mắt|ophthalmic)", "ophthalmic"),
    (r"\b(bôi|kem|mỡ|cream|topical)", "topical"),
    (r"\b(er|xl|sr|phóng thích kéo dài|extended release)\b", "extended release"),
]
NOISE = re.compile(r"extended release|delayed release|chewable|disintegrating|"
                   r"effervescent|injection|suspension|solution|cream|ointment|"
                   r"patch|inhal|ophthalmic|topical|rectal|24 hr|12 hr|once daily")


def norm(s):
    s = unicodedata.normalize("NFC", s).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s./%-]", " ", s)).strip()


def resolve(span):
    n = norm(span).replace(",", ".")
    m = STRENGTH.search(n)
    if not m:
        return ("no-strength", None, None, 0)
    val, unit = m.group(1), m.group(2)
    u = UNIT.get(unit.lower(), unit.upper())
    v = val.rstrip("0").rstrip(".") if "." in val else val
    toks = [t for t in re.findall(r"[a-z]{4,}", n)]
    cands = []
    for t in toks:
        # prefix-4 bridges morphological variants (senna <-> sennosides)
        cands += BY.get((t[:5], v, u), []) or BY.get((t[:4] + t[4:5], v, u), [])
        if len(t) >= 5:
            for k, cs in BY.items():
                if k[1] == v and k[2] == u and k[0][:4] == t[:4]:
                    cands += cs
    if not cands:
        # gold falls back to the nearest real strength ("clonazepam 1.5 mg" -> 1 MG)
        try:
            target = float(v)
        except ValueError:
            return ("no-product", None, None, 0)
        near = []
        for t in toks:
            for k, cs in BY.items():
                if k[2] != u or k[0][:4] != t[:4]:
                    continue
                try:
                    d = abs(float(k[1]) - target)
                except ValueError:
                    continue
                if d <= target * 0.5:
                    near.append((d, cs))
        if not near:
            return ("no-product", None, None, 0)
        near.sort(key=lambda x: x[0])
        cands = [c for _, cs in near[:3] for c in cs]
    cands = sorted(set(cands))
    wanted = next((f for pat, f in FORM_CUES if re.search(pat, n)), None)

    def score(cui):
        tty, name = NAME[cui]
        low = name.lower()
        s = 0.0
        if wanted:
            s -= 12 if wanted in low else 0
        else:
            s -= 12 if re.search(r"\boral tablet\b", low) else 0
            s += 6 if NOISE.search(low) else 0
        s += 2 if tty == "SBD" else 0          # prefer generic unless span is a brand
        s += len(low) / 300.0
        return s

    cands.sort(key=score)
    best = cands[0]
    return (NAME[best][0], best, NAME[best][1], len(cands))


PRD = [("amlodipine 10 mg po daily", "308135"),
       ("aspirin 81 mg po daily", "243670"),
       ("metoprolol succinate xl 50 mg po daily", "866436"),
       ("guaifenesin ml po q6h:prn", None),
       ("nystatin oral suspension 5 ml po qid:prn", None),
       ("acetaminophen 325-650 mg po q6h:prn", "313782"),
       ("pravastatin 40 mg po daily", "904475"),
       ("docusate sodium 100 mg po bid", "1099278"),
       ("senna 8.6 mg po bid:prn", "312935"),
       ("clonazepam 0.5 mg po qam:prn", "197527"),
       ("clonazepam 1.5 mg po qhs", "197528")]

print("=== Đối chiếu với 11 span gold của PRD ===")
ok = tot = 0
for span, want in PRD:
    st, cui, lbl, fan = resolve(span)
    if want is None:
        print(f"  ~ {span:<40} gold=(IN/khác)  suy ra={cui} ({st})")
        continue
    tot += 1; ok += cui == want
    print(f"  {'✓' if cui == want else '✗'} {span:<40} gold={want:<9} "
          f"suy ra={cui} ({st}, {fan} ứng viên) {lbl or ''}")
print(f"  → khớp {ok}/{tot}\n")

rows = []
for f in sorted(os.listdir(GOLD)):
    if f.endswith(".json"):
        for e in json.load(open(os.path.join(GOLD, f), encoding="utf-8")):
            if e["type"] == "THUỐC":
                rows.append((f[:-5], e["text"], e["candidates"]))

stat = collections.Counter(); changes = []; unres = []
for stem, text, cands in rows:
    st, cui, lbl, fan = resolve(text)
    stat[st] += 1
    if st in ("SCD", "SCDC", "SBD"):
        changes.append({"stem": stem, "text": text, "old": cands,
                        "new": [cui], "tty": st, "label": lbl, "fanout": fan})
    elif st == "no-product":
        unres.append((stem, text))

t = len(rows)
print(f"=== {t} span THUỐC trong 100 file gold ===")
for k, v in stat.most_common():
    print(f"  {k:<12} {v:>4}  ({100*v/t:.1f}%)")
print(f"\nĐổi được IN → sản phẩm: {len(changes)} ({100*len(changes)/t:.1f}%)")
print(f"Có hàm lượng, không dựng được sản phẩm (giữ IN): {len(unres)}")
for s, x in unres[:15]:
    print(f"    [{s}] {x!r}")
json.dump(changes, open(os.path.join(HERE, "scd_changes.json"), "w"),
          ensure_ascii=False, indent=1)
print(f"\n→ {len(changes)} đề xuất ghi vào scd_changes.json")
