#!/usr/bin/env python3
"""Build a per-file review packet: text + current annotations with KB labels resolved
+ candidate suggestions, so reviewers spend tokens on judgement not lookup."""
import json, os, pickle, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

ROOT = REPO + "/data/generated_medical_records/restyled"
OUT = os.path.join(HERE, "packets")
K = pickle.load(open(os.path.join(HERE, "kb_index.pkl"), "rb"))


def norm(s):
    s = unicodedata.normalize("NFC", s or "").lower().strip()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s))


def icd_label(code):
    hit = K["icd_code"].get(code)
    return hit[0] if hit else "*** KHÔNG CÓ TRONG ICD10.csv ***"


def rx_label(cui):
    hit = K["rx_cui"].get(cui)
    if not hit:
        return "*** KHÔNG CÓ trong sab=RXNORM (code đáng ngờ) ***"
    ttys = ",".join(sorted({t for t, _ in hit}))
    best = next((s for t, s in hit if t in ("IN", "PIN", "MIN", "BN", "SCD", "SBD")), hit[0][1])
    extra = f"  [brand→ingredient: {K['b2i'][cui]}]" if cui in K["b2i"] else ""
    return f"{best} (tty={ttys}){extra}"


STOP = {"tien", "su", "benh", "nhan", "cua", "va", "do", "bi", "mac", "chan", "doan"}


def icd_suggest(phrase, k=8):
    q = norm(phrase)
    q = re.sub(r"^(tien su|chan doan|benh nhan)\s+", "", q).strip() or q
    toks = [t for t in q.split() if len(t) > 1]
    if not toks:
        return []
    core = [t for t in toks if t not in STOP] or toks
    scored = []
    for n, codes in K["icd_name"].items():
        if n == q:
            sc = 300
        elif n.startswith(q):
            sc = 200 + 20 / (1 + len(n))
        elif q and q in n:
            sc = 100 + 20 / (1 + len(n))
        else:
            hits = sum(1 for t in core if t in n)
            if hits < max(1, len(core) - 1):
                continue
            sc = hits + 10 / (1 + len(n))
        scored.append((sc, n, codes))
    scored.sort(reverse=True)
    out, seen = [], set()
    for _, n, codes in scored:
        for c in codes:
            if c in seen:
                continue
            seen.add(c)
            out.append((c, K["icd_code"][c][0]))
            if len(out) >= k:
                return out
    return out


def rx_suggest(phrase, k=6):
    q = norm(phrase)
    # strip dosage tail so "levothroid 0 1 mg dung hang ngay" still matches
    q = re.sub(r"\b\d+[\d.,/]*\s*(mg|mcg|g|ml|iu|unit|%)\b.*$", "", q).strip() or q
    order = {"IN": 0, "PIN": 1, "MIN": 2, "BN": 3, "SCD": 4, "SBD": 5}
    out = []
    for n, pairs in K["rx_name"].items():
        if n == q:
            sc = 0
        elif n.startswith(q + " ") or f" {q} " in f" {n} ":
            sc = 1
        elif q and len(q) > 3 and q in n:
            sc = 2
        else:
            continue
        for cui, tty in pairs:
            out.append((sc, order.get(tty, 9), len(n), cui, tty))
    out.sort()
    res, seen = [], set()
    for _, _, _, cui, tty in out:
        if cui in seen:
            continue
        seen.add(cui)
        names = K["rx_cui"][cui]
        disp = next((s for t, s in names if t == tty), names[0][1])
        ing = f"  [→ ingredient {K['b2i'][cui]}]" if cui in K["b2i"] else ""
        res.append((cui, tty, disp + ing))
        if len(res) >= k:
            break
    return res


def build(stem):
    txt = open(os.path.join(ROOT, "text", stem + ".txt"), encoding="utf-8").read()
    ents = json.load(open(os.path.join(ROOT, "annotations", stem + ".json"), encoding="utf-8"))
    L = [f"# {stem}", "", f"## VĂN BẢN (len={len(txt)} ký tự)", "```", txt, "```", "",
         "## NHÃN HIỆN TẠI (cần kiểm tra)", "",
         "| # | pos | type | text | candidates → nhãn KB | assertions |",
         "|---|-----|------|------|----------------------|------------|"]
    for i, e in enumerate(ents):
        s, t = e["position"]
        if e["type"] == "CHẨN_ĐOÁN":
            cs = "; ".join(f"`{c}` = {icd_label(c)}" for c in e["candidates"]) or "*(rỗng)*"
        elif e["type"] == "THUỐC":
            cs = "; ".join(f"`{c}` = {rx_label(c)}" for c in e["candidates"]) or "*(rỗng)*"
        else:
            cs = "; ".join(f"`{c}`" for c in e["candidates"]) or "—"
        txt_disp = e["text"].replace("|", "\\|").replace("\n", "⏎")
        L.append(f"| {i} | {s}-{t} | {e['type']} | {txt_disp} | {cs} | "
                 f"{', '.join(e['assertions']) or '—'} |")

    L += ["", "## GỢI Ý TRA CỨU KB (tự động, theo từ khoá — KHÔNG phải đáp án, phải tự thẩm định)"]
    seen = set()
    for e in ents:
        key = (e["type"], e["text"].lower())
        if e["type"] not in ("CHẨN_ĐOÁN", "THUỐC") or key in seen:
            continue
        seen.add(key)
        sug = icd_suggest(e["text"]) if e["type"] == "CHẨN_ĐOÁN" else rx_suggest(e["text"])
        L.append(f"\n**{e['type']} · “{e['text']}”**")
        if not sug:
            L.append("- (không có gợi ý lexical — tự tra bằng `kb.py icdfind` / `kb.py rxfind`)")
        for c, *rest in sug:
            L.append(f"- `{c}` — " + " · ".join(str(r) for r in rest))
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, stem + ".md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    stems = [s[:-5] if s.endswith(".json") else s for s in sys.argv[1:]]
    if not stems:
        stems = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, "annotations"))
                       if f.endswith(".json"))
    for s in stems:
        build(s)
    print(f"wrote {len(stems)} packets to {OUT}")
