#!/usr/bin/env python3
"""Build a strength-preserving product index from RXNORM.csv (SCD/SCDC/SBD).

kb.py's normaliser destroys decimal strengths ("0.5 mg" -> "0 5 mg"), so drug
products cannot be matched by strength through it. This builds a separate index
keyed on (ingredient-token, strength-value, unit) with decimals intact.
"""
import csv, os, pickle, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

csv.field_size_limit(10**9)
ROOT = REPO + "/data/knowledge_base"
OUT = os.path.join(HERE, "scd_index.pkl")

STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(MG|MCG|G|ML|IU|UNT|%|MEQ)\b", re.I)
UNIT = {"IU": "UNT"}


def canon(v):
    v = v.rstrip("0").rstrip(".") if "." in v else v
    return v or "0"


def build():
    by_key = collections.defaultdict(list)
    cui_name = {}
    n = 0
    with open(os.path.join(ROOT, "RXNORM.csv"), encoding="utf-8") as f:
        for x in csv.DictReader(f):
            if x["sab"] != "RXNORM" or x["tty"] not in ("SCD", "SCDC", "SBD"):
                continue
            if x["suppress"] not in ("", "N"):
                continue
            s, cui, tty = x["str"], x["rxcui"], x["tty"]
            cui_name.setdefault(cui, (tty, s))
            ms = STRENGTH.findall(s)
            if not ms:
                continue
            n += 1
            low = s.lower()
            toks = set(re.findall(r"[a-z]{4,}", low))
            for val, unit in ms:
                u = UNIT.get(unit.upper(), unit.upper())
                v = canon(val)
                for t in toks:
                    by_key[(t[:5], v, u)].append(cui)
    by_key = {k: sorted(set(v)) for k, v in by_key.items()}
    pickle.dump({"by_key": by_key, "cui_name": cui_name}, open(OUT, "wb"))
    print(f"indexed {n} product strings, {len(by_key)} (tok,strength,unit) keys, "
          f"{len(cui_name)} cuis")


if __name__ == "__main__":
    build()
