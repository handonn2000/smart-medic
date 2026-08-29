#!/usr/bin/env python3
"""Đo phần gán mã của src/normalizer.py trên những span đáp án CÓ mã.

    python scripts/measure_normalizer.py
    python scripts/measure_normalizer.py --gold data/dev/gold --text-dir data/test

candidates chiếm 0,4 trong điểm cuối — nặng nhất ba thành phần — nhưng trước script này
không ai biết nó đúng bao nhiêu phần trăm. Ở đây đo ba thứ tách rời nhau, vì ba thứ đó
sửa bằng ba cách khác nhau:

  * XẾP HẠNG  — mã đúng có nằm ở hạng 1 không, hay tụt xuống hạng 2, 3?
  * NGƯỠNG    — mã đúng có bị `score > 65` / `score > 70` loại thẳng không?
  * SỐ LƯỢNG  — đáp án gần như luôn đúng MỘT mã, nên trả 3 mã thì J tối đa còn 1/3.

Cách chấm giống evaluate.py: J = |giao| / |hợp|, hai bên đều rỗng thì J = 1, một bên rỗng
thì J = 0. Nghĩa là đoán mã cho span mà đáp án để rỗng cũng bị tính điểm 0, không phải
"không mất gì".

CẢNH BÁO: đáp án dùng ở đây là nhãn sinh tự động (annotations_gold), không phải đáp án của
BTC. Nó cho biết normalizer có khớp được tên bệnh/tên thuốc tiếng Việt với bảng mã hay
không — nhưng nếu chính nhãn sinh ra đã chọn sai mã thì con số ở đây cũng lệch theo.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from rapidfuzz import fuzz, process  # noqa: E402

from labels import CODEABLE_TYPES  # noqa: E402
from normalizer import (DEFAULT_TOP_K, DISEASE_CUTOFF, DRUG_CUTOFF,  # noqa: E402
                        MedicalNormalizer, normalize_drug_string)

DEFAULT_GOLD = REPO / "data" / "generated_medical_records" / "restyled" / "annotations_gold"

#: Lấy thẳng từ normalizer.py, không chép lại, để báo cáo luôn nói về cấu hình đang chạy.
CUTOFF = {"CHẨN_ĐOÁN": DISEASE_CUTOFF, "THUỐC": DRUG_CUTOFF}
SWEEP_CUTOFFS = (0, 50, 55, 60, 65, 70, 75, 80, 85)
SWEEP_TOPK = (1, 2, 3)

#: Xem sâu hơn 3 để biết mã đúng nằm ở hạng mấy khi nó không vào top 3.
DEPTH = 10


def jaccard(pred: set[str], gold: set[str]) -> float:
    """Giống evaluate.py: cả hai rỗng = 1, một bên rỗng = 0."""
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    return len(pred & gold) / len(pred | gold)


def gold_spans(gold_dir: Path) -> dict[str, list[dict]]:
    """{type: [span…]} cho hai type có mã, giữ cả span đáp án để mã rỗng."""
    out = collections.defaultdict(list)
    files = sorted(gold_dir.glob("*.json"))
    if not files:
        sys.exit(f"không có file .json nào trong {gold_dir}")
    for path in files:
        for ann in json.loads(path.read_text(encoding="utf-8")):
            if ann["type"] in CODEABLE_TYPES:
                out[ann["type"]].append(ann)
    return out


class Table:
    """Một bảng mã: tra chính xác trước, rồi fuzzy — y như normalizer.py."""

    def __init__(self, frame, code_column: str, exact: dict[str, str]):
        self.codes = frame[code_column].astype(str).tolist()
        self.names = frame["name"].tolist()
        self.exact = exact
        self.code_set = set(self.codes)
        self.name_of = {}
        for code, name in zip(self.codes, self.names):
            self.name_of.setdefault(code, name)

    def ranked(self, query: str) -> list[tuple[str, float]]:
        """[(mã, điểm)] theo hạng giảm dần; tra chính xác thì trả đúng một mã, điểm 100."""
        key = query.lower().strip()
        if key in self.exact:
            return [(str(self.exact[key]), 100.0)]
        found = process.extract(key, self.names, scorer=fuzz.token_sort_ratio, limit=DEPTH)
        return [(self.codes[index], score) for _, score, index in found]


def query_of(text: str, concept_type: str) -> str:
    """Cùng chuỗi mà normalizer.py đưa vào fuzzy — thuốc thì bỏ route/tần suất trước."""
    if concept_type == "THUỐC":
        return normalize_drug_string(text) or text.lower().strip()
    return text


def map_ranked(ranked: list[tuple[str, float]], resolve) -> list[tuple[str, float]]:
    """Áp BN/SCD → IN lên danh sách xếp hạng, giữ điểm của lần khớp đầu."""
    if resolve is None:
        return ranked
    out, seen = [], set()
    for code, score in ranked:
        mapped = resolve(code)
        if mapped not in seen:
            seen.add(mapped)
            out.append((mapped, score))
    return out


def emitted(ranked: list[tuple[str, float]], top_k: int, cutoff: int,
            resolve=None) -> set[str]:
    """Đúng thứ normalizer.py trả về: cắt top_k trước, lọc ngưỡng, rồi (thuốc) → IN."""
    return {code for code, score in map_ranked(ranked, resolve)[:top_k]
            if score > cutoff}


def check_matches_production(normalizer, table: Table, spans, concept_type: str,
                             resolve=None) -> None:
    """Xác nhận cách tính lại ở đây trùng với chính hàm trong normalizer.py."""
    call = (normalizer.normalize_disease if concept_type == "CHẨN_ĐOÁN"
            else normalizer.normalize_drug)
    for ann in spans[:40]:
        mine = emitted(table.ranked(query_of(ann["text"], concept_type)),
                       DEFAULT_TOP_K, CUTOFF[concept_type], resolve=resolve)
        if set(call(ann["text"])) != mine:
            sys.exit(f"đo lệch với normalizer.py tại {ann['text']!r}: "
                     f"{sorted(call(ann['text']))} vs {sorted(mine)}")


def report(concept_type: str, spans, table: Table, resolve=None) -> None:
    cutoff = CUTOFF[concept_type]
    # Keep the raw fuzzy ranking; resolve BN/SCD → IN lazily. Pre-mapping the top-10 for
    # every unique drug string would mean thousands of RxNav calls on a cold cache.
    ranked = {}
    for ann in spans:
        if ann["text"] not in ranked:
            ranked[ann["text"]] = table.ranked(query_of(ann["text"], concept_type))

    with_code = [a for a in spans if a["candidates"]]
    print(f"\n{'=' * 78}")
    print(f"{concept_type} — {len(spans)} span, {len(with_code)} span có mã trong đáp án, "
          f"{len(ranked)} chuỗi khác nhau")
    print(f"{'=' * 78}")

    # Câu hỏi đầu tiên trước mọi thứ khác: mã đáp án có nằm trong bảng không? Nếu không
    # thì không cách tra nào tìm ra được, và mọi con số dưới đây là chuyện khác.
    wanted = [code for ann in with_code for code in ann["candidates"]]
    absent = [code for code in wanted if code not in table.code_set]
    print(f"\n  mã đáp án có trong bảng đã nạp: {len(wanted) - len(absent)}/{len(wanted)}"
          + (f" — thiếu: {sorted(set(absent))[:8]}" if absent else ""))

    # Mã đúng nằm ở hạng mấy, và điểm của nó là bao nhiêu?
    rank_of = collections.Counter()
    score_of = []
    for ann in with_code:
        gold = set(ann["candidates"])
        hit = None
        for i, (code, score) in enumerate(ranked[ann["text"]], 1):
            mapped = resolve(code) if resolve else code
            if mapped in gold:
                hit = i
                score_of.append(score)
                break
        rank_of[hit] += 1

    inside = sum(count for hit, count in rank_of.items() if hit is not None)
    print(f"\n  mã đáp án nằm trong {DEPTH} hạng đầu: {inside}/{len(with_code)} "
          f"({inside / max(1, len(with_code)):.1%})")
    for hit in sorted(k for k in rank_of if k is not None):
        print(f"    hạng {hit:2}: {rank_of[hit]:5}")
    print(f"    không thấy: {rank_of[None]}")

    if score_of:
        score_of.sort()
        blocked = sum(1 for s in score_of if s <= cutoff)
        print(f"\n  điểm của mã đúng: thấp nhất {score_of[0]:.0f}, "
              f"trung vị {score_of[len(score_of) // 2]:.0f}, cao nhất {score_of[-1]:.0f}")
        print(f"    bị ngưỡng score > {cutoff} loại: {blocked}/{len(score_of)} "
              f"({blocked / len(score_of):.1%})")

    # Quét ngưỡng × số mã. Điểm tính trên MỌI span của type, kể cả span đáp án để rỗng,
    # vì đó là cách candidates_score được lấy trung bình.
    print(f"\n  J trung bình trên cả {len(spans)} span (đang dùng: "
          f"top_k={DEFAULT_TOP_K}, ngưỡng {cutoff}):")
    print("    ngưỡng " + "".join(f"  top{k}  " for k in SWEEP_TOPK))
    best = (0.0, None)
    for sweep_cutoff in SWEEP_CUTOFFS:
        cells = []
        for top_k in SWEEP_TOPK:
            mean = sum(jaccard(emitted(ranked[a["text"]], top_k, sweep_cutoff, resolve),
                               set(a["candidates"])) for a in spans) / len(spans)
            cells.append(mean)
            if mean > best[0]:
                best = (mean, (top_k, sweep_cutoff))
        marks = ["*" if (k, sweep_cutoff) == (DEFAULT_TOP_K, cutoff) else " "
                 for k in SWEEP_TOPK]
        print(f"    {sweep_cutoff:6}  " +
              "".join(f"{c:.3f}{m} " for c, m in zip(cells, marks)))
    print(f"    (* = cấu hình hiện tại)   tốt nhất: {best[0]:.3f} tại "
          f"top_k={best[1][0]}, ngưỡng {best[1][1]}")

    resolved_top = {text: map_ranked(rows, resolve) for text, rows in ranked.items()}
    oracle = sum(jaccard(set(a["candidates"]) & {c for c, _ in resolved_top[a["text"]]},
                         set(a["candidates"])) for a in spans) / len(spans)
    print(f"    trần nếu chọn đúng mã trong {DEPTH} hạng đầu: {oracle:.3f}")

    print(f"\n  span mà mã đáp án KHÔNG vào {DEPTH} hạng đầu — tra thua ở đâu:")
    seen = set()
    for ann in with_code:
        if len(seen) >= 6:
            break
        top = resolved_top[ann["text"]]
        if ann["text"] in seen or set(ann["candidates"]) & {c for c, _ in top}:
            continue
        seen.add(ann["text"])
        gold = ann["candidates"][0]
        print(f"    {ann['text']!r}")
        print(f"      đáp án {gold:9} = {str(table.name_of.get(gold))[:52]!r}")
        print(f"      hạng 1 {top[0][0]:9} = {str(table.name_of.get(top[0][0]))[:52]!r}"
              f"  (điểm {top[0][1]:.0f})")


def parse_args():
    parser = argparse.ArgumentParser(description="Đo phần gán mã của normalizer.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                        help=f"thư mục nhãn JSON (mặc định: "
                             f"{DEFAULT_GOLD.relative_to(REPO).as_posix()})")
    return parser.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    spans = gold_spans(args.gold)

    normalizer = MedicalNormalizer()
    tables = {
        "CHẨN_ĐOÁN": Table(normalizer.icd_df, "code", normalizer.icd_dict),
        "THUỐC": Table(normalizer.rxnorm_df, "rxcui", normalizer.rxnorm_dict),
    }

    for concept_type in ("CHẨN_ĐOÁN", "THUỐC"):
        if not spans[concept_type]:
            print(f"\n  {concept_type}: không có span nào")
            continue
        resolve = normalizer.to_ingredient if concept_type == "THUỐC" else None
        check_matches_production(normalizer, tables[concept_type],
                                 spans[concept_type], concept_type, resolve=resolve)
        report(concept_type, spans[concept_type], tables[concept_type], resolve=resolve)
        normalizer.flush_ingredient_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
