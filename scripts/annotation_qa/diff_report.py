#!/usr/bin/env python3
"""Compare annotations/ vs annotations_gold/ and report what changed."""
import json, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

ROOT = REPO + "/data/generated_medical_records/restyled"
OLD, NEW = os.path.join(ROOT, "annotations"), os.path.join(ROOT, "annotations_gold")


def load(d, stem):
    p = os.path.join(d, stem + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def key(e):
    return (e["position"][0], e["position"][1])


def main():
    stems = sorted(f[:-5] for f in os.listdir(NEW) if f.endswith(".json"))
    ops = collections.Counter()
    tot_old = tot_new = 0
    type_new = collections.Counter()
    examples = collections.defaultdict(list)
    per_file = []
    for s in stems:
        o, n = load(OLD, s), load(NEW, s)
        if o is None or n is None:
            continue
        tot_old += len(o); tot_new += len(n)
        for e in n:
            type_new[e["type"]] += 1
        om = {key(e): e for e in o}
        nm = {key(e): e for e in n}
        # exact-span matches
        kept = mod = 0
        for k in om.keys() & nm.keys():
            a, b = om[k], nm[k]
            ch = []
            if a["type"] != b["type"]:
                ch.append("type"); ops["sửa type"] += 1
            if sorted(a["candidates"]) != sorted(b["candidates"]):
                ch.append("code"); ops["sửa code"] += 1
            if sorted(a["assertions"]) != sorted(b["assertions"]):
                ch.append("assertion"); ops["sửa assertion"] += 1
            if ch:
                mod += 1
                examples["+".join(ch)].append((s, a, b))
            else:
                kept += 1; ops["giữ nguyên"] += 1
        # spans only in old / only in new — try to pair by overlap (= span boundary edit)
        only_o = [om[k] for k in om.keys() - nm.keys()]
        only_n = [nm[k] for k in nm.keys() - om.keys()]
        paired_n = set()
        for a in only_o:
            best = None
            for i, b in enumerate(only_n):
                if i in paired_n:
                    continue
                s1, e1 = a["position"]; s2, e2 = b["position"]
                ov = min(e1, e2) - max(s1, s2)
                if ov > 0 and (best is None or ov > best[0]):
                    best = (ov, i, b)
            if best:
                paired_n.add(best[1]); ops["sửa span"] += 1
                examples["span"].append((s, a, best[2]))
            else:
                ops["xoá"] += 1
                examples["xoá"].append((s, a, None))
        for i, b in enumerate(only_n):
            if i not in paired_n:
                ops["thêm"] += 1
                examples["thêm"].append((s, None, b))
        per_file.append((s, len(o), len(n)))

    print(f"Files: {len(per_file)}   entities {tot_old} → {tot_new} "
          f"({tot_new - tot_old:+d}, {100*(tot_new-tot_old)/max(tot_old,1):+.1f}%)")
    print("\nThao tác:")
    for k, v in ops.most_common():
        print(f"  {k:<16} {v}")
    print("\nPhân bố type (gold):")
    for k, v in type_new.most_common():
        print(f"  {k:<22} {v}")
    if "--examples" in sys.argv:
        for cat in ["type", "code", "assertion", "span", "xoá", "thêm"]:
            rows = [x for k, v in examples.items() if cat in k for x in v]
            if not rows:
                continue
            print(f"\n### {cat} ({len(rows)}) — 12 mẫu")
            for s, a, b in rows[:12]:
                if a is None:
                    print(f"  + [{s}] {b['text']!r} {b['type']} {b['candidates']} {b['assertions']}")
                elif b is None:
                    print(f"  - [{s}] {a['text']!r} {a['type']} {a['candidates']} {a['assertions']}")
                else:
                    print(f"  ~ [{s}] {a['text']!r} {a['type']} {a['candidates']} {a['assertions']}")
                    print(f"    →      {b['text']!r} {b['type']} {b['candidates']} {b['assertions']}")
    if "--perfile" in sys.argv:
        print("\nPer-file:")
        for s, a, b in per_file:
            print(f"  {s:<40} {a:>3} → {b:>3}  ({b-a:+d})")


if __name__ == "__main__":
    main()
