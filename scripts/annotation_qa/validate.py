#!/usr/bin/env python3
"""Validate gold annotation files. Usage: python3 validate.py [stem ...]  (no args = all)"""
import json, os, pickle, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

ROOT = REPO + "/data/generated_medical_records/restyled"
GOLD = os.path.join(ROOT, "annotations_gold")
K = pickle.load(open(os.path.join(HERE, "kb_index.pkl"), "rb"))

TYPES = {"TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"}
ASSERT_OK = {"isNegated", "isFamily", "isHistorical"}
CODABLE = {"CHẨN_ĐOÁN", "THUỐC"}
ASSERTABLE = {"CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG"}


def check(stem):
    errs, warns = [], []
    p = os.path.join(GOLD, stem + ".json")
    if not os.path.exists(p):
        return [f"{stem}: MISSING output file"], []
    txt = open(os.path.join(ROOT, "text", stem + ".txt"), encoding="utf-8").read()
    try:
        ents = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return [f"{stem}: JSON parse error: {e}"], []
    if not isinstance(ents, list):
        return [f"{stem}: top level is not a list"], []
    if not ents:
        errs.append(f"{stem}: empty annotation list")
    prev = -1
    for i, e in enumerate(ents):
        tag = f"{stem}[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{tag}: entity must be an object, got {type(e).__name__}")
            continue
        if set(e) != {"text", "type", "candidates", "assertions", "position"}:
            errs.append(f"{tag}: bad keys {sorted(e)}")
            continue
        if not isinstance(e["text"], str):
            errs.append(f"{tag}: text must be a string")
            continue
        candidates = e["candidates"]
        assertions = e["assertions"]
        if not isinstance(candidates, list) or not all(isinstance(c, str) for c in candidates):
            errs.append(f"{tag}: candidates must be a list of strings")
            candidates = []
        if not isinstance(assertions, list) or not all(isinstance(a, str) for a in assertions):
            errs.append(f"{tag}: assertions must be a list of strings")
            assertions = []
        s, t = e["position"] if isinstance(e["position"], list) and len(e["position"]) == 2 else (None, None)
        if not isinstance(s, int) or not isinstance(t, int):
            errs.append(f"{tag}: position must be [int,int], got {e['position']}"); continue
        if not (0 <= s < t <= len(txt)):
            errs.append(f"{tag}: position out of range {e['position']} (len={len(txt)})"); continue
        if txt[s:t] != e["text"]:
            errs.append(f"{tag}: OFFSET MISMATCH text={e['text']!r} vs raw={txt[s:t]!r}")
        entity_type = e["type"]
        if not isinstance(entity_type, str) or entity_type not in TYPES:
            errs.append(f"{tag}: bad type {e['type']!r}")
        bad_a = [a for a in assertions if a not in ASSERT_OK]
        if bad_a:
            errs.append(f"{tag}: bad assertions {bad_a}")
        if len(set(assertions)) != len(assertions):
            errs.append(f"{tag}: duplicate assertions {assertions}")
        if assertions and entity_type not in ASSERTABLE:
            errs.append(f"{tag}: assertions on non-assertable type {entity_type}")
        if len(set(candidates)) != len(candidates):
            errs.append(f"{tag}: duplicate candidates {candidates}")
        if candidates and entity_type not in CODABLE:
            errs.append(f"{tag}: candidates on non-codable type {entity_type}")
        if entity_type == "CHẨN_ĐOÁN" and len(candidates) > 1:
            errs.append(f"{tag}: diagnosis must have at most one candidate, got {candidates}")
        if entity_type == "CHẨN_ĐOÁN":
            for c in candidates:
                if c not in K["icd_code"]:
                    errs.append(f"{tag}: ICD {c!r} not in ICD10.csv")
        if entity_type == "THUỐC":
            for c in candidates:
                if not c.isdigit():
                    errs.append(f"{tag}: RxCUI {c!r} not numeric")
                elif c not in K["rx_cui"]:
                    errs.append(f"{tag}: RxCUI {c!r} has no active sab=RXNORM atom")
                else:
                    ttys = {ty for ty, _ in K["rx_cui"][c]}
                    if not ttys & {"IN", "PIN", "MIN"}:
                        warns.append(f"{tag}: RxCUI {c} tty={sorted(ttys)} not ingredient-level")
        if "*" in e["text"] and e["text"].strip("* ") == "":
            errs.append(f"{tag}: masked span {e['text']!r} must be dropped")
        if e["text"] != e["text"].strip():
            warns.append(f"{tag}: span has leading/trailing whitespace {e['text']!r}")
        if s < prev:
            warns.append(f"{tag}: not sorted by position (start {s} < previous {prev})")
        prev = s
    # duplicate spans
    seen = {}
    for i, e in enumerate(ents):
        if not isinstance(e, dict) or "position" not in e or "type" not in e or "text" not in e:
            continue
        position = e["position"]
        entity_type = e["type"]
        key = ((position[0], position[1]), entity_type) if (
            isinstance(position, list)
            and len(position) == 2
            and all(isinstance(value, int) for value in position)
            and isinstance(entity_type, str)
        ) else None
        if key and key in seen:
            errs.append(f"{stem}[{i}]: duplicate of [{seen[key]}] {e['text']!r}")
        seen[key] = i
    return errs, warns


if __name__ == "__main__":
    explicit = bool(sys.argv[1:])
    global_errs = []
    if explicit:
        stems = sys.argv[1:]
    else:
        text_stems = {f[:-4] for f in os.listdir(os.path.join(ROOT, "text")) if f.endswith(".txt")}
        source_stems = {f[:-5] for f in os.listdir(os.path.join(ROOT, "annotations")) if f.endswith(".json")}
        gold_stems = {f[:-5] for f in os.listdir(GOLD) if f.endswith(".json")}
        for label, missing in (
            ("source annotations missing for text", text_stems - source_stems),
            ("text missing for source annotations", source_stems - text_stems),
            ("gold annotations missing", source_stems - gold_stems),
            ("unexpected gold annotations", gold_stems - source_stems),
        ):
            if missing:
                global_errs.append(f"{label}: {', '.join(sorted(missing))}")
        stems = sorted(source_stems)
    stems = [s[:-5] if s.endswith(".json") else s for s in stems]
    E, W = len(global_errs), 0
    for x in global_errs:
        print("ERROR  " + x)
    for s in stems:
        errs, warns = check(s)
        E += len(errs); W += len(warns)
        for x in errs: print("ERROR  " + x)
        for x in warns: print("WARN   " + x)
    print(f"\n{len(stems)} file(s): {E} error(s), {W} warning(s)"
          + ("  ✅ CLEAN" if E == 0 and W == 0 else "  ❌ FIX ERRORS/WARNINGS"))
    sys.exit(1 if E or W else 0)
