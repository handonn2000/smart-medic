#!/usr/bin/env python3
"""Sinh dữ liệu train từ mtsamples: dịch có khoá tên thuốc, nhãn tính bằng code.

Vấn đề của cách "dịch rồi nhờ LLM annotate": nhãn thừa hưởng sai số của LLM —
đã đo được chuỗi thu ngắn gold 3,53 → silver 3,09 → pred v4 2,36 từ. Script này
tránh hẳn việc đó: **LLM chỉ sinh phần văn bản KHÔNG phải thực thể**, còn mọi
thực thể đều do code chèn vào, nên offset và nhãn đúng tuyệt đối theo cách dựng.

Bốn bước, chạy riêng được từng bước:

    prepare    khoá tên thuốc/viết tắt lab trong note tiếng Anh thành placeholder
    translate  LLM dịch sang tiếng Việt, thay mọi mention thực thể bằng slot token
    fill       code điền slot từ bảng ICD/RxNorm của BTC, ghi nhãn theo offset dựng
    verify     kiểm lại: text[position] khớp từng ký tự, round-trip qua build_textref

Tại sao phải qua slot chứ không annotate bản dịch: nếu để LLM dịch nguyên văn rồi
gán nhãn, mọi mention nó bỏ sót thành nhãn O → dạy model rằng chỗ đó KHÔNG phải
thực thể → sinh thêm false negative. Với slot thì mỗi ký tự trong tài liệu đều có
chủ: hoặc là thực thể ta chèn, hoặc là văn bản đệm ta biết chắc không chứa thực thể
(bước verify quét lại bằng gazetteer để chứng minh điều đó).

Đo được trên 40 tài liệu sinh thử (mặc định hiện tại), so với dữ liệu BTC:

    độ dài span (từ)      sinh ra   gold        đặc điểm            sinh ra  test
      CHẨN_ĐOÁN              3,99   4,05          file có bẫy ***       30%   30%
      KẾT_QUẢ_XÉT_NGHIỆM     4,29   5,32          file dạng NFD         22%   20%
      THUỐC                  1,95   2,10          file có tiêu đề mục  100%   81%
      TRIỆU_CHỨNG            3,44   3,27
      TÊN_XÉT_NGHIỆM         3,70   3,71        mã tra được trong bảng: 654/654

Offset sai: 0. Mọi mã sinh ra đều tra được trong bảng BTC — nghĩa là phần liên kết
mã (trọng số nặng nhất) học từ nhãn đúng tuyệt đối, không phải nhãn LLM đoán.

Chạy:
    python scripts/synth_from_mtsamples.py prepare
    python scripts/synth_from_mtsamples.py translate --use-api     # cần ANTHROPIC_API_KEY
    python scripts/synth_from_mtsamples.py translate --skeletons FILE.jsonl   # hoặc nạp sẵn
    python scripts/synth_from_mtsamples.py fill --n 400
    python scripts/synth_from_mtsamples.py verify
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import os
import random
import re
import shutil
import statistics as st
import sys
import unicodedata as ud
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

KB = REPO / "data" / "kb"
EXT = REPO / "data" / "external"
WORK = REPO / "data" / "synth" / "work"
OUT_LABELS = REPO / "data" / "synth"
OUT_TEXT = REPO / "data" / "train_input"

SEED = 20260727

# ---------------------------------------------------------------- placeholder

#: Placeholder khoá tên thuốc. Dùng ký tự ⟦⟧ vì chúng không xuất hiện trong
#: mtsamples lẫn bảng KB, nên không thể trùng nội dung thật. Bước translate
#: LOẠI note nào placeholder không về đủ — không tin prompt, kiểm bằng code.
PH = "⟦{}{:02d}⟧"
PH_RE = re.compile(r"⟦([A-Z])(\d{2})⟧")

#: Slot cho từng loại thực thể. LLM chỉ được sinh slot, không sinh tên thật.
SLOTS = {
    "DX": "CHẨN_ĐOÁN",
    "SYM": "TRIỆU_CHỨNG",
    "TEST": "TÊN_XÉT_NGHIỆM",
    "RES": "KẾT_QUẢ_XÉT_NGHIỆM",
    "DRUG": "THUỐC",
}
SLOT_RE = re.compile(r"\{\{(DX|SYM|TEST|RES|DRUG)\}\}")

EN_LAB = (
    r"\b(WBC|RBC|HGB|HCT|PLT|NEUT|LYMPH|MCV|MCH|AST|ALT|GOT|GPT|CRP|HbA1c|BUN"
    r"|LDL|HDL|TSH|CEA|ESR|INR)\b"
)

#: Bảng RxNorm chứa biệt dược trùng từ tiếng Anh thông thường. Không lọc thì
#: "today" bị khoá 247 lần trên 457 note — nhiều nhất trong toàn bộ, và mọi lần
#: đều là trạng từ chỉ thời gian. Danh sách này duyệt tay từ 59 alias trùng từ
#: điển hệ thống trong chính 457 note đã lọc; không dùng từ điển làm bộ lọc tự
#: động được vì nó chặn luôn aspirin, morphine, heparin, codeine.
DRUG_STOP = {
    "today", "tomorrow", "yesterday", "air", "water", "perform", "restart",
    "tandem", "lead", "fiber", "latex", "react", "rid", "soma", "kerosene",
    "paraffin", "collagen", "lutein", "barium", "iodine", "holmium", "oxygen",
    "saline", "dextrose", "alcohol", "tissue", "control", "spirit", "gas",
    "balance", "compound", "plus", "one", "two", "free", "sensitive",
}

#: Chất phân tích: trong bệnh án chúng là ĐỐI TƯỢNG XÉT NGHIỆM, không phải thuốc
#: được kê. Đo trên 457 note: 531/2.850 lần khoá (18,6%) thuộc nhóm này, và
#: 0% có liều theo sau — nên ngữ cảnh liều không dùng để phân biệt được. Vẫn
#: khoá để LLM không dịch mất, nhưng gán nhãn TÊN_XÉT_NGHIỆM.
ANALYTE_AS_TEST = {
    "creatinine", "glucose", "cholesterol", "sodium", "potassium", "calcium",
    "magnesium", "phosphorus", "albumin", "urea", "bilirubin", "lactate",
    "ammonia", "hemoglobin", "hematocrit", "triglyceride", "fibrinogen",
    "lipase", "amylase", "prothrombin", "guaiac", "ethanol", "lactose",
    "chloride", "bicarbonate", "troponin", "ferritin", "transferrin",
    "cortisol", "testosterone", "protein", "iron", "zinc", "selenium",
}

# ------------------------------------------------------- từ vựng tiếng Việt
# Ba loại dưới KHÔNG có trong bảng của BTC (đo trên gold: TÊN_XÉT_NGHIỆM và
# KẾT_QUẢ_XÉT_NGHIỆM có 0% candidates), nên phải có danh sách riêng. Độ dài
# được chọn khớp gold: triệu chứng 3,27 từ · tên xét nghiệm 3,71 · kết quả 5,32.
# Sửa/thêm tự do — đây là hằng số, không phải dữ liệu sinh ra.

# Phân bố khớp gold: 199/410 span TRIỆU_CHỨNG chỉ 1-2 từ (median 3), đuôi dài tới
# 16 từ. Chỉ dùng cụm mô tả dài thì span sinh ra TB 4,22 từ, dài hơn gold 3,27.
SYMPTOMS = [
    # 1-2 từ (chiếm ~nửa trong gold)
    "sốt", "ho", "buồn nôn", "nôn", "khó thở", "chóng mặt", "đau đầu", "mệt",
    "vàng da", "co giật", "lú lẫn", "chảy máu", "phù", "ngứa", "ban đỏ",
    "chướng bụng", "hôi miệng", "bồn chồn", "gần ngất", "sốt cao", "đau bụng",
    "khó chịu", "sụt cân", "táo bón", "tiêu chảy", "mất ngủ", "ợ chua",
    "run tay", "tê bì", "khàn tiếng", "ngạt mũi", "đau lưng", "đau khớp",
    # 3 từ trở lên
    "đau ngực khi gắng sức", "khó thở khi nằm", "ho khan kéo dài", "sốt cao liên tục",
    "buồn nôn và nôn", "chóng mặt khi đứng lên", "đau đầu vùng thái dương",
    "mệt mỏi nhiều", "sụt cân không rõ nguyên nhân", "vàng da vàng mắt",
    "phù hai chi dưới", "tiểu buốt tiểu rắt", "đau bụng vùng hạ sườn phải",
    "tê bì hai bàn tay", "đau lưng lan xuống chân", "khó ngủ về đêm",
    "đánh trống ngực", "ra mồ hôi về đêm", "chán ăn", "táo bón kéo dài",
    "tiêu chảy nhiều lần trong ngày", "khàn tiếng", "chảy máu chân răng",
    "nổi ban đỏ toàn thân", "ngứa nhiều vùng lưng", "sưng đau khớp bàn tay",
    "cứng khớp buổi sáng", "giảm thị lực mắt phải", "nghe kém tai trái",
    "hoa mắt khi thay đổi tư thế", "run tay khi nghỉ", "yếu nửa người bên phải",
    "nói khó", "co giật toàn thể", "mất ngủ kéo dài", "lo lắng quá mức",
    "đau vùng thượng vị sau ăn", "ợ chua", "khó tiêu", "đầy hơi chướng bụng",
    "khó thở khi gắng sức nhẹ", "thở khò khè", "đau họng khi nuốt",
    "chảy nước mũi trong", "ngạt mũi hai bên", "đau tai phải", "sốt nhẹ về chiều",
    "gầy sút cân nhanh", "khát nước nhiều", "tiểu nhiều lần về đêm",
    "chuột rút bắp chân", "đau cách hồi khi đi bộ", "loét bàn chân lâu lành",
    "rụng tóc nhiều", "kinh nguyệt không đều", "đau khi quan hệ",
    "ra máu âm đạo bất thường", "són tiểu khi ho", "bí tiểu cấp", "mất cảm giác đầu chi",
]

# Phân bố khớp gold: 42/122 span TÊN_XÉT_NGHIỆM chỉ 1-2 từ (median 4), và gold có
# cả viết tắt tiếng Anh giữ nguyên ('WBC', 'LDL', 'ERCP', 'ecg', 'spo2', 'troponin')
# — đây là chỗ tôi đã giả định sai ở lượt trước khi coi hai type xét nghiệm là thuần
# cụm mô tả tiếng Việt. Chỉ dùng cụm dài thì span sinh ra TB 5,41 từ, dài hơn gold.
TEST_NAMES = [
    # 1-2 từ, gồm viết tắt Anh y như gold
    "WBC", "RBC", "HGB", "HCT", "PLT", "LDL", "HDL", "AST", "ALT", "CRP",
    "HbA1c", "BUN", "INR", "TSH", "ESR", "troponin", "ecg", "spo2", "ERCP",
    "siêu âm", "nội soi", "sinh thiết", "chụp CT", "chụp MRI", "X-quang",
    "đường huyết", "xét nghiệm", "double test", "nipt", "monitor holter",
    "NEUT%", "LDL-cholesterol", "khí máu", "điện tim", "nước tiểu",
    "xét nghiệm máu", "công thức máu toàn phần", "xét nghiệm sinh hoá máu",
    "phân tích nước tiểu", "chụp x-quang ngực", "siêu âm ổ bụng",
    "siêu âm tim qua thành ngực", "điện tâm đồ", "monitor holter điện tâm đồ",
    "chụp cắt lớp vi tính lồng ngực", "chụp cộng hưởng từ sọ não",
    "nội soi dạ dày tá tràng", "nội soi đại tràng toàn bộ",
    "xét nghiệm chức năng gan", "xét nghiệm chức năng thận",
    "định lượng đường huyết lúc đói", "xét nghiệm HbA1c", "định lượng mỡ máu",
    "xét nghiệm chức năng tuyến giáp", "cấy máu tìm vi khuẩn",
    "cấy nước tiểu định danh vi khuẩn", "xét nghiệm dịch màng phổi",
    "chọc dò dịch não tuỷ", "sinh thiết niêm mạc dạ dày",
    "đo chức năng thông khí phổi", "nghiệm pháp gắng sức thảm chạy",
    "chụp mạch vành qua da", "đo mật độ xương", "xét nghiệm đông máu cơ bản",
    "định lượng men tim troponin", "xét nghiệm khí máu động mạch",
    "soi tươi dịch âm đạo", "xét nghiệm tế bào cổ tử cung",
    "chụp x-quang khớp gối hai bên", "siêu âm doppler mạch chi dưới",
    "xét nghiệm sàng lọc sơ sinh", "lấy máu khô ở gót chân",
    "xét nghiệm nước tiểu 24 giờ", "chụp x-quang bụng không chuẩn bị",
    "siêu âm tuyến giáp", "đo điện cơ chi dưới", "xét nghiệm phân tìm hồng cầu",
]

# Phân bố độ dài khớp gold: 32/63 span KẾT_QUẢ_XÉT_NGHIỆM chỉ 1-3 từ (median 3),
# nhưng đuôi dài tới 19 từ kéo trung bình lên 5,32. Danh sách phải có cả hai phía —
# chỉ dùng cụm mô tả dài thì span sinh ra TB 7,08 từ, dài hơn gold.
RESULT_PHRASES = [
    # 1-3 từ (chiếm phần lớn trong gold)
    "bình thường", "âm tính", "dương tính", "dương tính yếu", "không bất thường",
    "tăng nhẹ", "giảm nhẹ", "tăng cao", "trong giới hạn", "chưa ghi nhận",
    "không rõ tổn thương", "ổn định", "tăng", "giảm",
    # số trần và số kèm đơn vị — gold có gán nhãn dạng này: '12.5', '1.05',
    # '38.3°C', '<70 mg/dL', '90-92%', '93%', '14.99 G/L', '92 g/L'
    "12.5", "1.05", "9.3", "0.3", "38.3°C", "37.8°C", "93%", "90-92%",
    "<70 mg/dL", "14.99 G/L", "92 g/L", "140 mmol/L", "4.4 mmol/L",
    "110 mg/dL", "1.8 mg/dL", "26 U/L", "56 U/L",
    # 4 từ trở lên
    "không ghi nhận gì bất thường", "trong giới hạn bình thường",
    "không có gì đáng chú ý", "bình thường", "nhịp xoang chiếm ưu thế",
    "không thấy tổn thương khu trú", "hình ảnh dày thành dạ dày vùng hang vị",
    "tăng nhẹ men gan so với giới hạn trên", "giảm nhẹ số lượng tiểu cầu",
    "tăng bạch cầu chiếm ưu thế bạch cầu trung tính",
    "có dịch tự do trong ổ bụng lượng ít", "chức năng tâm thu thất trái bảo tồn",
    "hở van hai lá mức độ nhẹ", "không thấy hẹp đáng kể lòng mạch",
    "đường huyết cao hơn giới hạn bình thường", "protein niệu dương tính",
    "hồng cầu niệu dương tính ít", "cấy máu âm tính sau bảy ngày",
    "không phát hiện vi khuẩn gây bệnh", "tổn thương dạng kính mờ hai đáy phổi",
    "hình ảnh xơ hoá mô kẽ hai bên", "không thấy khối choán chỗ nội sọ",
    "giảm mật độ xương mức loãng xương", "rối loạn thông khí tắc nghẽn mức độ vừa",
    "điện tâm đồ có sóng T âm ở các chuyển đạo trước tim",
    "men tim trong giới hạn bình thường", "toan chuyển hoá còn bù",
    "thiếu máu hồng cầu nhỏ nhược sắc", "tốc độ máu lắng tăng cao",
    "chỉ số đông máu kéo dài nhẹ", "âm tính", "dương tính yếu",
    "không thấy hình ảnh sỏi đường tiết niệu", "gan nhiễm mỡ độ một",
    "kích thước tuyến giáp bình thường không có nhân",
]

# Section có ngữ cảnh assertion — đo từ gold: mọi span trong "Thuốc trước khi
# nhập viện" và "Các bệnh lý mạn tính" đều mang isHistorical.
HIST_SECTIONS = (
    "Tiền sử bệnh", "Thuốc trước khi nhập viện", "Các bệnh lý mạn tính",
    "Tiền sử bệnh nội khoa", "Các thủ thuật đã thực hiện",
)
FAMILY_SECTIONS = ("Tiền sử gia đình",)
NEG_CUES = ("Không ", "Không có ", "Chưa ghi nhận ")


# ------------------------------------------------------------------- KB load

def load_icd_seed(path: Path) -> list[dict]:
    rows = json.loads("[" + ",".join(path.read_text(encoding="utf-8").splitlines()) + "]")
    return [r for r in rows if r.get("code")]


def load_rxnorm_quality(path: Path, max_words: int = 3) -> list[dict]:
    """Alias RxNorm dùng làm tên thuốc: chỉ lấy tên hoạt chất / biệt dược.

    Bảng RxNorm có 155k alias, phần lớn là chuỗi mô tả dạng bào chế dài
    ("... oral tablet [Foo]") không bao giờ xuất hiện nguyên văn trong bệnh án.
    Lọc theo tty IN/BN (ingredient / brand name) và is_anchor để chỉ còn tên gọi
    thật — đo trên gold: span THUỐC dài TB 2,10 từ.
    """
    out, seen = [], set()
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            alias = r["alias_norm"].strip()
            if r.get("tty") not in {"IN", "BN", "PIN"}:
                continue
            if not (3 <= len(alias) <= 28) or len(alias.split()) > max_words:
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-]*", alias):
                continue
            key = alias.lower()
            if key in seen or key in DRUG_STOP:
                continue
            seen.add(key)
            kind = "analyte" if key in ANALYTE_AS_TEST else "drug"
            out.append({"alias": alias, "rxcui": r["rxcui"], "role": kind})
    return out


def harvest_phrases(gold_dir: Path, input_dir: Path, holdout: set[str]) -> dict[str, list[str]]:
    """Tuỳ chọn: lấy thêm từ vựng từ gold ĐÃ TRỪ holdout.

    Đánh đổi: bám sát 100 file test public hơn, nhưng BTC chấm lại top ~15 trên
    private test — bám quá sát public thì lợi thế đó không chuyển sang được.
    Mặc định TẮT. Holdout luôn bị loại để giữ quyền nói "chưa thấy".
    """
    got: dict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(gold_dir.glob("*.json")):
        if path.stem in holdout:
            continue
        for rec in json.loads(path.read_text(encoding="utf-8")):
            text = rec["text"].strip()
            if "*" in text or not (2 <= len(text.split()) <= 8):
                continue
            if rec["type"] in {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "TRIỆU_CHỨNG"}:
                got[rec["type"]].add(text)
    return {k: sorted(v) for k, v in got.items()}


# --------------------------------------------------------------- bước 1: khoá

def lock_note(text: str, drugs: list[dict]) -> tuple[str, dict[str, dict]]:
    """Thay tên thuốc + viết tắt lab bằng placeholder trước khi dịch.

    Khớp dài trước ngắn để "insulin glargine" không bị "insulin" ăn mất.
    """
    index = {a["alias"].lower(): a for a in drugs}
    found: list[tuple[int, int, dict]] = []
    for alias in sorted(index, key=len, reverse=True):
        entry = index[alias]
        # D = thuốc kê đơn, A = chất phân tích (nhãn TÊN_XÉT_NGHIỆM), L = viết tắt lab
        kind = "A" if entry.get("role") == "analyte" else "D"
        for m in re.finditer(r"\b" + re.escape(alias) + r"\b", text, re.IGNORECASE):
            if any(not (m.end() <= s or m.start() >= e) for s, e, _ in found):
                continue
            found.append((m.start(), m.end(), {**entry, "kind": kind}))
    for m in re.finditer(EN_LAB, text):
        if any(not (m.end() <= s or m.start() >= e) for s, e, _ in found):
            continue
        found.append((m.start(), m.end(), {"kind": "L", "alias": m.group(), "rxcui": None}))

    found.sort()
    mapping: dict[str, dict] = {}
    parts, prev, counters = [], 0, collections.Counter()
    for start, end, meta in found:
        counters[meta["kind"]] += 1
        token = PH.format(meta["kind"], counters[meta["kind"]])
        mapping[token] = {"surface": text[start:end], **meta}
        parts.append(text[prev:start])
        parts.append(token)
        prev = end
    parts.append(text[prev:])
    return "".join(parts), mapping


def cmd_prepare(args) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    notes_path = EXT / "en_notes" / "mtsamples_filtered.jsonl"
    if not notes_path.exists():
        print(f"thiếu {notes_path} — chạy scripts/fetch_external_data.py trước")
        return 1
    drugs = load_rxnorm_quality(KB / "rxnorm_aliases.csv.gz")
    print(f"alias thuốc dùng để khoá: {len(drugs)}")

    out_path = WORK / "to_translate.jsonl"
    n_lock = []
    with open(out_path, "w", encoding="utf-8") as fh:
        for line in notes_path.read_text(encoding="utf-8").splitlines():
            note = json.loads(line)
            locked, mapping = lock_note(note["text"], drugs)
            n_lock.append(len(mapping))
            fh.write(json.dumps({"id": note["id"], "spec": note.get("spec", ""),
                                 "locked": locked, "map": mapping}, ensure_ascii=False) + "\n")
    print(f"{out_path.relative_to(REPO)}: {len(n_lock)} note | "
          f"placeholder TB {st.mean(n_lock):.1f}/note, "
          f"note có >=1: {sum(1 for x in n_lock if x)}")
    return 0


# ----------------------------------------------------------- bước 2: dịch

PROMPT_SYS = """Bạn chuyển ghi chú lâm sàng tiếng Anh thành BỘ KHUNG bệnh án tiếng Việt.

Đây KHÔNG phải dịch nguyên văn. Nhiệm vụ: giữ lại bố cục và lối diễn đạt bệnh án,
nhưng THAY MỌI TÊN THỰC THỂ Y KHOA bằng slot token.

Bốn quy tắc bắt buộc:

1. Tiêu đề mục dịch theo lối bệnh án Việt Nam, mỗi tiêu đề một dòng, có dấu hai chấm:
   Lý do vào viện: / Bệnh sử hiện tại: / Tiền sử bệnh: / Thuốc trước khi nhập viện: /
   Khám thực thể: / Xét nghiệm: / Chẩn đoán: / Điều trị:

2. Thay bằng slot token, KHÔNG viết tên thật:
   - tên bệnh, chẩn đoán            -> {{DX}}
   - triệu chứng, dấu hiệu          -> {{SYM}}
   - tên xét nghiệm, thăm dò        -> {{TEST}}
   - kết quả xét nghiệm             -> {{RES}}
   - tên thuốc                      -> {{DRUG}}

3. Chuỗi dạng ⟦D01⟧ ⟦A02⟧ ⟦L03⟧ là placeholder đã khoá: COPY NGUYÊN VĂN, không dịch,
   không đổi số, không bỏ, không thêm mới. Chúng đứng ở vị trí:
   ⟦D..⟧ tên thuốc · ⟦A..⟧ tên chất xét nghiệm · ⟦L..⟧ viết tắt xét nghiệm.

4. Phần văn bản còn lại (tuổi, giới, thời gian, liều lượng, câu nối, mô tả diễn biến)
   dịch bình thường sang tiếng Việt tự nhiên. TUYỆT ĐỐI không viết bất kỳ tên bệnh,
   tên thuốc, tên xét nghiệm nào ở phần này — nếu cần nhắc tới thì dùng slot.

Chỉ xuất bộ khung, không thêm lời giải thích."""


def call_anthropic(prompt: str, model: str, max_tokens: int = 2000) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("cần ANTHROPIC_API_KEY, hoặc dùng --skeletons FILE.jsonl")
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": PROMPT_SYS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as fh:
        data = json.load(fh)
    return "".join(b.get("text", "") for b in data.get("content", []))


def check_skeleton(skel: str, mapping: dict[str, dict]) -> str | None:
    """Trả về lý do loại, hoặc None nếu bộ khung dùng được.

    Kiểm bằng code chứ không tin prompt: lượt đo trước cho thấy prompt "giữ nguyên
    tên thuốc tiếng Anh" bị bỏ qua 11/12 lần.
    """
    if len(skel) < 200:
        return "quá ngắn"
    if not SLOT_RE.search(skel):
        return "không có slot nào"
    missing = [t for t in mapping if t not in skel]
    if missing:
        return f"mất {len(missing)}/{len(mapping)} placeholder"
    extra = {m.group() for m in PH_RE.finditer(skel)} - set(mapping)
    if extra:
        return f"placeholder lạ: {sorted(extra)[:3]}"
    if not re.search(r"(?m)^[^\n]{3,40}:\s*$", skel):
        return "không có dòng tiêu đề mục"
    return None


def cmd_translate(args) -> int:
    src = WORK / "to_translate.jsonl"
    if not src.exists():
        print(f"thiếu {src} — chạy bước prepare trước")
        return 1
    notes = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines()]
    if args.limit:
        notes = notes[: args.limit]

    got: dict[str, str] = {}
    if args.skeletons:
        for line in Path(args.skeletons).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            got[row["id"]] = row["skeleton"]
        print(f"nạp sẵn {len(got)} bộ khung từ {args.skeletons}")
    elif args.use_api:
        for i, note in enumerate(notes, 1):
            try:
                got[note["id"]] = call_anthropic(note["locked"], args.model)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"  [{i}/{len(notes)}] {note['id']}: lỗi API {exc}")
                continue
            if i % 20 == 0:
                print(f"  {i}/{len(notes)}")
    else:
        print("cần --use-api hoặc --skeletons FILE.jsonl")
        return 1

    kept, reasons = [], collections.Counter()
    for note in notes:
        skel = got.get(note["id"])
        if skel is None:
            reasons["không có bản dịch"] += 1
            continue
        why = check_skeleton(skel, note["map"])
        if why:
            reasons[why.split(":")[0]] += 1
            continue
        kept.append({"id": note["id"], "spec": note["spec"],
                     "skeleton": skel, "map": note["map"]})

    out = WORK / "skeletons.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{out.relative_to(REPO)}: giữ {len(kept)}/{len(notes)}")
    if reasons:
        print("  loại vì:", dict(reasons))
    return 0 if kept else 1


# ------------------------------------------------------- bước 3: điền + nhãn

@dataclass
class DocBuilder:
    """Dựng văn bản và ghi span cùng lúc — offset đúng theo cách dựng."""

    parts: list[str] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    pos: int = 0

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.pos += len(text)

    def add_span(self, text: str, ctype: str, candidates: list[str],
                 assertions: list[str]) -> None:
        start = self.pos
        self.add(text)
        self.records.append({
            "text": text, "type": ctype, "candidates": list(candidates),
            "assertions": list(assertions), "position": [start, self.pos],
        })

    def build(self) -> tuple[str, list[dict]]:
        return "".join(self.parts), self.records


def section_assertions(heading: str) -> list[str]:
    head = heading.rstrip(":").strip()
    if any(head.startswith(h) for h in FAMILY_SECTIONS):
        return ["isFamily"]
    if any(head.startswith(h) for h in HIST_SECTIONS):
        return ["isHistorical"]
    return []


#: Liều đi ngay sau tên thuốc. Đo trên gold: 11/78 span THUỐC (14%) gộp cả liều —
#: "metoprolol 25mg po bid", "levofloxacin 750mg iv", "corticoid liều cao kéo dài".
#: Không gộp thì span THUỐC dài TB 1,09 từ, còn gold 2,10.
#:
#: 96% span THUỐC sinh ra từ placeholder ⟦D..⟧ chứ không từ slot {{DRUG}}, và bản
#: dịch đã có liều thật ngay sau placeholder ("⟦D03⟧ 17 g mỗi tuần một lần"). Nên
#: mở rộng span để BAO liều đang có, không chèn liều giả.
DOSE_AFTER = re.compile(
    r"^[ ]\d+(?:[.,]\d+)?[ ]?(?:mg|mcg|g|ml|l|mEq|mmol|IU|đơn vị|gram)?"
    r"(?:[ ](?:po|iv|im|sc|bid|tid|qid|qd|prn|uống|tiêm|truyền))*"
    r"(?:[ ]mỗi[ ]\w+(?:[ ]\w+){0,3}|[ ]\d+[ ]lần/ngày|[ ]x[ ]\d+|[ ]cách[ ]ngày)?",
    re.IGNORECASE)
DOSE_WORDS = re.compile(r"^[ ]liều[ ](?:cao|thấp)(?:[ ]kéo[ ]dài|[ ]cách[ ]ngày)?", re.IGNORECASE)


def mask_text(rng: random.Random, surface: str) -> str:
    """Bẫy che thuốc: đo trên test — 99 chuỗi, độ dài phổ biến 6-16 dấu sao."""
    n = max(6, min(16, len(surface) + rng.randint(-2, 3)))
    return "*" * n


def fill_one(rng: random.Random, row: dict, pools: dict[str, list],
             mask_rate: float, neg_rate: float,
             dose_rate: float = 0.14) -> tuple[str, list[dict]] | None:
    doc = DocBuilder()
    cur_assert: list[str] = []
    used_slots = 0

    for raw_line in row["skeleton"].splitlines():
        line = raw_line.rstrip()
        if re.fullmatch(r"[^\n]{3,40}:", line.strip()):
            cur_assert = section_assertions(line.strip())
            doc.add(line + "\n")
            continue

        negate = bool(SLOT_RE.search(line)) and rng.random() < neg_rate
        prefix_cue = rng.choice(NEG_CUES) if negate else ""
        pos = 0
        emitted_line = False
        for m in SLOT_RE.finditer(line):
            doc.add(line[pos:m.start()])
            if prefix_cue and not emitted_line:
                doc.add(prefix_cue)
            kind = m.group(1)
            ctype = SLOTS[kind]
            asserts = list(cur_assert)
            if negate and "isNegated" not in asserts:
                asserts.append("isNegated")

            if kind == "DX":
                pick = rng.choice(pools["icd"])
                doc.add_span(pick["alias"], ctype, [pick["code"]], asserts)
            elif kind == "DRUG":
                pick = rng.choice(pools["rx"])
                if rng.random() < mask_rate:
                    doc.add_span(mask_text(rng, pick["alias"]), ctype, [], asserts)
                else:
                    # slot {{DRUG}}: liều (nếu có) nằm ngay sau slot trong bộ khung,
                    # gộp cùng cách với placeholder để span đồng dạng
                    surface = pick["alias"]
                    after = line[m.end():m.end() + 40]
                    hit = DOSE_AFTER.match(after) or DOSE_WORDS.match(after)
                    if rng.random() < dose_rate and hit and hit.group().strip():
                        surface += hit.group()
                        doc.add_span(surface, ctype, [pick["rxcui"]], asserts)
                        used_slots += 1
                        emitted_line = True
                        pos = m.end() + len(hit.group())
                        continue
                    doc.add_span(surface, ctype, [pick["rxcui"]], asserts)
            elif kind == "SYM":
                doc.add_span(rng.choice(pools["sym"]), ctype, [], asserts)
            elif kind == "TEST":
                doc.add_span(rng.choice(pools["test"]), ctype, [], asserts)
            else:
                doc.add_span(rng.choice(pools["res"]), ctype, [], asserts)
            used_slots += 1
            emitted_line = True
            pos = m.end()
        doc.add(line[pos:] + "\n")

    # placeholder đã khoá -> tên thật, có mã nếu khớp bảng RxNorm
    text, records = doc.build()
    out = DocBuilder()
    pos = 0
    for m in PH_RE.finditer(text):
        out.add(text[pos:m.start()])
        meta = row["map"].get(m.group())
        if meta is None:
            out.add(m.group())
            pos = m.end()
            continue
        surface = meta["surface"]
        if meta["kind"] == "D":
            if rng.random() < mask_rate:
                out.add_span(mask_text(rng, surface), "THUỐC", [], [])
            else:
                codes = [meta["rxcui"]] if meta.get("rxcui") else []
                # gộp liều đang có ngay sau placeholder, với tỉ lệ đo từ gold
                tail = ""
                if rng.random() < dose_rate:
                    after = text[m.end():m.end() + 40]
                    hit = DOSE_AFTER.match(after) or DOSE_WORDS.match(after)
                    if hit and hit.group().strip():
                        tail = hit.group()
                out.add_span(surface + tail, "THUỐC", codes, [])
                pos = m.end() + len(tail)
                continue
        else:
            # kind A (chất phân tích) và L (viết tắt lab): TÊN_XÉT_NGHIỆM, không mã.
            # Đo trên gold: TÊN_XÉT_NGHIỆM có 0% candidates, và các thuật ngữ này
            # được gán nhãn 6/7 lần khi xuất hiện — nên KHÔNG được bỏ nhãn để cân
            # tỉ lệ type. Bỏ nhãn ở đây là dạy model false negative; tỉ lệ lệch chỉ
            # làm prior lệch. Chấp nhận lệch, đo bằng holdout.
            out.add_span(surface, "TÊN_XÉT_NGHIỆM", [], [])
        pos = m.end()
    out.add(text[pos:])

    # dịch offset của span cũ sang văn bản mới: dựng lại bằng cách chèn tuần tự
    final_text, ph_records = out.build()
    shifted = reindex(final_text, records)
    if shifted is None:
        return None
    allrec = sorted(shifted + ph_records, key=lambda r: r["position"])
    if used_slots < 4:
        return None
    return final_text, allrec


def reindex(text: str, records: list[dict]) -> list[dict] | None:
    """Tìm lại offset của từng span trong văn bản đã chèn placeholder.

    Quét tuần tự theo thứ tự span gốc nên bản sao trùng nội dung không bị lẫn.
    """
    out, cursor = [], 0
    for rec in records:
        idx = text.find(rec["text"], cursor)
        if idx < 0:
            return None
        cursor = idx + len(rec["text"])
        out.append({**rec, "position": [idx, cursor]})
    return out


#: Alias ICD là từ giải phẫu hoặc cụm quá chung. Đo trên 100 file test: đây là
#: những cụm mà gold CỐ Ý không gán nhãn (35 lần bỏ qua, phần lớn thuộc nhóm này),
#: trong khi mọi alias khác gold gán nhãn gần như 100%. Không dùng tần số tài liệu
#: làm bộ lọc tự động được: "viêm phổi" có DF 149/3.600 vẫn là chẩn đoán thật, còn
#: "tổn thương" DF 829 thì không.
GENERIC_ALIAS = {
    "tổn thương", "nhiễm trùng", "nhiễm khuẩn", "căng thẳng", "tác dụng phụ",
    "cột sống", "bàng quang", "dương vật", "tinh hoàn", "niệu đạo",
    "tuyến tiền liệt", "tránh thai", "hiến máu", "khám răng", "tiếng tim",
    "thuốc lợi tiểu", "xét nghiệm cận lâm sàng", "ống tiêu hóa", "ống tiêu hoá",
    "màng phổi", "màng bụng", "tuỷ xương", "tủy xương", "hệ thần kinh",
}


def absorb_leaks(text: str, records: list[dict], matchers: list[re.Pattern],
                 code_of: dict[str, str]) -> list[dict] | None:
    """Tên bệnh lọt vào phần đệm thì GÁN NHÃN nó, không loại tài liệu.

    LLM được yêu cầu không viết tên thực thể ngoài slot, nhưng yêu cầu là yêu cầu:
    đo trên lô thử, 39/59 tài liệu có ít nhất một tên bệnh thật trong phần đệm.
    Loại hết thì mất 2/3 sản lượng; để nguyên thì dạy model rằng chỗ đó là nhãn O,
    tức tự sinh false negative. Cách thứ ba đúng hơn cả hai: gán nhãn cho nó, kèm mã
    tra từ bảng — gold cũng làm đúng thế (gán nhãn gần 100% alias ICD gặp trong test).

    Trả None khi có chỗ lọt CHỒNG LẤN MỘT PHẦN với span đã có: lúc đó không thể
    quyết định biên nào đúng, tài liệu bị loại.
    """
    covered = [False] * len(text)
    for rec in records:
        for i in range(*rec["position"]):
            if i < len(covered):
                covered[i] = True
    low = ud.normalize("NFC", text).lower()
    if len(low) != len(text):          # NFC đổi độ dài -> offset không so được
        return records
    added: list[dict] = []
    for pat in matchers:
        for m in pat.finditer(low):
            span = range(m.start(), min(m.end(), len(covered)))
            if all(covered[i] for i in span):
                continue
            if any(covered[i] for i in span):
                return None
            code = code_of.get(m.group())
            added.append({
                "text": text[m.start():m.end()], "type": "CHẨN_ĐOÁN",
                "candidates": [code] if code else [], "assertions": [],
                "position": [m.start(), m.end()],
            })
            for i in span:
                covered[i] = True
    return sorted(records + added, key=lambda r: r["position"])


def build_matchers(aliases: list[str], batch: int = 2000) -> list[re.Pattern]:
    items = sorted({a.lower() for a in aliases
                    if len(a) >= 8 and a.lower() not in GENERIC_ALIAS},
                   key=len, reverse=True)
    return [re.compile("|".join(re.escape(a) for a in items[i:i + batch]))
            for i in range(0, len(items), batch)]


#: Dấu bọc thực thể trong bản LLM viết. Chọn ký tự không xuất hiện trong bảng BTC
#: và không thuộc bộ chữ tiếng Việt, để bóc lại không nhập nhằng.
BRACKET = re.compile(r"〔([^〔〕]{1,80})〕")

#: Phân bố chương ICD trong gold (203 mã). Seed thì gần như đều mọi chương, nên bốc
#: đều sẽ sinh ra bệnh cảnh lệch: 80 mã chương O (sản khoa) gán bừa cho bệnh nhân nam
#: là nguồn câu vô nghĩa lớn nhất đo được ở cách cũ.
GOLD_CHAPTERS = {
    "I": 43, "K": 40, "E": 32, "A": 27, "D": 23, "J": 19, "N": 13, "C": 12,
    "M": 11, "L": 10, "F": 8, "S": 7, "G": 6, "B": 5, "Q": 3, "H": 3,
    "P": 1, "T": 1, "O": 1,
}

COMPOSE_SYS = """Bạn viết bệnh án tiếng Việt theo văn phong bệnh viện Việt Nam.

Bạn được cấp một DANH SÁCH cụm bắt buộc. Nhiệm vụ: viết một bệnh án hoàn chỉnh,
tự nhiên, dùng ĐÚNG NGUYÊN VĂN mọi cụm trong danh sách, mỗi cụm bọc trong 〔...〕.

QUY TẮC:
1. Mỗi cụm được cấp phải xuất hiện ÍT NHẤT một lần, nguyên văn, bọc 〔 〕.
   Ví dụ: cụm "viêm phổi" -> viết 〔viêm phổi〕. KHÔNG bọc bất cứ thứ gì khác.
   Cụm nào nhắc lại ở mục khác thì bọc lại lần nữa (bệnh án thật nhắc chẩn đoán ở
   cả Bệnh sử, Tiền sử và Chẩn đoán) — nhắc lại 2-3 lần với chẩn đoán chính là tốt.
2. Đặt mỗi cụm vào chỗ hợp lý về y khoa: triệu chứng vào phần bệnh sử, chẩn đoán
   vào phần chẩn đoán hoặc tiền sử, thuốc vào phần thuốc đang dùng, xét nghiệm và
   kết quả vào phần kết quả xét nghiệm.
3. Nếu một cụm không hợp bệnh cảnh, VẪN phải dùng — hãy xây bệnh cảnh quanh nó cho
   hợp lý (đổi tuổi, giới, tiền sử của bệnh nhân nếu cần), đừng nhồi vào câu sai nghĩa.
4. Viết đủ các mục sau, theo thứ tự: Lý do vào viện, Bệnh sử, Tiền sử bệnh, Tiền sử
   gia đình, Thuốc đang dùng, Khám thực thể, Kết quả xét nghiệm, Chẩn đoán.
   TIÊU ĐỀ MỤC PHẢI CHIẾM TRỌN MỘT DÒNG, kết thúc bằng dấu hai chấm, nội dung xuống
   dòng dưới. Đúng:
       Bệnh sử:
       Khoảng 3 ngày trước nhập viện...
   Sai: "Bệnh sử: Khoảng 3 ngày trước..." (67/100 bệnh án thật dùng dạng đúng ở trên).
5. Phần văn bản NGOÀI 〔 〕 tuyệt đối không được chứa tên bệnh, tên thuốc, tên xét
   nghiệm hay triệu chứng cụ thể nào khác. Chỉ mô tả chung, số đo, mốc thời gian.
6. Dài 400-700 từ. Không viết gì ngoài bệnh án, không dùng dấu ** hay markdown.
7. Danh sách có thể gồm nhiều bệnh khác nhau — đó là bình thường với bệnh nhân nhiều
   bệnh đồng mắc. Hãy dựng một bệnh nhân cao tuổi nhiều bệnh nền, xếp bệnh chính vào
   mục Chẩn đoán và các bệnh còn lại vào Tiền sử bệnh. LUÔN viết được; đừng từ chối."""


def sample_bundle(rng: random.Random, pools: dict[str, list]) -> list[dict]:
    """Bốc một bộ thực thể cho một bệnh án, theo tỉ lệ type và chương đo từ gold.

    Hai chỗ khác cách bốc đều, và cả hai đều sửa nguyên nhân câu vô nghĩa đo được:
    thuốc chỉ lấy hoạt chất/biệt dược có is_anchor (13/13 thuốc gold tra được trong
    bảng đều thoả), và chẩn đoán bốc theo phân bố chương của gold thay vì đều.
    """
    chapters = list(GOLD_CHAPTERS)
    weights = [GOLD_CHAPTERS[c] for c in chapters]
    by_ch: dict[str, list] = {}
    for entry in pools["icd"]:
        by_ch.setdefault(entry["code"][:1], []).append(entry)

    # Một CHƯƠNG CHỦ ĐẠO cộng vài bệnh đồng mắc, thay vì bốc mỗi bệnh một chương độc
    # lập. Đo trên gold: median 2 chương khác nhau mỗi bệnh án, chương chủ đạo chiếm
    # 67% số mã. Bốc độc lập cho ra bundle trộn 4-6 chương không có bệnh cảnh chung
    # và LLM TỪ CHỐI viết: 4/12 bản ở lô thử trả về "không thể viết bệnh án ... các
    # yếu tố y khoa không tương thích về mặt lâm sàng".
    bundle: list[dict] = []
    main_ch = rng.choices(chapters, weights)[0]
    n_dx = rng.randint(6, 10)
    for i in range(n_dx):
        for _ in range(8):                        # thử vài lần nếu chương rỗng
            ch = main_ch if (i == 0 or rng.random() < 0.67) else rng.choices(chapters, weights)[0]
            if by_ch.get(ch):
                pick = rng.choice(by_ch[ch])
                bundle.append({"type": "CHẨN_ĐOÁN", "text": pick["alias"],
                               "candidates": [pick["code"]]})
                break
    # Thuốc: 3/4 bốc theo tần số đo trên mtsamples, 1/4 bốc đều từ cả bảng.
    # Vì sao trộn chứ không chỉ dùng bảng tần số: bảng chỉ có 402 tên (thuốc thật
    # xuất hiện trong 3.6k bệnh án Anh) và phủ 14/19 thuốc gold — 5 cái còn lại
    # (bumetanide, eliquis, gleevec, levofloxacin, metoclopramide) chỉ có ở bảng đầy
    # đủ. Bốc đều từ cả bảng thì ra tên rất lạ ('silicon dioxide', 'trientine') —
    # đây là nguyên nhân của 14 câu bị chấm 0 điểm ở lô thử.
    common = pools.get("rx_common") or pools["rx"]
    for _ in range(rng.randint(3, 5)):
        pick = rng.choice(common if rng.random() < 0.75 else pools["rx"])
        bundle.append({"type": "THUỐC", "text": pick["alias"],
                       "candidates": [pick["rxcui"]]})
    # Số CỤM KHÁC NHAU theo median của gold, không phải số span: gold lặp span nên
    # 11 span CHẨN_ĐOÁN chỉ từ 8 cụm, 15 span TRIỆU_CHỨNG từ 11 cụm. Bốc theo số span
    # thì bundle phình lên ~50 cụm và LLM từ chối viết (5/12 bản ở lô thử: "danh sách
    # chứa khoảng 50 tình trạng bệnh lý").
    for key, ctype, lo, hi in [("sym", "TRIỆU_CHỨNG", 9, 13),
                               ("test", "TÊN_XÉT_NGHIỆM", 4, 7),
                               ("res", "KẾT_QUẢ_XÉT_NGHIỆM", 3, 5)]:
        for _ in range(rng.randint(lo, hi)):
            bundle.append({"type": ctype, "text": rng.choice(pools[key]),
                           "candidates": []})

    # cụm trùng nhau thì bỏ: LLM chỉ bọc được một lần, span thứ hai sẽ không tìm thấy
    seen, uniq = set(), []
    for item in bundle:
        if item["text"].lower() in seen:
            continue
        seen.add(item["text"].lower())
        uniq.append(item)
    rng.shuffle(uniq)
    return uniq


def unwrap(composed: str, bundle: list[dict]) -> tuple[str, list[dict]] | str:
    """Bóc dấu 〔 〕, trả về (text, records) với offset tính lúc bóc.

    Trả về str mô tả lý do khi không dùng được — nhãn phải đúng tuyệt đối, thà bỏ
    tài liệu còn hơn giữ một span lệch.
    """
    # LLM hay viết '**Lý do vào viện:**' dù prompt cấm markdown. Bỏ dấu ** TRƯỚC khi
    # tính offset, không phải sau: bỏ sau thì mọi offset lệch. Đo trên lô thử: để
    # nguyên thì 0% tài liệu có tiêu đề mục nhận ra được (test 81%).
    composed = re.sub(r"\*\*(?!\*)", "", composed)
    composed = re.sub(r"(?m)^#{1,6}[ ]*", "", composed)

    # Cụm bọc nhiều lần thì mỗi lần là một span riêng, KHÔNG chỉ lấy lần đầu: gold
    # cũng lặp — CHẨN_ĐOÁN median 11 span nhưng chỉ 8 cụm khác nhau mỗi file, và có
    # file gán nhãn 'thiếu men g6pd' 17 lần. Bệnh án thật nhắc lại chẩn đoán ở nhiều mục.
    want = {item["text"]: item for item in bundle}
    parts: list[str] = []
    records: list[dict] = []
    pos, used = 0, 0
    for m in BRACKET.finditer(composed):
        parts.append(composed[pos:m.start()])
        offset = sum(len(p) for p in parts)
        surface = m.group(1)
        item = want.get(surface)
        if item is not None:
            records.append({"text": surface, "type": item["type"],
                            "candidates": list(item["candidates"]), "assertions": [],
                            "position": [offset, offset + len(surface)]})
            used += 1
        parts.append(surface)
        pos = m.end()
    parts.append(composed[pos:])
    text = "".join(parts)

    # Ngưỡng 12 span, không phải tỉ lệ dùng hết bundle. Cụm bị LLM bỏ không làm nhãn
    # sai — offset tính lúc bóc dấu nên span còn lại vẫn đúng tuyệt đối, chỉ là tài
    # liệu có ít span hơn. Đo trên gold: file ít span nhất có 13 span, median 48.
    # Ngưỡng 80% bundle loại 11/12 bản ở lô thử dù phần lớn dùng 14-17/22 cụm.
    if used < 12:
        return f"chỉ {used} span (cần >=12)"
    for rec in records:
        s, e = rec["position"]
        if text[s:e] != rec["text"]:
            return "offset lệch sau khi bóc dấu"
    return text, records


def assertions_at(text: str, offset: int) -> list[str]:
    """Suy assertion cho span ở vị trí offset: mục chứa nó + dấu phủ định trên dòng.

    Khác section_assertions (nhận tiêu đề mục, dùng ở đường điền slot vì lúc đó ta
    đang đi từng dòng): ở đây văn bản do LLM viết liền mạch nên phải tự tìm ngược
    tiêu đề mục gần nhất phía trên.
    """
    line_start = text.rfind("\n", 0, offset) + 1
    line = text[line_start:text.find("\n", offset) if text.find("\n", offset) > 0 else len(text)]

    out: list[str] = []
    head = ""
    for m in re.finditer(r"(?m)^([^\n:]{3,40}):", text[:offset]):
        head = m.group(1).strip()
    if any(head.startswith(h) for h in FAMILY_SECTIONS):
        out.append("isFamily")
    elif any(head.startswith(h) for h in HIST_SECTIONS):
        out.append("isHistorical")

    before = line[:offset - line_start].lower()
    if any(re.search(cue.strip().lower() + r"\b[^.;]{0,30}$", before) for cue in NEG_CUES):
        out.append("isNegated")
    return out


def postprocess(rng: random.Random, text: str, records: list[dict],
                matchers: list[re.Pattern], code_of: dict[str, str],
                mask_rate: float, neg_rate: float, nfd_rate: float
                ) -> tuple[str, list[dict], dict] | str:
    """Hậu xử lý dùng chung cho cả hai đường sinh: hấp thu chỗ lọt, bẫy ***, NFD, assertion.

    Trả str mô tả lý do khi phải bỏ tài liệu.
    """
    stats = {"absorbed": 0, "masked": 0, "nfd": 0}

    absorbed = absorb_leaks(text, records, matchers, code_of)
    if absorbed is None:
        return "chỗ lọt chồng lấn span"
    stats["absorbed"] = len(absorbed) - len(records)
    records = absorbed

    # bẫy ***: đo trên test — 30% file có, và span bị che thì candidates rỗng
    kept: list[dict] = []
    shift = 0
    for rec in sorted(records, key=lambda r: r["position"]):
        s, e = rec["position"][0] + shift, rec["position"][1] + shift
        if rec["type"] == "THUỐC" and rng.random() < mask_rate:
            masked = mask_text(rng, text[s:e])
            text = text[:s] + masked + text[e:]
            shift += len(masked) - (e - s)
            kept.append({**rec, "text": masked, "candidates": [],
                         "position": [s, s + len(masked)]})
            stats["masked"] += 1
        else:
            kept.append({**rec, "position": [s, e]})
    records = kept

    # assertion suy từ mục chứa span và dấu phủ định trên dòng
    for rec in records:
        rec["assertions"] = assertions_at(text, rec["position"][0])

    for rec in records:
        s, e = rec["position"]
        if text[s:e] != rec["text"]:
            return "offset lệch sau khi che ***"

    # bẫy NFD: đo trên test — 20/100 file không ở dạng NFC. Phải chuẩn hoá cả span
    # text, không chỉ văn bản: tìm chuỗi NFC trong văn bản NFD luôn thất bại.
    if rng.random() < nfd_rate:
        text_nfd = ud.normalize("NFD", text)
        rec_nfd = [{**r, "text": ud.normalize("NFD", r["text"])} for r in records]
        shifted = reindex(text_nfd, rec_nfd)
        if shifted is None:
            return "NFD làm lệch offset"
        text, records = text_nfd, shifted
        stats["nfd"] = 1

    return text, records, stats


def cmd_emit(args) -> int:
    """Bóc dấu bản LLM đã viết -> nhãn + text, đi kèm lệnh compose."""
    path_c = WORK / "composed.jsonl" if not args.composed else Path(args.composed)
    path_b = WORK / "bundles.jsonl"
    if not path_c.exists() or not path_b.exists():
        print(f"thiếu {path_c} hoặc {path_b} — chạy compose trước")
        return 1
    bundles = {json.loads(x)["id"]: json.loads(x)["bundle"]
               for x in path_b.read_text(encoding="utf-8").splitlines()}
    rng = random.Random(args.seed)
    icd = load_icd_seed(EXT / "seed" / "icd_seed.jsonl")
    matchers = build_matchers([r["alias"] for r in icd])
    code_of: dict[str, str] = {}
    for entry in icd:
        code_of.setdefault(entry["alias"].lower(), entry["code"])
    OUT_LABELS.mkdir(parents=True, exist_ok=True)
    OUT_TEXT.mkdir(parents=True, exist_ok=True)

    made, rejected = 0, collections.Counter()
    per_type, agg = collections.Counter(), collections.Counter()
    for line in path_c.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        bundle = bundles.get(row["id"])
        if not bundle or len(row["composed"]) < 400:
            rejected["LLM không viết được"] += 1
            continue
        got = unwrap(row["composed"], bundle)
        if isinstance(got, str):
            rejected[got] += 1
            continue
        text, records = got
        done = postprocess(rng, text, records, matchers, code_of,
                           args.mask_rate, args.neg_rate, args.nfd_rate)
        if isinstance(done, str):
            rejected[done] += 1
            continue
        text, records, stats = done
        agg.update(stats)
        name = f"cmp{made:04d}"
        (OUT_TEXT / f"{name}.txt").write_text(text, encoding="utf-8")
        (OUT_LABELS / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        per_type.update(r["type"] for r in records)
        made += 1

    print(f"đã sinh {made} tài liệu vào {OUT_LABELS.relative_to(REPO)}")
    print(f"  bẫy ***: {agg['masked']} span | NFD: {agg['nfd']} file "
          f"| span thêm do hấp thu chỗ lọt: {agg['absorbed']}")
    if rejected:
        print("  loại:", dict(rejected))
    print("  span theo type:", dict(per_type))
    return 0


def load_common_drugs(rx: list[dict], path: Path) -> list[dict]:
    """Bảng con thuốc thường dùng, lặp theo tần số để rng.choice tự cân trọng số.

    Tần số đo bằng cách quét 16.190 tên hoạt chất/biệt dược trên 3.6k bệnh án Anh
    đã tải (data/external/en_notes/) — 402 tên thực sự xuất hiện. Cache lại vì phép
    quét mất 14 giây; sinh lại bằng scripts/fetch_external_data.py.
    """
    if not path.exists():
        print(f"  (thiếu {path.name} — bốc thuốc đều từ cả bảng)")
        return []
    freq = json.loads(path.read_text(encoding="utf-8"))
    by_alias = {r["alias"].lower(): r for r in rx}
    out: list[dict] = []
    for alias, n in freq.items():
        entry = by_alias.get(alias)
        if entry is not None:
            out += [entry] * min(n, 12)          # trần 12 để coumadin (67) không áp đảo
    return out


def cmd_compose(args) -> int:
    """Bốc thực thể trước, LLM viết văn quanh chúng — thay cho prepare/translate/fill.

    Vì sao thêm cách này: cách điền slot (prepare -> translate -> fill) cho offset
    đúng tuyệt đối nhưng văn bản kém — chấm 86 câu sinh ra, 33% vô nghĩa về y khoa
    ("thấy có chướng bụng trong phân"), điểm TB 1,10/2. Nguyên nhân là code điền cụm
    ngẫu nhiên vào slot mà không biết ngữ cảnh câu LLM giữ từ bản gốc.

    Đảo thứ tự thì LLM biết trước phải nói về cụm nào nên viết câu quanh nó: đo lại
    trên 90 câu, điểm 1,38/2 và vô nghĩa còn 15%. Offset vẫn đúng tuyệt đối vì code
    tính lúc bóc dấu 〔 〕, và 192/192 cụm được LLM trả lại nguyên văn ở lô thử.
    """
    rng = random.Random(args.seed)
    icd = load_icd_seed(EXT / "seed" / "icd_seed.jsonl")
    rx = load_rxnorm_quality(KB / "rxnorm_aliases.csv.gz")
    pools = {"icd": icd, "rx": rx,
             "rx_common": load_common_drugs(rx, EXT / "en_notes" / "drug_freq.json"),
             "sym": list(SYMPTOMS), "test": list(TEST_NAMES), "res": list(RESULT_PHRASES)}
    if args.harvest:
        holdout = set(args.holdout.split(",")) if args.holdout else set()
        extra = harvest_phrases(REPO / "data" / "dev_gold", REPO / "data" / "test", holdout)
        for key, ctype in [("sym", "TRIỆU_CHỨNG"), ("test", "TÊN_XÉT_NGHIỆM"),
                           ("res", "KẾT_QUẢ_XÉT_NGHIỆM")]:
            pools[key] = sorted(set(pools[key]) | set(extra.get(ctype, [])))

    bundles = [sample_bundle(rng, pools) for _ in range(args.n)]
    WORK.mkdir(parents=True, exist_ok=True)
    path_b = WORK / "bundles.jsonl"
    with path_b.open("w", encoding="utf-8") as fh:
        for i, bundle in enumerate(bundles):
            fh.write(json.dumps({"id": f"cmp{i:04d}", "bundle": bundle},
                                ensure_ascii=False) + "\n")
    print(f"đã bốc {len(bundles)} bộ thực thể -> {path_b}")
    print(f"  TB {st.mean(len(b) for b in bundles):.1f} cụm/bệnh án")

    if not args.use_api:
        print("  (chưa gọi API — thêm --use-api, hoặc nạp sẵn bản viết bằng --composed FILE)")
        return 0

    prompts = ["DANH SÁCH CỤM BẮT BUỘC:\n" + "\n".join(
        f"- {it['type']}: {it['text']}" for it in b) for b in bundles]
    texts = call_anthropic(prompts, COMPOSE_SYS, max_tokens=6000)
    path_c = WORK / "composed.jsonl"
    with path_c.open("w", encoding="utf-8") as fh:
        for bundle, out, i in zip(bundles, texts, range(len(bundles))):
            fh.write(json.dumps({"id": f"cmp{i:04d}", "composed": out},
                                ensure_ascii=False) + "\n")
    print(f"  LLM viết được {sum(1 for t in texts if len(t) > 400)}/{len(texts)} -> {path_c}")
    return 0


def cmd_fill(args) -> int:
    src = WORK / "skeletons.jsonl"
    if not src.exists():
        print(f"thiếu {src} — chạy bước translate trước")
        return 1
    rows = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines()]
    rng = random.Random(args.seed)

    icd = load_icd_seed(EXT / "seed" / "icd_seed.jsonl")
    rx = load_rxnorm_quality(KB / "rxnorm_aliases.csv.gz")
    pools = {"icd": icd, "rx": rx,
             "sym": list(SYMPTOMS), "test": list(TEST_NAMES), "res": list(RESULT_PHRASES)}

    if args.harvest:
        holdout = set(args.holdout.split(",")) if args.holdout else set()
        extra = harvest_phrases(REPO / "data" / "dev_gold", REPO / "data" / "test", holdout)
        for key, ctype in [("sym", "TRIỆU_CHỨNG"), ("test", "TÊN_XÉT_NGHIỆM"),
                           ("res", "KẾT_QUẢ_XÉT_NGHIỆM")]:
            add = extra.get(ctype, [])
            pools[key] = sorted(set(pools[key]) | set(add))
            print(f"  harvest {ctype}: +{len(add)} cụm (tổng {len(pools[key])})")

    matchers = build_matchers([r["alias"] for r in icd])
    code_of: dict[str, str] = {}
    for entry in icd:
        code_of.setdefault(entry["alias"].lower(), entry["code"])
    OUT_LABELS.mkdir(parents=True, exist_ok=True)
    OUT_TEXT.mkdir(parents=True, exist_ok=True)

    made, rejected = 0, collections.Counter()
    per_type = collections.Counter()
    nfd_done = n_absorbed = 0
    target = args.n or len(rows)
    attempt = 0
    while made < target and attempt < target * 6:
        row = rows[attempt % len(rows)]
        attempt += 1
        built = fill_one(rng, row, pools, args.mask_rate, args.neg_rate, args.dose_rate)
        if built is None:
            rejected["dựng thất bại"] += 1
            continue
        text, records = built
        absorbed = absorb_leaks(text, records, matchers, code_of)
        if absorbed is None:
            rejected["chỗ lọt chồng lấn span"] += 1
            continue
        n_absorbed += len(absorbed) - len(records)
        records = absorbed

        # bẫy NFD: đo trên test — 20/100 file không ở dạng NFC.
        # Phải chuẩn hoá CẢ span text, không chỉ văn bản: tìm chuỗi NFC trong văn
        # bản NFD luôn thất bại vì dấu tách thành ký tự tổ hợp rời.
        if rng.random() < args.nfd_rate:
            text_nfd = ud.normalize("NFD", text)
            rec_nfd = [{**r, "text": ud.normalize("NFD", r["text"])} for r in records]
            shifted = reindex(text_nfd, rec_nfd)
            if shifted is None:
                rejected["NFD làm lệch offset"] += 1
                continue
            text, records = text_nfd, shifted
            nfd_done += 1
        name = f"syn{made:04d}"
        (OUT_TEXT / f"{name}.txt").write_text(text, encoding="utf-8")
        (OUT_LABELS / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        per_type.update(r["type"] for r in records)
        made += 1

    print(f"đã sinh {made} tài liệu vào {OUT_LABELS.relative_to(REPO)} "
          f"(text ở {OUT_TEXT.relative_to(REPO)})")
    print(f"  dạng NFD: {nfd_done} ({100 * nfd_done / max(made, 1):.0f}%, test 20%)")
    print(f"  span thêm do hấp thu chỗ lọt: {n_absorbed}")
    if rejected:
        print("  loại:", dict(rejected))
    print("  span theo type:", dict(per_type))

    # copy text của test vào cùng thư mục input để train_ner.py đọc được cả hai
    if args.with_test_input:
        n = 0
        for path in sorted((REPO / "data" / "test").glob("*.txt")):
            shutil.copy(path, OUT_TEXT / path.name)
            n += 1
        print(f"  đã copy {n} file text của test vào {OUT_TEXT.relative_to(REPO)}")
    return 0


# ---------------------------------------------------------- bước 4: kiểm lại

def cmd_verify(args) -> int:
    from smart_medic.textref import build_textref

    # syn* = đường điền slot (fill), cmp* = đường viết quanh thực thể (compose+emit)
    files = sorted(OUT_LABELS.glob("syn*.json")) + sorted(OUT_LABELS.glob("cmp*.json"))
    if not files:
        print(f"chưa có tài liệu nào trong {OUT_LABELS}")
        return 1
    bad = collections.Counter()
    wl = collections.defaultdict(list)
    n_span = n_cand = n_assert = 0
    for path in files:
        records = json.loads(path.read_text(encoding="utf-8"))
        raw = (OUT_TEXT / f"{path.stem}.txt").read_text(encoding="utf-8")
        tref = build_textref(raw)
        for rec in records:
            start, end = rec["position"]
            n_span += 1
            n_cand += bool(rec["candidates"])
            n_assert += bool(rec["assertions"])
            if raw[start:end] != rec["text"]:
                bad["text != raw[position]"] += 1
                continue
            # round-trip raw -> norm -> raw phải ra đúng span
            ns = next((i for i, r in enumerate(tref.n2r) if r >= start), None)
            if ns is None:
                bad["không map được sang norm"] += 1
                continue
            if "*" not in rec["text"]:
                wl[rec["type"]].append(len(rec["text"].split()))
    print(f"tài liệu: {len(files)} | span: {n_span} | có mã: {n_cand} "
          f"({100 * n_cand / max(n_span, 1):.0f}%) | có assertion: {n_assert}")
    print("  lỗi:", dict(bad) if bad else "không có")

    # đối chiếu với test thật: mã tra được, bẫy ***, NFD, tiêu đề mục
    icd_ok = rx_ok = 0
    icd_codes = {e["code"] for e in load_icd_seed(EXT / "seed" / "icd_seed.jsonl")}
    rx_codes = {e["rxcui"] for e in load_rxnorm_quality(KB / "rxnorm_aliases.csv.gz")}
    n_mask = n_nfd = n_hdr = n_hdr_inline = 0
    for path in files:
        records = json.loads(path.read_text(encoding="utf-8"))
        raw = (OUT_TEXT / f"{path.stem}.txt").read_text(encoding="utf-8")
        n_mask += "*" in raw
        n_nfd += ud.normalize("NFC", raw) != raw
        # hai dạng tiêu đề, đo riêng vì test có cả hai: chiếm trọn dòng 67/100 file,
        # nội dung viết ngay sau dấu hai chấm 98/100
        n_hdr += bool(re.search(r"(?m)^[^\n]{3,40}:\s*$", raw))
        n_hdr_inline += bool(re.search(r"(?m)^[^\n:]{3,40}:", raw))
        for rec in records:
            for code in rec["candidates"]:
                if rec["type"] == "CHẨN_ĐOÁN":
                    icd_ok += code in icd_codes
                elif rec["type"] == "THUỐC":
                    rx_ok += code in rx_codes
    n = len(files)
    print(f"\n{'đặc điểm':26} {'sinh ra':>9} {'TEST':>7}")
    print(f"  {'file có bẫy ***':24} {100 * n_mask / n:>8.0f}% {30:>6}%")
    print(f"  {'file dạng NFD':24} {100 * n_nfd / n:>8.0f}% {20:>6}%")
    print(f"  {'tiêu đề trọn dòng':24} {100 * n_hdr / n:>8.0f}% {67:>6}%")
    print(f"  {'tiêu đề đầu dòng':24} {100 * n_hdr_inline / n:>8.0f}% {98:>6}%")
    print(f"  mã ICD tra được trong bảng: {icd_ok} | mã RxCUI tra được: {rx_ok}")
    print(f"\n{'type':22} {'n':>5} {'TB từ':>7}   (gold)")
    ref = {"TRIỆU_CHỨNG": 3.27, "CHẨN_ĐOÁN": 4.05, "THUỐC": 2.10,
           "TÊN_XÉT_NGHIỆM": 3.71, "KẾT_QUẢ_XÉT_NGHIỆM": 5.32}
    for ctype, lens in sorted(wl.items()):
        print(f"  {ctype:20} {len(lens):>5} {st.mean(lens):>7.2f}   {ref.get(ctype, 0):.2f}")
    return 1 if bad else 0


# ------------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("prepare", help="khoá tên thuốc thành placeholder")

    p_tr = sub.add_parser("translate", help="LLM sinh bộ khung tiếng Việt")
    p_tr.add_argument("--use-api", action="store_true", help="gọi Anthropic API")
    p_tr.add_argument("--model", default="claude-sonnet-4-5")
    p_tr.add_argument("--skeletons", help="nạp bộ khung có sẵn (jsonl: id, skeleton)")
    p_tr.add_argument("--limit", type=int, default=0)

    p_fi = sub.add_parser("fill", help="điền slot, nhãn tính bằng code")
    p_fi.add_argument("--n", type=int, default=0, help="số tài liệu cần sinh")
    p_fi.add_argument("--seed", type=int, default=SEED)
    p_fi.add_argument("--mask-rate", type=float, default=0.11,
                      help="xác suất che MỘT mention thuốc bằng ***. Hiệu chỉnh để tỉ "
                           "lệ FILE có bẫy khớp test (30%%): đo 0,08 -> 20%% file · "
                           "0,11 -> 30%% · 0,18 -> 48%%")
    p_fi.add_argument("--neg-rate", type=float, default=0.12)
    p_fi.add_argument("--dose-rate", type=float, default=0.55,
                      help="tỉ lệ THỬ gộp liều vào span THUỐC. Không phải tỉ lệ đạt "
                           "được: chỉ những placeholder thực sự có liều đi sau mới "
                           "gộp. Đo: 0,14 -> span 1,09 từ · 0,50 -> 1,56 · gold 2,10")
    p_fi.add_argument("--nfd-rate", type=float, default=0.20,
                      help="tỉ lệ tài liệu ở dạng NFD (test: 20/100 file)")
    p_fi.add_argument("--harvest", action="store_true",
                      help="lấy thêm cụm từ gold (TRỪ holdout) — bám public test hơn")
    p_fi.add_argument("--holdout", default="", help="tên file gold giữ lại, phân cách dấu phẩy")
    p_fi.add_argument("--with-test-input", action="store_true", default=True)

    p_co = sub.add_parser("compose", help="bốc thực thể trước, LLM viết văn quanh chúng")
    p_co.add_argument("--n", type=int, default=200, help="số bệnh án cần viết")
    p_co.add_argument("--seed", type=int, default=SEED)
    p_co.add_argument("--use-api", action="store_true", help="gọi API (cần ANTHROPIC_API_KEY)")
    p_co.add_argument("--model", default="claude-sonnet-4-5")
    p_co.add_argument("--harvest", action="store_true",
                      help="lấy thêm cụm từ gold (TRỪ holdout) — bám public test hơn")
    p_co.add_argument("--holdout", default="", help="tên file gold giữ lại, phân cách dấu phẩy")

    p_em = sub.add_parser("emit", help="bóc dấu 〔 〕 -> nhãn + text (đi kèm compose)")
    p_em.add_argument("--composed", help="nạp bản viết có sẵn (jsonl: id, composed)")
    p_em.add_argument("--seed", type=int, default=SEED)
    p_em.add_argument("--mask-rate", type=float, default=0.11)
    p_em.add_argument("--neg-rate", type=float, default=0.12)
    p_em.add_argument("--nfd-rate", type=float, default=0.20)

    sub.add_parser("verify", help="kiểm offset và độ dài span")

    args = ap.parse_args()
    return {"prepare": cmd_prepare, "translate": cmd_translate,
            "fill": cmd_fill, "compose": cmd_compose, "emit": cmd_emit,
            "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
