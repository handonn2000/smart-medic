#!/usr/bin/env python3
"""Post-pass over annotations_gold/: enforce corpus-wide decisions the per-batch
reviewers could not see, and report residual inconsistencies.

Run with --apply to write changes; default is dry-run.

Decisions enforced (see gold-annotation-handoff.md for rationale):
  D1  Lifestyle/social-history is not a diagnosis -> drop Z72.x smoking/alcohol/drug spans.
  D2  Generic drug-class mentions are not THUỐC -> drop.
  D3  Generic test words ("xét nghiệm", "kiểm tra") are not TÊN_XÉT_NGHIỆM -> drop.
  D4  ICD10.csv Vietnamese label is the authority: exact-label disagreements are
      reported for manual adjudication and are never auto-applied.
"""
import json, os, re, sys, pickle, unicodedata, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

ROOT = REPO + "/data/generated_medical_records/restyled"
GOLD = os.path.join(ROOT, "annotations_gold")
K = pickle.load(open(os.path.join(HERE, "kb_index.pkl"), "rb"))
APPLY = "--apply" in sys.argv


def norm(s):
    s = unicodedata.normalize("NFC", s).lower().strip()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


LIFESTYLE = re.compile(
    r"^(tái phát )?(thói quen )?(hút (thuốc|tẩu|thuốc lá)|sử dụng (ma túy|thuốc lá|rượu)"
    r"|uống rượu|rượu xã giao|hút)( .{0,20})?$", re.I)

DRUG_CLASS = {
    "thuốc lợi tiểu", "lợi tiểu", "kháng sinh", "kháng sinh iv", "kháng sinh tĩnh mạch",
    "thuốc chống đông", "thuốc chống nấm", "thuốc kháng sinh", "thuốc giảm đau",
    "thuốc hạ áp", "thuốc huyết áp", "thuốc nhỏ mắt", "thuốc ngủ", "thuốc bổ",
    "thuốc chống viêm", "thuốc an thần", "thuốc tim mạch", "thuốc tiểu đường",
    "dịch truyền", "thuốc", "các thuốc", "thuốc điều trị",
}

GENERIC_TEST = {
    "xét nghiệm", "các xét nghiệm", "kiểm tra", "chỉ số", "kết quả",
    "thăm khám", "khám", "chẩn đoán hình ảnh", "cận lâm sàng",
}


def main():
    stems = sorted(f[:-5] for f in os.listdir(GOLD) if f.endswith(".json"))
    dropped = collections.Counter()
    drop_ex = collections.defaultdict(list)
    label_pref = []
    z72_review = []
    for s in stems:
        p = os.path.join(GOLD, s + ".json")
        ents = json.load(open(p, encoding="utf-8"))
        out = []
        for e in ents:
            t, ty = e["text"], e["type"]
            n = norm(t)
            if ty == "CHẨN_ĐOÁN" and LIFESTYLE.match(t.strip()):
                dropped["D1 lifestyle"] += 1; drop_ex["D1 lifestyle"].append((s, t, e["candidates"])); continue
            if ty == "CHẨN_ĐOÁN" and any(c.startswith("Z72") for c in e["candidates"]):
                # A true dependence disorder can be miscoded as Z72.x. Report unknown
                # lexical forms instead of deleting them without reading the context.
                z72_review.append((s, t, e["candidates"]))
            if ty == "THUỐC" and n in DRUG_CLASS:
                dropped["D2 drug-class"] += 1; drop_ex["D2 drug-class"].append((s, t, e["candidates"])); continue
            if ty == "TÊN_XÉT_NGHIỆM" and n in GENERIC_TEST:
                dropped["D3 generic-test"] += 1; drop_ex["D3 generic-test"].append((s, t, [])); continue
            if ty == "CHẨN_ĐOÁN":
                exact = K["icd_name"].get(n)
                if exact and e["candidates"] and not (set(exact) & set(e["candidates"])):
                    label_pref.append((s, t, e["candidates"], exact))
            out.append(e)
        if APPLY and len(out) != len(ents):
            out.sort(key=lambda e: (e["position"][0], e["position"][1]))
            with open(p, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
                f.write("\n")

    print(f"{'APPLIED' if APPLY else 'DRY RUN'} over {len(stems)} files\n")
    print("=== Auto-drops ===")
    for k, v in dropped.most_common():
        print(f"  {k:<18} {v}")
        for s, t, c in drop_ex[k][:6]:
            print(f"      [{s}] {t!r} {c}")
    print(f"\n=== D1 manual review: Z72.x không khớp mẫu lối sống ({len(z72_review)}) ===")
    for s, t, c in z72_review[:40]:
        print(f"  [{s}] {t!r} {c}")
    print(f"\n=== D4: span text khớp CHÍNH XÁC nhãn ICD10.csv nhưng dùng mã khác ({len(label_pref)}) ===")
    for s, t, cur, exact in label_pref[:40]:
        print(f"  [{s}] “{t}”  hiện={cur}  nhãn-khớp={exact} → {K['icd_code'][exact[0]][0]}")


if __name__ == "__main__":
    main()
