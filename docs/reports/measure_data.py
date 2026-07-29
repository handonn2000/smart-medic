#!/usr/bin/env python3
"""Reproduce every measured number quoted in docs/reports/research-directions.html.

Run from the repo root:

    python docs/reports/measure_data.py

Every figure in the report's "Đo đạc" sections comes from this script. Nothing is
estimated from the literature; if a number is not printed here, it is not ours.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import os
import random
import re
import statistics
import sys
import unicodedata

csv.field_size_limit(10 ** 7)
KB = "data/knowledge_base"
GEN = "data/generated_medical_records"


def h(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ─────────────────────────── 1. test-set profile ───────────────────────────
def test_set_profile() -> None:
    h("1 · TEST SET — 100 documents")
    files = sorted(glob.glob("data/test/*.txt"),
                   key=lambda p: int(os.path.basename(p)[:-4]))
    lens, feat = [], collections.Counter()
    nfc = shifted = combining = 0
    worst = []
    for f in files:
        s = open(f, encoding="utf-8").read()
        lens.append(len(s))
        n = unicodedata.normalize("NFC", s)
        if s == n:
            nfc += 1
        else:
            shifted += 1
            worst.append((os.path.basename(f), len(s), len(s) - len(n)))
        combining += sum(1 for ch in s if unicodedata.combining(ch))
        if re.search(r"^\s*[-•*+]\s|\n\s*\d+[.)]\s", s, re.M):
            feat["bullet / numbered list"] += 1
        if "?" in s:
            feat["question mark"] += 1
        if re.search(r"\*{3,}", s):
            feat["redacted ***** token"] += 1
        if re.search(r"\d+[,.]?\d*\s*(mg|ml|g|mmol|%|U/L|mg/dL|G/L|T/L)", s, re.I):
            feat["numeric value + unit"] += 1
        if re.search(r"(chào|bác sĩ|cảm ơn|ạ\b)", s, re.I):
            feat["conversational markers"] += 1
        if re.search(r"(tiền sử|tiền căn)", s, re.I):
            feat['history cue "tiền sử"'] += 1
        if re.search(r"\b(bố|mẹ|cha|anh trai|chị gái|gia đình|ông|bà)\b", s):
            feat["family word"] += 1
        if re.search(r"\bkhông\b", s):
            feat['negation "không"'] += 1
        lines = [l for l in s.split("\n") if l.strip()]
        if lines and sum(len(l) for l in lines) / len(lines) < 45:
            feat["short avg line (wrapped)"] += 1

    lens.sort()
    print(f"  n={len(files)}  chars: median {lens[len(lens)//2]}  "
          f"mean {sum(lens)//len(lens)}  max {lens[-1]}  total {sum(lens)}")
    print(f"\n  Unicode: NFC={nfc}  NOT-NFC={shifted}  combining marks={combining}")
    print("  → NFC normalisation would SHIFT offsets in these files:")
    for name, orig, delta in sorted(worst, key=lambda t: -t[2])[:8]:
        print(f"      {name:<10} len={orig:<6} loses {delta} chars")
    print("\n  Surface features:")
    for k, v in feat.most_common():
        print(f"      {k:<30} {v:>3}/100")

    runs = collections.Counter()
    for f in files:
        s = open(f, encoding="utf-8").read()
        for m in re.finditer(r"\*{2,}", s):
            runs[len(m.group(0))] += 1
    print(f"\n  Asterisk redaction runs: {sum(runs.values())} total, "
          f"lengths {min(runs)}–{max(runs)}")


# ───────────────────── 2. silver annotation statistics ─────────────────────
def silver_stats() -> None:
    h("2 · SILVER ANNOTATIONS")
    types = collections.Counter()
    asets = collections.Counter()
    ncand = collections.Counter()
    by_type_cand = collections.Counter()
    spanw = collections.defaultdict(list)
    ndoc = 0
    for f in glob.glob(f"{GEN}/*/annotations/*.json"):
        try:
            ents = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        ndoc += 1
        for e in ents:
            t = e.get("type")
            types[t] += 1
            spanw[t].append(len((e.get("text") or "").split()))
            if t in ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG"):
                asets[tuple(sorted(e.get("assertions") or []))] += 1
            if t in ("CHẨN_ĐOÁN", "THUỐC"):
                k = min(len(e.get("candidates") or []), 3)
                ncand[k] += 1
                by_type_cand[(t, k)] += 1

    print(f"  files={ndoc}  entities={sum(types.values())}")
    print("\n  type distribution:")
    tot = sum(types.values())
    for t, c in types.most_common():
        print(f"      {t:<22} {c:>6}  {c/tot:6.1%}   mean span "
              f"{statistics.mean(spanw[t]):.2f} words")

    ta = sum(asets.values())
    print(f"\n  assertion sets (n={ta} assertion-bearing entities):")
    for k, v in asets.most_common():
        print(f"      {str(k or '()'):<32} {v:>6}  {v/ta:6.1%}")

    tc = sum(ncand.values())
    print(f"\n  #codes per CHẨN_ĐOÁN/THUỐC entity (n={tc}):")
    for k in sorted(ncand):
        lbl = {0: "0 (empty)", 1: "1", 2: "2", 3: "≥3"}[k]
        print(f"      {lbl:<12} {ncand[k]:>6}  {ncand[k]/tc:6.1%}")
    nonempty = tc - ncand[0]
    print(f"      → P(gold empty)      = {ncand[0]/tc:.3f}")
    print(f"      → P(doublet | ≥1)    = {ncand[2]/nonempty:.4f}")
    pd = ncand[2] / nonempty
    print(f"      → gap threshold p1-p2 to justify a 2nd code: {pd/(1-pd):.4f}")
    for t in ("CHẨN_ĐOÁN", "THUỐC"):
        s = sum(by_type_cand[(t, k)] for k in range(4))
        print(f"      {t:<12} empty {by_type_cand[(t,0)]/s:5.1%} | "
              f"1 code {by_type_cand[(t,1)]/s:5.1%} | 2 codes {by_type_cand[(t,2)]/s:4.1%}")


# ──────────────── 3. document-level consistency of repeats ─────────────────
def consistency() -> None:
    h("3 · DOCUMENT-LEVEL CONSISTENCY OF REPEATED SURFACE FORMS")
    groups = 0
    bad = collections.Counter()
    repeated = 0
    for f in glob.glob(f"{GEN}/*/annotations/*.json"):
        try:
            ents = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        by_surface = collections.defaultdict(list)
        for e in ents:
            key = " ".join((e.get("text") or "").lower().split())
            by_surface[key].append(e)
        for key, es in by_surface.items():
            groups += 1
            if len(es) < 2:
                continue
            repeated += 1
            if len({e.get("type") for e in es}) > 1:
                bad["type"] += 1
            if len({tuple(sorted(e.get("candidates") or [])) for e in es}) > 1:
                bad["candidates"] += 1
            if len({tuple(sorted(e.get("assertions") or [])) for e in es}) > 1:
                bad["assertions"] += 1

    print(f"  (doc, surface-form) groups: {groups}   of which repeated: {repeated} "
          f"({repeated/groups:.1%})")
    print("\n  inconsistent groups among the repeated ones:")
    for field in ("candidates", "type", "assertions"):
        c = bad[field]
        verdict = "HARD-TIE OK" if c / groups < 0.01 else "DO NOT TIE"
        print(f"      {field:<12} {c:>4}  {c/groups:6.2%} of all groups   → {verdict}")


# ───────────────────── 4. knowledge-base profiling ────────────────────────
def kb_profile() -> None:
    h("4 · KNOWLEDGE BASES")
    rows = list(csv.reader(open(f"{KB}/ICD10.csv", encoding="utf-8-sig")))
    data = [r for r in rows[5:] if len(r) > 2 and r[1].strip()]
    codes = [r[1].strip() for r in data]
    name2codes = collections.defaultdict(set)
    for r in data:
        name2codes[r[2].strip().lower()].add(r[1].strip())
    amb = {k: v for k, v in name2codes.items() if len(v) > 1}
    par = {c for c in codes if "." not in c}
    kid = {c for c in codes if "." in c}
    nw = [len(n.split()) for n in name2codes]
    print(f"  ICD-10 rows with a code : {len(data)}")
    print(f"  unique codes            : {len(set(codes))}")
    print(f"  unique Vietnamese names : {len(name2codes)}  "
          f"(→ {len(data)/len(name2codes):.1f} rows per name)")
    print(f"  names → >1 distinct code: {len(amb)} ({len(amb)/len(name2codes):.1%})")
    print(f"  3-char categories       : {len(par)}   decimal codes: {len(kid)}")
    print(f"  categories with children: {len({c.split('.')[0] for c in kid} & par)}")
    print(f"  distinct 'Nhóm bệnh'    : {len({r[3].strip() for r in data if len(r)>3})}")
    print(f"  name length (words)     : mean {sum(nw)/len(nw):.1f}  max {max(nw)}")

    # VN↔EN parallel corpus via the ICD-10-CM description file
    cm = {}
    p = f"{KB}/icd10cm-code-descriptions-2027/icd10cm-codes-2027.txt"
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split(None, 1)
            if len(parts) == 2:
                cm[parts[0].strip().upper()] = parts[1].strip()
        vn = {c.replace(".", "").upper() for c in codes}
        pref = collections.defaultdict(list)
        for c in cm:
            pref[c[:3]].append(c)
        exact = vn & set(cm)
        hit3 = sum(1 for c in vn if c[:3] in pref)
        starts = sum(1 for c in vn if any(k.startswith(c) for k in pref.get(c[:3], [])))
        print(f"\n  VN↔EN parallel labels (join on code):")
        print(f"      exact code matches   : {len(exact)} ({len(exact)/len(vn):.1%} of VN codes)")
        print(f"      VN code prefixes a CM: {starts} ({starts/len(vn):.1%})")
        print(f"      3-char category in CM: {hit3} ({hit3/len(vn):.1%})")

    # RxNorm
    tty = collections.Counter()
    cui = set()
    ing_cui, ing_names, allnames = set(), set(), set()
    with open(f"{KB}/RXNORM.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tty[row["tty"]] += 1
            cui.add(row["rxcui"])
            allnames.add(row["str"].strip().lower())
            if row["tty"] in ("IN", "PIN", "MIN"):
                ing_cui.add(row["rxcui"])
                ing_names.add(row["str"].strip())
            if row["tty"] in ("IN", "PIN", "MIN", "BN", "SU"):
                pass
    print(f"\n  RxNorm rows             : {sum(tty.values())}")
    print(f"  unique RxCUI            : {len(cui)}")
    print(f"  unique normalized names : {len(allnames)}")
    print(f"  ingredient family CUIs  : {len(ing_cui)} "
          f"(→ {len(cui)/len(ing_cui):.0f}x smaller search space)")
    print(f"  ingredient family names : {len(ing_names)}")
    print(f"  top tty: {tty.most_common(8)}")

    # redaction length-constraint power
    bylen = collections.Counter(len(unicodedata.normalize("NFC", n)) for n in ing_names)
    obs = collections.Counter()
    for f in glob.glob("data/test/*.txt"):
        for m in re.finditer(r"\*{2,}", open(f, encoding="utf-8").read()):
            obs[len(m.group(0))] += 1
    if obs:
        tot_runs = sum(obs.values())
        tot_cand = sum(obs[L] * bylen.get(L, 0) for L in obs)
        avg = tot_cand / tot_runs
        print(f"\n  Redaction length constraint (assumes length-preserving masking):")
        print(f"      mean candidates per masked run: {avg:,.0f} of {len(ing_names):,} "
              f"→ {len(ing_names)/avg:.0f}x reduction")


# ───────────────── 5. metric decision theory (simulation) ─────────────────
def metric_sim() -> None:
    h("5 · METRIC DECISION THEORY")

    def J(g, p):
        g, p = set(g), set(p)
        if not (g | p):
            return 1.0
        return len(g & p) / len(g | p)

    def ev(probs, k, p_doublet=0.0):
        pred = set(range(k))
        e = p_doublet * J({0, 1}, pred)
        for i, pi in enumerate(probs):
            e += (1 - p_doublet) * pi * J({i}, pred)
        return e

    scen = {
        "confident   [.85 .08 .04 .02 .01]": [.85, .08, .04, .02, .01],
        "ambiguous   [.45 .35 .12 .05 .03]": [.45, .35, .12, .05, .03],
        "sibling-tie [.40 .38 .10 .07 .05]": [.40, .38, .10, .07, .05],
        "weak        [.25 .20 .18 .15 .12]": [.25, .20, .18, .15, .12],
    }
    print("  A · E[Jaccard] by k emitted codes (gold is a single code)")
    print("     " + "scenario".ljust(36) + "".join(f"k={k:<7}" for k in range(5)) + " argmax")
    for name, p in scen.items():
        row = [ev(p, k) for k in range(5)]
        print("     " + name.ljust(36) + "".join(f"{v:<9.3f}" for v in row)
              + f" k={max(range(5), key=lambda k: row[k])}")

    print("\n  B · closed-form rule check: emit 2nd code iff p_d/(1-p_d) > p1-p2")
    random.seed(1)
    bad = 0
    for _ in range(2000):
        p_d = random.choice([0.0, .05, .1, .2, .3, .45])
        raw = sorted((random.random() for _ in range(5)), reverse=True)
        s = sum(raw)
        p = [x / s for x in raw]
        vals = [ev(p, k, p_d) for k in range(4)]
        best = max(range(1, 4), key=lambda k: vals[k])
        rule = 2 if (p_d / (1 - p_d) if p_d < 1 else 9e9) > (p[0] - p[1]) else 1
        bad += (best != rule)
    print(f"     mismatches over 2000 random configs: {bad}")

    print("\n  C · break-even: P(gold has 2 codes) needed to justify a 2nd code")
    for gap in (.02, .05, .10, .20, .30, .50, .70):
        print(f"     gap p1-p2 = {gap:.2f}  →  need P(doublet) > {gap/(1+gap):.1%}")

    print("\n  D · WER cost of boundary errors (text_score = 1 - WER)")

    def wer(ref, hyp):
        r, hy = ref.split(), hyp.split()
        d = [[0] * (len(hy) + 1) for _ in range(len(r) + 1)]
        for i in range(len(r) + 1):
            d[i][0] = i
        for j in range(len(hy) + 1):
            d[0][j] = j
        for i in range(1, len(r) + 1):
            for j in range(1, len(hy) + 1):
                d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1,
                              d[i-1][j-1] + (r[i-1] != hy[j-1]))
        return d[-1][-1] / max(1, len(r))

    cases = [
        ("amlodipine 10 mg po daily", "amlodipine", "truncated to ingredient"),
        ("amlodipine 10 mg po daily", "amlodipine 10 mg", "truncated to strength"),
        ("ho đờm xanh", "ho", "head only"),
        ("ho đờm xanh", "ho đờm", "missing modifier"),
        ("bệnh trào ngược dạ dày – thực quản",
         "trào ngược dạ dày – thực quản", "dropped leading 'bệnh'"),
        ("sốt", "bệnh nhân có sốt cao", "OVER-generation on a 1-word gold"),
    ]
    for g, hy, note in cases:
        w = wer(g, hy)
        print(f"     WER={w:5.2f}  score={1-w:6.2f}   {note}")
    print("     → note the last row: 1-WER is UNBOUNDED BELOW. Clamp at 0.")

    print("\n  E · assertion strategies, Monte-Carlo on the measured silver distribution")
    sets = collections.Counter()
    for f in glob.glob(f"{GEN}/*/annotations/*.json"):
        try:
            ents = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for e in ents:
            if e.get("type") in ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG"):
                sets[tuple(sorted(e.get("assertions") or []))] += 1
    if not sets:
        return
    tot = sum(sets.values())
    empty = sum(v * J(set(k), set()) for k, v in sets.items()) / tot
    print(f"     always-empty                E[Jaccard] = {empty:.4f}")

    random.seed(0)
    keys, wts = list(sets), [sets[k] for k in sets]

    def sim(prec, rec, trials=120_000):
        acc = 0.0
        for _ in range(trials):
            g = set(random.choices(keys, weights=wts)[0])
            p = {x for x in g if random.random() < rec}
            if random.random() < (1 - prec) * 0.5:
                p.add(random.choice(["isNegated", "isFamily", "isHistorical"]))
            acc += J(g, p)
        return acc / trials

    for prec, rec in ((.95, .9), (.9, .8), (.85, .6), (.7, .9)):
        v = sim(prec, rec)
        print(f"     model P={prec} R={rec}          E[Jaccard] = {v:.4f}   "
              f"(final +{0.3*(v-empty):+.4f})")


if __name__ == "__main__":
    if not os.path.isdir("data"):
        sys.exit("run me from the repo root (data/ not found)")
    test_set_profile()
    silver_stats()
    consistency()
    kb_profile()
    metric_sim()
    print("\ndone.")
