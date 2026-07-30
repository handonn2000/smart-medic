#!/usr/bin/env python3
"""Chấm điểm nội bộ theo metric của BTC — WER trên `text`, Jaccard trên `assertions`/`candidates`.

    python scripts/evaluate.py --pred data/output --gold data/dev_gold
    python scripts/evaluate.py --pred data/output --gold data/generated_medical_records/restyled/annotations
    python scripts/evaluate.py --pred data/output --gold data/dev_gold --text-dir data/test --per-file 10

CÔNG THỨC (bản đề, mục 6 của docs/PRD.html):

    final_score      = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score
    text_score       = Σ_i (1 − WER(i)) / len(test)
    assertions_score = Σ_i J_assertions(i) / len(test)
    candidates_score = Σ_i [ J_candidates(i) · W(i) ] / Σ_i W(i),  W(i) = Σ_{k∈i} (len(gt(k)) + 1)

    J = 1 nếu gt và pred đều rỗng; J = 0 nếu gt rỗng mà pred không rỗng;
    còn lại J = |gt ∩ pred| / |gt ∪ pred|.

Hai thành phần đầu là trung bình đều theo file; `candidates_score` là trung bình CÓ
TRỌNG SỐ — file nhiều khái niệm và nhiều mã đáp án nặng điểm hơn.

BA GIẢ ĐỊNH, vì đề phát biểu mọi thứ theo sample i mà không nói cách ghép khái niệm:

 1. GHÉP pred↔gold theo CÙNG TYPE + CHỒNG LẤN KÝ TỰ, tham lam theo độ chồng lấn giảm
    dần, một-đối-một. Suy ra từ chính ghi chú của đề: đoán đúng text nhưng sai type thì
    khái niệm "bị tính 2 lần và mỗi lần 0 điểm cả 3 metric" — tức là có một bước ghép,
    và type là điều kiện ghép. Span đoán thừa và span đáp án bỏ sót đều là một đơn vị
    tính điểm riêng, đều 0 điểm; nên một span sai type mất điểm gấp đôi span bỏ qua.

 2. Cả 3 metric tính THEO TỪNG KHÁI NIỆM rồi lấy trung bình trong file (đề nói rõ điều
    này cho assertions: "lấy trung bình tất cả các giá trị này thành 1 điểm J(assertion)",
    và ghi chú "mỗi lần đều được tính 0 điểm" chỉ có nghĩa khi chấm theo khái niệm).

 3. `k` trong W(i) chạy trên MỌI khái niệm của file, không chỉ CHẨN_ĐOÁN/THUỐC: khái
    niệm không có mã đáp án vẫn nặng 1 nhờ số "+1", và được J=1 khi ta cũng để rỗng.
    Đây là lý do "để candidates rỗng cho TRIỆU_CHỨNG/TÊN_XN/KẾT_QUẢ_XN" thực sự ăn điểm.
    Đổi bằng --candidates-scope codeable để xem điểm nhạy thế nào với giả định này.

Vì cả ba đều là giả định, con số ở đây là CHỈ BÁO TƯƠNG ĐỐI để so hai phiên bản model
với nhau, không phải điểm của BTC. So sánh chỉ có nghĩa khi cùng tập gold và cùng cờ.

Chuỗi luôn được chuẩn hóa về NFC trước khi so: 20% file test ở dạng NFD, không chuẩn
hóa thì hai chuỗi trông y hệt nhau vẫn lệch nhau từng ký tự và WER thành 1.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata as ud
from pathlib import Path

#: Tên type chính thức của BTC. Đoán type ngoài danh sách này = 0 điểm ở cả 3 metric.
ENTITY_TYPES = ("CHẨN_ĐOÁN", "TRIỆU_CHỨNG", "THUỐC",
                "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM")

#: Chỉ 3 type này có assertions (đề: "với các bệnh, thuốc và triệu chứng tương ứng").
ASSERTION_TYPES = ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG")

#: Chỉ 2 type này có mã chuẩn: CHẨN_ĐOÁN -> ICD-10, THUỐC -> RxNorm.
CODEABLE_TYPES = ("CHẨN_ĐOÁN", "THUỐC")

W_TEXT, W_ASSERT, W_CAND = 0.3, 0.3, 0.4

PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


# ------------------------------------------------------------------ metric gốc

def words(s: str, lower: bool = False, strip_punct: bool = False) -> list[str]:
    s = ud.normalize("NFC", s)
    if strip_punct:
        s = PUNCT.sub(" ", s)
    if lower:
        s = s.lower()
    return s.split()


def wer(ref: list[str], hyp: list[str]) -> float:
    """(thêm + bớt + thay) / số từ đáp án, chặn trên ở 1.0.

    Chặn trên vì insertion không có mẫu số: đoán 10 từ cho đáp án 1 từ ra WER = 10,
    kéo cả file xuống âm nếu để nguyên. Chặn ở 1 đúng với tinh thần "0 điểm là đáy".
    """
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1,                  # bớt một từ đáp án
                           cur[j - 1] + 1,               # thêm một từ lạ
                           prev[j - 1] + (r != h)))       # thay
        prev = cur
    return min(1.0, prev[-1] / len(ref))


def jaccard(gold: set, pred: set) -> float:
    if not gold and not pred:
        return 1.0
    if not gold:
        return 0.0          # đáp án rỗng mà vẫn đoán -> quy ước của đề
    return len(gold & pred) / len(gold | pred)


def mean(xs: list[float], default: float) -> float:
    return sum(xs) / len(xs) if xs else default


# ---------------------------------------------------------------- đọc dữ liệu

def load_records_from(data: list[dict]) -> list[dict]:
    """Chuẩn hóa list khái niệm thô: NFC cho mọi chuỗi, position thành tuple int."""
    out = []
    for rec in data:
        pos = rec.get("position") or [0, 0]
        try:
            start, end = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
            start, end = 0, 0
        out.append({
            "text": ud.normalize("NFC", rec.get("text") or ""),
            "type": ud.normalize("NFC", (rec.get("type") or "").strip()),
            "position": (start, end),
            "assertions": {ud.normalize("NFC", str(a)) for a in rec.get("assertions") or []},
            "candidates": {str(c).strip() for c in rec.get("candidates") or []},
        })
    return out


def load_records(path: Path) -> list[dict]:
    """Đọc một file nhãn/dự đoán thành list khái niệm đã chuẩn hóa."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: JSON không đọc được — {exc}")
    if not isinstance(data, list):
        sys.exit(f"{path}: mong đợi một JSON array các khái niệm")
    return load_records_from(data)


def pair_files(gold: Path, pred: Path) -> tuple[list[tuple[str, Path, Path | None]], list[str]]:
    """Ghép file gold với file pred theo tên (không đuôi). Trả về (cặp, pred lạc)."""
    if gold.is_file():
        return [(gold.stem, gold, pred if pred.is_file() else pred / gold.name)], []

    gold_files = sorted(gold.glob("*.json"))
    if not gold_files:
        sys.exit(f"không có file .json nào trong {gold}")
    pred_files = {p.stem: p for p in pred.glob("*.json")} if pred.is_dir() else {}
    pairs = [(g.stem, g, pred_files.get(g.stem)) for g in gold_files]
    extra = sorted(set(pred_files) - {g.stem for g in gold_files})
    return pairs, extra


# ------------------------------------------------------------------ ghép span

def overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return min(a[1], b[1]) - max(a[0], b[0])


def greedy_match(gold: list[dict], pred: list[dict], same_type: bool = True
                 ) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Ghép một-đối-một theo chồng lấn ký tự, ưu tiên cặp chồng lấn nhiều nhất.

    Tham lam thay vì ghép tối ưu (Hungarian): span trong một bệnh án gần như không
    chồng lên nhau (gen_sample_data đã loại span lồng nhau), nên hai cách cho cùng
    kết quả, mà tham lam thì đọc được và tái lập được.
    """
    cands = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if same_type and g["type"] != p["type"]:
                continue
            ov = overlap(g["position"], p["position"])
            if ov > 0:
                cands.append((ov, gi, pi))
    cands.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_g: set[int] = set()
    used_p: set[int] = set()
    pairs = []
    for _, gi, pi in cands:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        pairs.append((gold[gi], pred[pi]))

    missed = [g for gi, g in enumerate(gold) if gi not in used_g]
    spurious = [p for pi, p in enumerate(pred) if pi not in used_p]
    return pairs, missed, spurious


# -------------------------------------------------------------- chấm một file

def score_sample(gold: list[dict], pred: list[dict], opts) -> dict:
    pairs, missed, spurious = greedy_match(gold, pred)

    # Span đoán chồng lấn đáp án nhưng khác type: mất điểm 2 lần, tách riêng để đo.
    wrong_type, _, _ = greedy_match(missed, spurious, same_type=False)

    cand_scope = None if opts.candidates_scope == "all" else CODEABLE_TYPES

    text_units = [1.0 - wer(words(g["text"], opts.lower, opts.strip_punct),
                            words(p["text"], opts.lower, opts.strip_punct))
                  for g, p in pairs]
    text_units += [0.0] * (len(missed) + len(spurious))

    assert_units: list[float] = []
    cand_units: list[float] = []
    weight = 0

    for g, p in pairs:
        if g["type"] in ASSERTION_TYPES:
            assert_units.append(jaccard(g["assertions"], p["assertions"]))
        if cand_scope is None or g["type"] in cand_scope:
            cand_units.append(jaccard(g["candidates"], p["candidates"]))
            weight += len(g["candidates"]) + 1

    for g in missed:
        if g["type"] in ASSERTION_TYPES:
            assert_units.append(0.0)
        if cand_scope is None or g["type"] in cand_scope:
            cand_units.append(0.0)
            weight += len(g["candidates"]) + 1

    for p in spurious:
        if p["type"] in ASSERTION_TYPES:
            assert_units.append(0.0)
        if cand_scope is None or p["type"] in cand_scope:
            cand_units.append(0.0)
            weight += 1        # khái niệm này không có trong gold -> len(gt) = 0

    return {
        "text": mean(text_units, 1.0),
        "assertions": mean(assert_units, 1.0),
        "candidates": mean(cand_units, 1.0),
        "weight": weight,
        "n_gold": len(gold),
        "n_pred": len(pred),
        "n_matched": len(pairs),
        "n_missed": len(missed),
        "n_spurious": len(spurious),
        "n_wrong_type": len(wrong_type),
        "pairs": pairs,
        "missed": missed,
        "spurious": spurious,
    }


def final_score(text: float, assertions: float, candidates: float) -> float:
    return W_TEXT * text + W_ASSERT * assertions + W_CAND * candidates


# ------------------------------------------------------------------- báo cáo

def check_offsets(records: list[dict], raw: str) -> int:
    """Số span mà raw[position] không đúng bằng text — offset lệch là mất điểm kép.

    Cắt trên chuỗi GỐC rồi mới chuẩn hóa mẩu cắt: 20% file test ở dạng NFD, chuẩn hóa
    cả file trước khi cắt làm đổi độ dài chuỗi nên mọi offset lệch theo, báo lỗi giả.
    """
    return sum(1 for r in records
               if ud.normalize("NFC", raw[r["position"][0]:r["position"][1]]) != r["text"])


def report_types(per_file: dict, opts) -> None:
    """Bảng theo type: đáp án / ghép được / bỏ sót / đoán thừa + điểm trung bình."""
    n_gold: collections.Counter = collections.Counter()
    n_match: collections.Counter = collections.Counter()
    n_miss: collections.Counter = collections.Counter()
    n_spur: collections.Counter = collections.Counter()
    text_by: collections.defaultdict = collections.defaultdict(list)
    asrt_by: collections.defaultdict = collections.defaultdict(list)
    cand_by: collections.defaultdict = collections.defaultdict(list)

    for res in per_file.values():
        for g, p in res["pairs"]:
            n_gold[g["type"]] += 1
            n_match[g["type"]] += 1
            text_by[g["type"]].append(
                1.0 - wer(words(g["text"], opts.lower, opts.strip_punct),
                          words(p["text"], opts.lower, opts.strip_punct)))
            if g["type"] in ASSERTION_TYPES:
                asrt_by[g["type"]].append(jaccard(g["assertions"], p["assertions"]))
            cand_by[g["type"]].append(jaccard(g["candidates"], p["candidates"]))
        for g in res["missed"]:
            n_gold[g["type"]] += 1
            n_miss[g["type"]] += 1
        for p in res["spurious"]:
            n_spur[p["type"]] += 1

    types = sorted(set(n_gold) | set(n_spur),
                   key=lambda t: (t not in ENTITY_TYPES, ENTITY_TYPES.index(t)
                                  if t in ENTITY_TYPES else 0))
    print(f"\n{'-' * 78}")
    print(f"  {'type':22}{'gold':>6}{'ghép':>6}{'sót':>6}{'thừa':>6}"
          f"{'text':>9}{'J asrt':>9}{'J cand':>9}   (trên span đã ghép)")
    for ctype in types:
        flag = "" if ctype in ENTITY_TYPES else "  <- không phải type của BTC"
        # Ba type còn lại không có assertions nên bỏ trống, đừng in 0.000 như thể mất điểm.
        asrt = (f"{mean(asrt_by[ctype], 0.0):.3f}" if ctype in ASSERTION_TYPES else "—")
        print(f"  {ctype:22}{n_gold[ctype]:>6}{n_match[ctype]:>6}"
              f"{n_miss[ctype]:>6}{n_spur[ctype]:>6}"
              f"{mean(text_by[ctype], 0.0):>9.3f}{asrt:>9}"
              f"{mean(cand_by[ctype], 0.0):>9.3f}{flag}")


def report_worst(per_file: dict, n: int) -> None:
    ranked = sorted(per_file.items(),
                    key=lambda kv: final_score(kv[1]["text"], kv[1]["assertions"],
                                               kv[1]["candidates"]))
    print(f"\n{'-' * 78}")
    print(f"  {n} file điểm thấp nhất:")
    print(f"  {'file':24}{'final':>8}{'text':>8}{'asrt':>8}{'cand':>8}"
          f"{'gold':>7}{'ghép':>7}{'sót':>7}{'thừa':>7}")
    for name, res in ranked[:n]:
        print(f"  {name[:23]:24}"
              f"{final_score(res['text'], res['assertions'], res['candidates']):>8.3f}"
              f"{res['text']:>8.3f}{res['assertions']:>8.3f}{res['candidates']:>8.3f}"
              f"{res['n_gold']:>7}{res['n_matched']:>7}"
              f"{res['n_missed']:>7}{res['n_spurious']:>7}")


# ------------------------------------------------------------------- tự kiểm

#: Đáp án của bộ tự kiểm: 1 file, 2 khái niệm, đủ để cố định ngữ nghĩa của metric.
SELF_GOLD = [
    {"text": "ho đờm xanh", "type": "TRIỆU_CHỨNG", "candidates": [], "assertions": [],
     "position": [0, 11]},
    {"text": "aspirin", "type": "THUỐC", "candidates": ["1191"],
     "assertions": ["isHistorical"], "position": [20, 27]},
]

#: (tên, dự đoán, điểm tính tay). Bộ này chốt hai điều dễ hỏng khi sửa code:
#: NFD phải cho điểm y như NFC, và SAI TYPE phải ĐẮT HƠN bỏ hẳn span (0.333 < 0.500).
SELF_CASES: tuple[tuple[str, list[dict], float], ...] = (
    ("khớp hoàn toàn", SELF_GOLD, 1.0),
    ("cùng nội dung, dạng NFD",
     [dict(r, text=ud.normalize("NFD", r["text"])) for r in SELF_GOLD], 1.0),
    ("cắt cụt 1 từ + thừa 1 mã + thiếu assertion", [
        {"text": "ho đờm", "type": "TRIỆU_CHỨNG", "candidates": [], "assertions": [],
         "position": [0, 6]},
        {"text": "aspirin", "type": "THUỐC", "candidates": ["1191", "999"],
         "assertions": [], "position": [20, 27]},
     ], 0.3 * (5 / 6) + 0.3 * 0.5 + 0.4 * 0.75),
    ("bỏ hẳn khái niệm 2", SELF_GOLD[:1], 0.5),
    ("khái niệm 2 đúng text nhưng SAI TYPE", [
        SELF_GOLD[0],
        dict(SELF_GOLD[1], type="CHẨN_ĐOÁN"),
     ], 1 / 3),
    ("đoán rỗng", [], 0.0),
)


def self_test() -> int:
    """Chấm 6 ví dụ tính tay bằng cờ mặc định, so với điểm đã tính trên giấy."""
    opts = argparse.Namespace(candidates_scope="all", lower=False, strip_punct=False)
    gold = load_records_from(SELF_GOLD)
    fails = 0
    print(f"\n  {'ca kiểm':48}{'điểm':>8}{'tính tay':>10}")
    for name, pred, expected in SELF_CASES:
        res = score_sample(gold, load_records_from(pred), opts)
        got = final_score(res["text"], res["assertions"], res["candidates"])
        ok = abs(got - expected) < 1e-9
        fails += not ok
        print(f"  {'ok ' if ok else 'SAI'} {name:44}{got:>8.4f}{expected:>10.4f}")
    print(f"\n  {'ĐẠT' if not fails else f'{fails} ca SAI'}\n")
    return 1 if fails else 0


# ----------------------------------------------------------------------- CLI

def resolve_text_dir(gold: Path, given: str | None) -> Path | None:
    """--text-dir hoặc, nếu gold nằm trong .../annotations, thư mục .../text kề bên."""
    if given:
        return Path(given)
    base = gold.parent if gold.is_file() else gold
    if base.name == "annotations" and (base.parent / "text").is_dir():
        return base.parent / "text"
    return None


def main() -> int:
    # Console Windows mặc định cp1252, in tiếng Việt có dấu là UnicodeEncodeError.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="Chấm điểm nội bộ theo metric của đề (WER + Jaccard)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("CÔNG THỨC")[1])
    ap.add_argument("--pred", help="thư mục (hoặc file) JSON dự đoán, VD data/output")
    ap.add_argument("--gold",
                    help="thư mục (hoặc file) JSON đáp án; ghép với --pred theo tên file")
    ap.add_argument("--text-dir",
                    help="thư mục .txt gốc để kiểm position (mặc định: suy từ --gold"
                         " nếu gold nằm trong .../annotations)")
    ap.add_argument("--candidates-scope", choices=("all", "codeable"), default="all",
                    help="k trong W(i) chạy trên mọi khái niệm (all, mặc định)"
                         " hay chỉ CHẨN_ĐOÁN+THUỐC (codeable)")
    ap.add_argument("--lower", action="store_true",
                    help="bỏ qua hoa/thường khi tính WER (đề không nói rõ; mặc định là phân biệt)")
    ap.add_argument("--strip-punct", action="store_true",
                    help="bỏ dấu câu khi tính WER (mặc định là giữ)")
    ap.add_argument("--per-file", type=int, default=0, metavar="N",
                    help="in N file điểm thấp nhất")
    ap.add_argument("--json", metavar="PATH", help="ghi điểm từng file ra JSON")
    ap.add_argument("--self-test", action="store_true",
                    help="chấm 6 ví dụ tính tay để kiểm chính script này")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.pred or not args.gold:
        ap.error("cần cả --pred và --gold (hoặc dùng --self-test)")

    gold_root, pred_root = Path(args.gold), Path(args.pred)
    for path in (gold_root, pred_root):
        if not path.exists():
            sys.exit(f"không tìm thấy {path}")

    file_pairs, extra_pred = pair_files(gold_root, pred_root)
    text_dir = resolve_text_dir(gold_root, args.text_dir)

    per_file: dict[str, dict] = {}
    missing_pred: list[str] = []
    bad_offsets = 0
    unofficial: collections.Counter = collections.Counter()

    for name, gold_file, pred_file in file_pairs:
        gold = load_records(gold_file)
        if pred_file is None or not pred_file.exists():
            missing_pred.append(name)
            pred = []
        else:
            pred = load_records(pred_file)
        for rec in pred:
            if rec["type"] not in ENTITY_TYPES:
                unofficial[rec["type"] or "(rỗng)"] += 1
        if text_dir is not None:
            raw_file = text_dir / f"{name}.txt"
            if raw_file.exists():
                bad_offsets += check_offsets(pred, raw_file.read_text(encoding="utf-8"))
        per_file[name] = score_sample(gold, pred, args)

    if not per_file:
        sys.exit("không có file nào để chấm")

    results = list(per_file.values())
    text_score = mean([r["text"] for r in results], 1.0)
    assert_score = mean([r["assertions"] for r in results], 1.0)
    total_weight = sum(r["weight"] for r in results)
    cand_score = (sum(r["candidates"] * r["weight"] for r in results) / total_weight
                  if total_weight else mean([r["candidates"] for r in results], 1.0))
    final = final_score(text_score, assert_score, cand_score)

    n_gold = sum(r["n_gold"] for r in results)
    n_pred = sum(r["n_pred"] for r in results)
    n_match = sum(r["n_matched"] for r in results)
    n_miss = sum(r["n_missed"] for r in results)
    n_spur = sum(r["n_spurious"] for r in results)
    n_wrong = sum(r["n_wrong_type"] for r in results)

    print(f"\n{'=' * 78}\n{'CHẤM ĐIỂM NỘI BỘ — WER + JACCARD':^78}\n{'=' * 78}\n")
    print(f"  gold: {str(gold_root):55} {len(file_pairs):4d} file")
    print(f"  pred: {str(pred_root):55} {len(file_pairs) - len(missing_pred):4d} file")
    print(f"  ghép khái niệm: cùng type + chồng lấn offset (giả định của ta, không phải BTC)")
    print(f"  candidates-scope: {args.candidates_scope}"
          f"   WER: {'không' if args.lower else 'có'} phân biệt hoa/thường,"
          f" {'bỏ' if args.strip_punct else 'giữ'} dấu câu\n")

    print(f"  text_score        {text_score:6.4f}   × {W_TEXT}")
    print(f"  assertions_score  {assert_score:6.4f}   × {W_ASSERT}")
    print(f"  candidates_score  {cand_score:6.4f}   × {W_CAND}"
          f"   (trọng số tổng {total_weight})")
    print(f"  {'-' * 40}")
    print(f"  final_score       {final:6.4f}\n")

    print("KHÁI NIỆM")
    print(f"  đáp án                {n_gold:6d}")
    print(f"  dự đoán               {n_pred:6d}")
    print(f"  ghép được             {n_match:6d}"
          f"   ({100 * n_match / max(n_gold, 1):.0f}% recall,"
          f" {100 * n_match / max(n_pred, 1):.0f}% precision)")
    print(f"  bỏ sót                {n_miss:6d}")
    print(f"  đoán thừa             {n_spur:6d}")
    print(f"  trong đó SAI TYPE     {n_wrong:6d}   (chồng lấn đáp án nhưng khác loại"
          f" -> mất điểm 2 lần)")

    report_types(per_file, args)
    if args.per_file:
        report_worst(per_file, min(args.per_file, len(per_file)))

    if missing_pred or extra_pred or unofficial or bad_offsets:
        print(f"\n{'-' * 78}\nCẢNH BÁO")
    if missing_pred:
        print(f"  thiếu {len(missing_pred)} file dự đoán, chấm như đoán rỗng:"
              f" {', '.join(missing_pred[:8])}{' …' if len(missing_pred) > 8 else ''}")
    if extra_pred:
        print(f"  {len(extra_pred)} file dự đoán không có đáp án, bỏ qua:"
              f" {', '.join(extra_pred[:8])}{' …' if len(extra_pred) > 8 else ''}")
    if unofficial:
        print(f"  {sum(unofficial.values())} span mang type KHÔNG phải của BTC"
              f" (0 điểm cả 3 metric): {dict(unofficial.most_common(8))}")
    if bad_offsets:
        print(f"  {bad_offsets} span có text != văn bản gốc tại position — offset lệch"
              f" làm hỏng bước ghép, mất điểm 2 lần")

    if args.json:
        out = {name: {k: v for k, v in res.items()
                      if k not in ("pairs", "missed", "spurious")}
               for name, res in per_file.items()}
        out["_total"] = {"text_score": text_score, "assertions_score": assert_score,
                         "candidates_score": cand_score, "final_score": final,
                         "n_files": len(per_file), "weight": total_weight}
        Path(args.json).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  điểm từng file -> {args.json}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
