#!/usr/bin/env python3
"""
validate_annotations.py — soát lỗi annotation do LLM sinh ra, TRƯỚC khi train.

Chạy:
  python validate_annotations.py --txt a.txt --json a.json
  python validate_annotations.py --dir data/ --report soat.csv

Mức độ:
  ERROR = gần như chắc chắn sai, phải sửa
  WARN  = đáng ngờ, cần mắt người
  INFO  = thống kê để phát hiện quy ước không nhất quán

MỚI so với bản trước:
  * In LINE NUMBER trong file .json cho từng concept (dễ mở editor nhảy tới sửa).
  * Tra NGƯỢC từ text ra mã (name -> code) để ĐỐI CHIẾU CHÉO với mã đang gán:
    check C2_SUGGEST đề xuất mã mà từ điển cho là khớp nhất với chính chuỗi text,
    kèm tty (SCD/SBD/BN/IN...) để bạn thấy mã hiện tại có sai BẬC hay không.

Các lớp lỗi nhắm tới (pipeline "dịch bằng LLM + annotate bằng LLM"):
  A. Offset lệch          B. Mã không tồn tại
  C. Mã tồn tại nhưng trỏ sai khái niệm   C2. Đề xuất mã từ text
  D. Type <-> candidates  E. Nhãn assertion không thống nhất
  F. Bỏ sót mention       G. Mâu thuẫn type/mã giữa các file
  H. Thiếu assertion dù có cue            I. Span chồng lấn

Phụ thuộc: pip install pandas rapidfuzz
         (+ transformers torch cho --linker sapbert)
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for _p in (_ROOT, _SRC):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# ---------------------------------------------------------------- quy ước
TYPES_WITH_CANDIDATES = {"CHẨN_ĐOÁN", "THUỐC"}
TYPES_NO_CANDIDATES = {"TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM"}
NEG_CUES = ["không", "chưa", "ko", "phủ nhận", "loại trừ", "âm tính"]
HIST_CUES = ["tiền sử", "trước đây", "đã từng"]
CUE_WINDOW = 30

# Ưu tiên bậc RxNorm khi đề xuất: mention càng chi tiết thì bậc càng cao.
TTY_RANK = {"SCD": 0, "SBD": 1, "GPCK": 2, "BPCK": 3, "BN": 4, "PIN": 5, "IN": 6}


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").lower().strip())


def fold(s):
    s = unicodedata.normalize("NFD", norm(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    # bỏ dấu câu: "mô kẽ, không phân loại" -> token "ke" khớp được với "ke"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


_ROUTE = {"po", "iv", "im", "sc", "sq", "sl", "pr", "top", "inh", "ng", "pv",
          "id", "neb", "ophth", "otic", "nasal", "buccal", "rectal"}
_FREQ = {"daily", "bid", "tid", "qid", "qd", "qod", "qhs", "qam", "qpm", "prn",
         "once", "weekly", "monthly", "hs", "ac", "pc", "stat"}
_FREQ_RE = re.compile(r"^q\d+h$")


def strip_dose_admin(text):
    out = []
    for tok in norm(text).split():
        tok = tok.split(":")[0]
        if not tok or tok in _ROUTE or tok in _FREQ or _FREQ_RE.match(tok):
            continue
        out.append(tok)
    return " ".join(out).strip()


# ------------------------------------------------- số dòng trong file JSON
def json_line_map(path):
    """Trả list line-number (1-based) ứng với từng phần tử của mảng JSON gốc.
    Quét thủ công theo độ sâu ngoặc, bỏ qua ngoặc nằm trong chuỗi."""
    raw = open(path, encoding="utf-8").read()
    lines, depth, in_str, esc, line = [], 0, False, False, 1
    for ch in raw:
        if ch == "\n":
            line += 1
            continue
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if ch == "{" and depth == 2:      # phần tử của mảng top-level
                lines.append(line)
        elif ch in "]}":
            depth -= 1
    return lines


# ---------------------------------------------------------------- từ điển
class NameIndex:
    """Tra NGƯỢC: từ chuỗi tên -> mã. Dùng cho check C2_SUGGEST."""

    def __init__(self):
        self.exact = defaultdict(list)     # folded -> [(code, tty)]
        self.entries = []                  # (folded, display, code, tty)
        self.token_index = defaultdict(list)
        self._seen = set()

    def add(self, name, code, tty=""):
        if not name or not code:
            return
        fn = fold(name)
        if not fn or (fn, code) in self._seen:
            return
        self._seen.add((fn, code))
        self.exact[fn].append((code, tty))
        self.entries.append((fn, name, code, tty))

    def build(self):
        for i, (fn, _, _, _) in enumerate(self.entries):
            for tok in set(fn.split()):
                self.token_index[tok].append(i)

    def suggest(self, query, extra_forms=(), limit=3):
        """Trả [(code, name, tty, score)] — ưu tiên exact, rồi fuzzy."""
        for f in [query, *extra_forms]:
            key = fold(f)
            if key and key in self.exact:
                hits = sorted(self.exact[key],
                              key=lambda ct: TTY_RANK.get(ct[1], 99))
                return [(c, key, t, 100.0) for c, t in hits[:limit]]
        q = fold(next((f for f in [query, *extra_forms] if fold(f)), query))
        ids = set()
        for tok in set(q.split()):
            ids.update(self.token_index.get(tok, ()))
        if not ids:
            return []
        choices = {i: self.entries[i][0] for i in ids}
        # token_set_ratio: chịu được tên từ điển DÀI HƠN mention
        # ("bệnh mô kẽ" vs "Bệnh phổi mô kẽ, không phân loại").
        # token_sort_ratio phạt nặng chênh lệch độ dài -> đẩy mã sai lên trên.
        res = process.extract(q, choices, scorer=fuzz.token_set_ratio,
                              limit=max(limit * 8, 40))
        # Nhiều tên cùng đạt 100 (vì chứa trọn mention) -> tie-break bằng fuzz.ratio
        # để tên NGẮN/sát độ dài mention nổi lên, thay vì mã đặc hiệu ngẫu nhiên.
        res = sorted(res, key=lambda r: (-r[1], -fuzz.ratio(q, r[0])))[:limit]
        return [(self.entries[k][2], self.entries[k][1], self.entries[k][3], round(sc, 1))
                for (_, sc, k) in res]


def load_icd(path):
    import pandas as pd
    df = pd.read_csv(path, skiprows=2, dtype=str, keep_default_na=False)
    code2names = defaultdict(set)
    idx = NameIndex()
    for _, r in df.iterrows():
        for cc, vn, en in ((r.get("MÃ BỆNH", ""), r.get("TÊN BỆNH", ""), r.get("DISEASE NAME", "")),
                           (r.get("MÃ LOẠI", ""), r.get("TÊN LOẠI", ""), r.get("TYPE NAME", ""))):
            cc = cc.strip()
            if not cc:
                continue
            for n in (vn, en):
                if n.strip():
                    code2names[cc].add(n.strip())
                    idx.add(n.strip(), cc)
    idx.build()
    return code2names, idx


def load_rxnorm(path):
    code2names, code2tty = defaultdict(set), defaultdict(set)
    idx = NameIndex()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c, s, tty = row.get("rxcui", "").strip(), row.get("str", "").strip(), row.get("tty", "")
            if c and s:
                code2names[c].add(s)
                code2tty[c].add(tty)
                idx.add(s, c, tty)
    idx.build()
    return code2names, code2tty, idx


# ---------------------------------------------------------------- kiểm tra
class Issue:
    __slots__ = ("level", "code", "doc", "line", "idx", "text", "msg")

    def __init__(self, level, code, doc, line, idx, text, msg):
        self.level, self.code, self.doc, self.line = level, code, doc, line
        self.idx, self.text, self.msg = idx, text, msg

    def row(self):
        return [self.level, self.code, self.doc, self.line, self.idx, self.text, self.msg]


def fmt_suggestions(sugs):
    return " | ".join(f"{c}{'/' + t if t else ''} {n[:45]!r} ({s})" for c, n, t, s in sugs)


def _suggest_icd(text, icd_idx, linker_backend, icd_linker, limit=3):
    """C2 suggestions for diagnoses: RapidFuzz NameIndex or SapBERT linker."""
    if linker_backend == "sapbert" and icd_linker is not None:
        return [(c, n, "", round(s, 1))
                for c, n, s in icd_linker.suggest_for_text(text, k=limit)]
    return icd_idx.suggest(text, limit=limit)


def _pick_device():
    import torch
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def build_icd_sapbert_linker(icd_path, device=None):
    """Lazy-friendly SapBERT ICD linker for validation / web UI."""
    try:
        from src.entity_linker import build_icd_linker
        from src.normalizer import read_icd10
    except ImportError:
        from entity_linker import build_icd_linker
        from normalizer import read_icd10
    alias_rows = [{"code": c, "name": n} for c, n in read_icd10(Path(icd_path))]
    return build_icd_linker(
        alias_rows, backend="sapbert", device=device or _pick_device()
    )


def check_doc(doc, txt, concepts, lines, icd, icd_idx, rx_names, rx_tty, rx_idx,
              fuzz_cutoff=55, suggest_cutoff=70, linker="rapidfuzz", icd_linker=None):
    out = []
    linker_backend = (linker or "rapidfuzz").strip().lower()
    if linker_backend in ("fuzzy", "rapid", "rapidfuzzy"):
        linker_backend = "rapidfuzz"

    def ln(i):
        return lines[i] if i is not None and 0 <= i < len(lines) else -1

    def add(lv, cd, i, t, m):
        out.append(Issue(lv, cd, doc, ln(i), i if i is not None else -1, t, m))

    spans = []
    for i, c in enumerate(concepts):
        text, typ = c.get("text", ""), c.get("type", "")
        pos = c.get("position") or [None, None]
        cands = [str(x).strip() for x in (c.get("candidates") or [])]
        assrt = c.get("assertions") or []

        # --- A. offset ---
        if pos[0] is None or pos[1] is None:
            add("ERROR", "A_NO_POS", i, text, "thiếu position")
        else:
            s, e = pos
            sub = txt[s:e] if 0 <= s <= e <= len(txt) else None
            if sub is None:
                add("ERROR", "A_OUT_OF_RANGE", i, text,
                    f"position [{s}:{e}] ngoài phạm vi (len={len(txt)})")
            elif sub != text:
                real = txt.find(text)
                hint = f"; text xuất hiện thật ở offset {real}" if real >= 0 else "; không thấy text trong file"
                add("ERROR", "A_MISMATCH", i, text, f"txt[{s}:{e}]={sub!r} != text{hint}")
            spans.append((s, e, i, text, typ))

        # --- D. type <-> candidates ---
        if typ in TYPES_NO_CANDIDATES and cands:
            add("ERROR", "D_UNEXPECTED_CAND", i, text, f"type {typ} phải rỗng nhưng có {cands}")
        if typ in TYPES_WITH_CANDIDATES and not cands:
            add("WARN", "D_MISSING_CAND", i, text, f"type {typ} nhưng candidates rỗng")

        # --- chọn từ điển theo type ---
        is_icd, is_rx = typ == "CHẨN_ĐOÁN", typ == "THUỐC"
        if not (is_icd or is_rx):
            continue

        # --- B & C. mã có tồn tại / trỏ đúng khái niệm ---
        for code in cands:
            names = icd.get(code) if is_icd else rx_names.get(code)
            label = "ICD" if is_icd else "RxCUI"
            if not names:
                add("ERROR", "B_CODE_NOT_FOUND", i, text,
                    f"{label} {code!r} KHÔNG có trong từ điển")
                continue
            best = max(fuzz.token_set_ratio(fold(text), fold(n)) for n in names)
            if best < fuzz_cutoff:
                ex = sorted(names)[0]
                tt = ",".join(sorted(rx_tty.get(code, []))) if is_rx else ""
                extra = f" [tty:{tt}]" if tt else ""
                add("WARN", "C_CODE_MISMATCH", i, text,
                    f"{label} {code} = {ex!r}{extra} (giống {best:.0f}%) - kiểm tra lại")

        # --- C2. tra NGƯỢC từ text -> đề xuất mã, đối chiếu chéo ---
        if is_icd:
            sugs = _suggest_icd(text, icd_idx, linker_backend, icd_linker, limit=3)
        else:
            sugs = rx_idx.suggest(text, extra_forms=(strip_dose_admin(text),), limit=3)
        sugs = [s for s in sugs if s[3] >= suggest_cutoff]
        if sugs:
            sug_codes = {s[0] for s in sugs}
            # ICD có cây phân cấp: J84.9 và J84.1 cùng họ "J84" -> chỉ khác độ đặc
            # hiệu, KHÔNG phải sai khái niệm. Chỉ cảnh báo khi khác hẳn họ.
            def fam(c):
                return c.split(".")[0] if is_icd else c
            same_family = bool({fam(x) for x in sug_codes} & {fam(x) for x in cands})
            if not cands:
                add("WARN", "C2_SUGGEST", i, text,
                    f"từ điển gợi ý từ chính text: {fmt_suggestions(sugs)}")
            elif sug_codes & set(cands):
                pass                                    # trùng mã -> yên tâm
            elif same_family:
                add("INFO", "C2_GRANULARITY", i, text,
                    f"mã {cands} cùng họ với gợi ý nhưng khác độ đặc hiệu: "
                    f"{fmt_suggestions(sugs)}")
            else:
                add("WARN", "C2_SUGGEST", i, text,
                    f"mã đang gán {cands} KHÔNG nằm trong gợi ý từ text: {fmt_suggestions(sugs)}")
        elif cands:
            add("INFO", "C2_NO_MATCH", i, text,
                "không tra được text trong từ điển (có thể do dịch/viết tắt) - soát tay")

        # --- H. cue nhưng thiếu assertion ---
        if pos[0] is not None:
            left = norm(txt[max(0, pos[0] - CUE_WINDOW):pos[0]])
            for cue in NEG_CUES:
                if cue in left and not any("egat" in a.lower() for a in assrt):
                    add("WARN", "H_MAYBE_NEG", i, text,
                        f"có cue {cue!r} ngay trước nhưng không có assertion phủ định")
                    break
            for cue in HIST_CUES:
                if cue in left and not any("istor" in a.lower() for a in assrt):
                    add("WARN", "H_MAYBE_HIST", i, text,
                        f"có cue {cue!r} ngay trước nhưng không có assertion tiền sử")
                    break

    # --- I. span chồng lấn ---
    spans.sort()
    for (s1, e1, i1, t1, _), (s2, e2, i2, t2, _) in zip(spans, spans[1:]):
        if s2 < e1:
            out.append(Issue("WARN", "I_OVERLAP", doc, ln(i1), i1, t1,
                             f"chồng lấn với #{i2} (dòng {ln(i2)}) {t2!r}"))

    # --- F. bỏ sót mention ---
    tagged = [(s, e) for s, e, _, _, _ in spans]
    for surface in {c.get("text", "") for c in concepts if len(c.get("text", "")) >= 4}:
        for m in re.finditer(re.escape(surface), txt):
            if not any(s <= m.start() < e for s, e in tagged):
                out.append(Issue("WARN", "F_MISSED", doc, -1, -1, surface,
                                 f"xuất hiện ở offset {m.start()} nhưng KHÔNG được annotate"))
    return out


def cross_doc_checks(all_concepts):
    out = []
    by_text_type, by_text_code, assertions = defaultdict(set), defaultdict(set), Counter()
    for doc, concepts in all_concepts.items():
        for c in concepts:
            key = norm(c.get("text", ""))
            by_text_type[key].add(c.get("type", ""))
            if c.get("candidates"):
                by_text_code[(key, c.get("type", ""))].add(
                    tuple(sorted(map(str, c["candidates"]))))
            for a in c.get("assertions") or []:
                assertions[a] += 1
    for text, types in by_text_type.items():
        if len(types) > 1:
            out.append(Issue("WARN", "G_TYPE_CONFLICT", "<corpus>", -1, -1, text,
                             f"cùng chuỗi nhưng nhiều type: {sorted(types)}"))
    for (text, typ), codesets in by_text_code.items():
        if len(codesets) > 1:
            out.append(Issue("WARN", "G_CODE_CONFLICT", "<corpus>", -1, -1, text,
                             f"[{typ}] cùng chuỗi nhưng nhiều mã: {sorted(codesets)}"))
    if assertions:
        out.append(Issue("INFO", "E_ASSERTION_VOCAB", "<corpus>", -1, -1, "",
                         f"tập nhãn assertion đang dùng: {dict(assertions)}"))
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--txt"); ap.add_argument("--json"); ap.add_argument("--dir")
    ap.add_argument("--icd", default="data/knowledge_base/ICD10_VN.csv")
    ap.add_argument("--rxnorm", default="data/knowledge_base/RXNORM.csv")
    ap.add_argument("--report", default=None)
    ap.add_argument("--suggest-cutoff", type=int, default=70,
                    help="ngưỡng điểm để hiện gợi ý mã tra từ text (0-100)")
    ap.add_argument("--linker", choices=["rapidfuzz", "sapbert"], default="rapidfuzz",
                    help="cách gợi ý mã ICD từ text (C2): rapidfuzz (mặc định) hoặc sapbert; "
                         "RxNorm luôn dùng RapidFuzz")
    args = ap.parse_args()

    pairs = []
    if args.dir:
        for fn in sorted(os.listdir(args.dir)):
            if fn.endswith(".json"):
                t = os.path.join(args.dir, fn[:-5] + ".txt")
                if os.path.exists(t):
                    pairs.append((t, os.path.join(args.dir, fn)))
    elif args.txt and args.json:
        pairs.append((args.txt, args.json))
    else:
        ap.error("cần --txt/--json hoặc --dir")

    print("Nạp từ điển...", file=sys.stderr)
    icd, icd_idx = load_icd(args.icd)
    rx_names, rx_tty, rx_idx = load_rxnorm(args.rxnorm)
    icd_linker = None
    if args.linker == "sapbert":
        print("Nạp SapBERT ICD linker...", file=sys.stderr)
        icd_linker = build_icd_sapbert_linker(args.icd)
    print(f"ICD C2 linker: {args.linker}", file=sys.stderr)

    issues, all_concepts = [], {}
    for tpath, jpath in pairs:
        txt = open(tpath, encoding="utf-8").read()
        concepts = json.load(open(jpath, encoding="utf-8"))
        doc = os.path.basename(jpath)
        all_concepts[doc] = concepts
        issues += check_doc(doc, txt, concepts, json_line_map(jpath),
                            icd, icd_idx, rx_names, rx_tty, rx_idx,
                            suggest_cutoff=args.suggest_cutoff,
                            linker=args.linker, icd_linker=icd_linker)
    issues += cross_doc_checks(all_concepts)

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    issues.sort(key=lambda x: (order[x.level], x.code, x.doc, x.line))
    for it in issues:
        loc = f"L{it.line}/#{it.idx}" if it.line > 0 else (f"#{it.idx}" if it.idx >= 0 else "-")
        print(f"[{it.level:5}] {it.code:18} {it.doc} {loc:12} {it.text!r}: {it.msg}")

    print("\n=== TỔNG KẾT ===")
    print(f"documents: {len(pairs)} | concepts: {sum(len(v) for v in all_concepts.values())}")
    for lv in ("ERROR", "WARN", "INFO"):
        print(f"  {lv}: {sum(1 for i in issues if i.level == lv)}")
    print(" ", dict(Counter(i.code for i in issues)))

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["level", "code", "doc", "line", "idx", "text", "msg", "verdict", "fix"])
            for it in issues:
                w.writerow(it.row() + ["", ""])
        print(f"\nĐã ghi {args.report} (điền cột verdict/fix khi soát tay)")


# python scripts/validate_annotation.py --txt data/generated_medical_records/restyled/text/mtsamples_cardio_0001_pho_bien.txt --json data/generated_medical_records/restyled/annotations_gold/mtsamples_cardio_0001_pho_bien.json
if __name__ == "__main__":
    main()