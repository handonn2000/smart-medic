"""Build a tiered reference set from several independent LLM annotators.

    python scripts/gold/build_consensus_gold.py --docs 1-100 --out data/consensus_gold

Replaces `data/proxy_gold_test/`, which is one LLM pass over 20 documents. A
single pass cannot show its own blind spots; three passes written from different
framings can, because they fail differently and their disagreement is visible.

Measured on 5 documents with all three annotators present:

    A-B span F1 0.857   A-C 0.816   B-C 0.756   type agreement 0.99+

An F1 near 0.8 between independent annotators means the task is well defined and
a consensus of them is worth trusting. (Near 0.5 would have meant the opposite,
and no amount of voting repairs that.) Against the same 5 documents the existing
single-pass gold misses 18 spans that 2+ annotators agreed on, and carries 7 that
none of them proposed — which is why recall measured against it reads 0.611 when
the honest range is 0.50 to 0.60.

Run this from the repl/analysis kernel via `host.llm`, not here — this module
holds the prompts, parsing and I/O so the calling code stays short.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

TYPES = (
    "TRIỆU_CHỨNG",
    "CHẨN_ĐOÁN",
    "THUỐC",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
)

#: Three framings, deliberately different. Identical prompts would agree for the
#: wrong reason — shared blind spots look like consensus.
PROMPTS = {
    "A": """Bạn là bác sĩ gán nhãn khái niệm y khoa trong văn bản tiếng Việt.

Liệt kê MỌI khái niệm y khoa theo đúng thứ tự xuất hiện.

5 LOẠI:
- TRIỆU_CHỨNG: dấu hiệu bệnh nhân cảm nhận/quan sát (đau bụng, sốt, ho, ngứa)
- CHẨN_ĐOÁN: tên bệnh, hội chứng (viêm phổi, đái tháo đường)
- THUỐC: tên thuốc, hoạt chất, nhóm thuốc, vitamin. Tên bị che bằng *** VẪN tính là THUỐC.
- TÊN_XÉT_NGHIỆM: tên phép đo/thăm dò (công thức máu, siêu âm, HbA1c)
- KẾT_QUẢ_XÉT_NGHIỆM: giá trị/kết luận (12.5 g/dL, âm tính, bình thường)

BẮT BUỘC:
- Gán MỌI lần xuất hiện, kể cả chuỗi lặp lại nhiều lần.
- Lấy cụm ĐẦY ĐỦ nguyên văn, giữ nguyên hoa/thường và dấu.

JSON array: {{"text":"<nguyên văn>","type":"<loại>","nth":<lần xuất hiện thứ mấy, từ 1>}}
Chỉ trả JSON.

VĂN BẢN:
{text}""",
    "B": """Nhiệm vụ: trích xuất thực thể y khoa (NER) từ văn bản tiếng Việt cho cuộc thi.

Duyệt văn bản TỪ ĐẦU ĐẾN CUỐI. Mỗi khi gặp một khái niệm y khoa, ghi lại.

Nhãn cho phép: TRIỆU_CHỨNG | CHẨN_ĐOÁN | THUỐC | TÊN_XÉT_NGHIỆM | KẾT_QUẢ_XÉT_NGHIỆM

Phân biệt quan trọng:
- "viêm phổi" là CHẨN_ĐOÁN (bệnh), "ho" là TRIỆU_CHỨNG (biểu hiện)
- "công thức máu" là TÊN_XÉT_NGHIỆM, "HC 3.2 T/L" là KẾT_QUẢ_XÉT_NGHIỆM
- chuỗi dấu sao (***) thay tên thuốc bị che -> THUỐC
- tên nhóm thuốc ("thuốc lợi tiểu", "kháng sinh") -> THUỐC

Đừng bỏ sót lần xuất hiện lặp lại. Đừng gộp hai khái niệm liền nhau thành một.

JSON array: {{"text":"<nguyên văn>","type":"<nhãn>","nth":<số thứ tự lần xuất hiện>}}

VĂN BẢN:
{text}""",
    "C": """Bạn đang xây tập kiểm thử cho hệ NER y khoa tiếng Việt. Cần độ PHỦ cao.

Đọc văn bản, liệt kê mọi cụm từ chỉ: triệu chứng, chẩn đoán/bệnh, thuốc,
tên xét nghiệm, hoặc kết quả xét nghiệm.

Nhãn: TRIỆU_CHỨNG, CHẨN_ĐOÁN, THUỐC, TÊN_XÉT_NGHIỆM, KẾT_QUẢ_XÉT_NGHIỆM

Nguyên tắc: thà ghi nhận một cụm còn nghi ngờ, hơn là bỏ sót nó.
Cụm bị che bằng dấu sao là tên thuốc -> THUỐC.
Ghi mọi lần xuất hiện, kể cả trùng lặp.
Trích nguyên văn, không sửa chính tả, không thêm bớt.

JSON array các phần tử {{"text":..., "type":..., "nth":...}} với nth là lần xuất hiện thứ mấy.

VĂN BẢN:
{text}""",
}


def parse_response(body: str) -> list | None:
    """Pull the JSON array out of a model reply, tolerating a trailing comma."""
    match = re.search(r"\[[\s\S]*\]", body)
    if not match:
        return None
    for candidate in (match.group(0), re.sub(r",\s*([\]}])", r"\1", match.group(0))):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def locate(text: str, items: list) -> list[dict]:
    """Turn {text, type, nth} into offsets by searching the document.

    Asking the model for offsets directly does not work — it cannot count
    characters. Asking which OCCURRENCE it means, and finding that occurrence
    here, gives exact positions.
    """
    out: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        surface = (item.get("text") or "").strip()
        etype = item.get("type")
        if not surface or etype not in TYPES:
            continue
        try:
            nth = max(1, int(item.get("nth", 1) or 1))
        except Exception:
            nth = 1
        positions = [m.start() for m in re.finditer(re.escape(surface), text)]
        if not positions:
            continue
        start = positions[min(nth, len(positions)) - 1]
        key = (start, start + len(surface), etype)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {"text": surface, "type": etype, "position": [start, start + len(surface)]}
        )
    return sorted(out, key=lambda e: e["position"])


def parse_doc_range(spec: str) -> list[str]:
    ids: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            ids += [str(i) for i in range(int(lo), int(hi) + 1)]
        elif part:
            ids.append(part)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", default="1-100", help="e.g. 1-100 or 3,7,12")
    ap.add_argument("--input", default="data/test")
    ap.add_argument("--out", default="data/consensus_gold")
    args = ap.parse_args()

    ids = parse_doc_range(args.docs)
    missing = [i for i in ids if not (Path(args.input) / f"{i}.txt").is_file()]
    print(f"{len(ids)} documents requested, {len(missing)} missing")
    print(f"annotators: {', '.join(sorted(PROMPTS))}")
    print(f"→ {len(ids) * len(PROMPTS)} LLM calls")
    print()
    print("This module holds the prompts and parsing only. Drive it from the")
    print("analysis kernel, where host.llm can fan the requests out in parallel:")
    print()
    print("    import build_consensus_gold as B, consensus")
    print("    reqs = [{'prompt': B.PROMPTS[t].format(text=raw[k]),")
    print("             'model': host.reasoning_model(), 'max_tokens': 20000}")
    print("            for t in B.PROMPTS for k in ids]")
    print("    res  = host.llm(reqs, max_concurrency=8)")
    print("    # → B.parse_response / B.locate → consensus.vote → consensus.write")


if __name__ == "__main__":
    main()
