#!/usr/bin/env python3
"""Tải và lọc ba nguồn dữ liệu ngoài cho smart-medic.

Nguồn 1: seed alias từ bảng ICD10/RxNorm của BTC (data/kb) — nhãn tính bằng code.
Nguồn 2: bệnh án tiếng Anh mtsamples (Apache-2.0) — để dịch sang tiếng Việt.
Nguồn 3: ba corpus y khoa tiếng Việt (MIT / Apache-2.0) — phủ cách nói dân gian.

License từng nguồn: xem data/external/README.md. Mọi nguồn đều redistribute được,
vì PRD §5 bắt nộp kèm dữ liệu nhóm sử dụng cho top ~15.

Chạy:  python scripts/fetch_external_data.py [--skip-download]
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import random
import re
import statistics as st
import unicodedata as ud
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KB = REPO / "data" / "kb"
EXT = REPO / "data" / "external"
RAW = EXT / "raw"
SEED = 20260727

# dataset -> số shard parquet cần tải
DATASETS = {
    "mtsamples": ("harishnair04/mtsamples", 1),
    "augmented_clinical": ("AGBonnet/augmented-clinical-notes", 1),
    "vi_medtext": ("baonguyenhuy/VietnameseMedicalText", 1),
    "vi_health_blog": ("ai-enthusiasm-community/vietnamese_health_dataset", 1),
    "vi_medqa": ("hungnm/vietnamese-medical-qa", 1),
}

# chữ ký section của bệnh án Mỹ — mtsamples dùng "SUBJECTIVE:," không phải đầu dòng
EN_HDR = (
    r"(?i)\b(SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN|HISTORY OF PRESENT ILLNESS"
    r"|PAST MEDICAL HISTORY|CURRENT MEDICATIONS|MEDICATIONS|ALLERGIES|LABORATORY DATA"
    r"|LABORATORY|PHYSICAL EXAMINATION|DIAGNOSIS|CHIEF COMPLAINT|FAMILY HISTORY"
    r"|SOCIAL HISTORY|REVIEW OF SYSTEMS|IMPRESSION|RECOMMENDATIONS)\s*:"
)
EN_LAB = (
    r"\b(WBC|RBC|HGB|HCT|PLT|NEUT|LYMPH|MCV|MCH|AST|ALT|GOT|GPT|CRP|HbA1c|BUN"
    r"|LDL|HDL|TSH|CEA|ESR|INR|creatinine|glucose|sodium|potassium)\b"
)
EN_DOSE = r"(?i)\b\d+\s*(mg|mcg|g|ml|units?)\b"


def parquet_urls(dataset: str) -> list[str]:
    url = "https://datasets-server.huggingface.co/parquet?" + urllib.parse.urlencode(
        {"dataset": dataset}
    )
    with urllib.request.urlopen(url, timeout=60) as fh:
        meta = json.load(fh)
    return [f["url"] for f in meta.get("parquet_files", [])]


def download(skip: bool = False) -> dict[str, list[Path]]:
    RAW.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[Path]] = {}
    for name, (dataset, nshard) in DATASETS.items():
        paths = []
        for i in range(nshard):
            dst = RAW / f"{name}_{i:03d}.parquet"
            if not dst.exists():
                if skip:
                    raise SystemExit(f"thiếu {dst} — bỏ --skip-download để tải")
                urls = parquet_urls(dataset)
                urllib.request.urlretrieve(urls[i], dst)
            paths.append(dst)
            print(f"  {name:20} shard{i} {dst.stat().st_size / 1e6:>7.1f} MB")
        out[name] = paths
    return out


def load_alias(path: Path, code_col: str, min_words: int, max_words: int,
               min_len: int = 6, max_len: int = 10**6) -> list[dict]:
    """Đọc bảng alias của BTC, giữ alias trong dải độ dài khớp gold."""
    seen: set[str] = set()
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            alias = ud.normalize("NFC", r["alias_norm"]).strip()
            nw = len(alias.split())
            if not (min_words <= nw <= max_words):
                continue
            if not (min_len <= len(alias) <= max_len):
                continue
            key = alias.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"alias": alias, "code": r.get(code_col) or r.get("code"),
                         "n_words": nw, "kind": path.stem.split("_")[0].upper()})
    return rows


def build_seed() -> tuple[list[dict], list[dict]]:
    """Nguồn 1 — alias 2-5 từ khớp dải độ dài gold (3,53 từ), nhãn tính bằng code."""
    icd = load_alias(KB / "icd10_aliases.csv.gz", "code", 2, 5)
    rx = load_alias(KB / "rxnorm_aliases.csv.gz", "rxcui", 1, 5, min_len=4, max_len=40)
    return icd, rx


def build_icd_matchers(icd_rows: list[dict], batch: int = 2000) -> list[re.Pattern]:
    """Alternation theo lô — 15k alias trong một regex thì compile rất chậm."""
    aliases = sorted((r["alias"].lower() for r in icd_rows), key=len, reverse=True)
    return [
        re.compile("|".join(re.escape(a) for a in aliases[i:i + batch]))
        for i in range(0, len(aliases), batch)
    ]


def count_icd(text: str, matchers: list[re.Pattern]) -> int:
    low = ud.normalize("NFC", text).lower()
    return sum(len(set(p.findall(low))) for p in matchers)


def filter_mtsamples(path: Path, per_spec: int = 40) -> list[dict]:
    """Nguồn 2 — note 700-3000 ký tự, >=3 section, ưu tiên giàu viết tắt lab."""
    import pyarrow.parquet as pq

    tbl = pq.read_table(path)
    kept: list[dict] = []
    for i in range(tbl.num_rows):
        text = tbl.column("transcription")[i].as_py() or ""
        if not (700 <= len(text) <= 3000):
            continue
        n_sec = len({m.upper() for m in re.findall(EN_HDR, text)})
        if n_sec < 3:
            continue
        kept.append({
            "src": "mtsamples",
            "spec": (tbl.column("medical_specialty")[i].as_py() or "").strip(),
            "text": text,
            "n_lab": len(re.findall(EN_LAB, text)),
            "n_sec": n_sec,
            "n_dose": len(re.findall(EN_DOSE, text)),
        })
    by_spec: dict[str, list[dict]] = collections.defaultdict(list)
    for d in kept:
        by_spec[d["spec"]].append(d)
    balanced: list[dict] = []
    for spec in sorted(by_spec):
        # trong mỗi chuyên khoa, ưu tiên note giàu viết tắt lab trước khi cắt
        ranked = sorted(by_spec[spec], key=lambda d: -(2 * min(d["n_lab"], 6) + d["n_sec"]))
        balanced += ranked[:per_spec]
    balanced.sort(key=lambda d: -(2 * min(d["n_lab"], 6) + d["n_sec"] + min(d["n_dose"], 4)))
    return balanced


def filter_vietnamese(paths: dict[str, list[Path]], matchers: list[re.Pattern],
                      cap: int = 1200, min_icd: int = 2) -> list[dict]:
    """Nguồn 3 — 600-3000 ký tự VÀ >=2 tên bệnh khớp nguyên văn bảng ICD của BTC."""
    import pyarrow.parquet as pq

    specs = {
        "vi_medtext": ("text", None),
        "vi_health_blog": ("context", None),
        "vi_medqa": ("question", "answer"),
    }
    rng = random.Random(SEED)
    out: list[dict] = []
    for name, (col_a, col_b) in specs.items():
        tbl = pq.read_table(paths[name][0])
        docs: list[str] = []
        for i in range(tbl.num_rows):
            text = tbl.column(col_a)[i].as_py() or ""
            if col_b:
                text = text + "\n" + (tbl.column(col_b)[i].as_py() or "")
            if 600 <= len(text) <= 3000:
                docs.append(text)
        picked: list[dict] = []
        for text in docs:
            n = count_icd(text, matchers)
            if n >= min_icd:
                picked.append({"src": name, "n_icd": n, "text": text})
            if len(picked) >= cap * 3:
                break
        rng.shuffle(picked)
        for i, d in enumerate(picked[:cap]):
            out.append({"id": f"{name}_{i:04d}", **d})
        print(f"  {name:16} {len(docs):>6} trong dải -> {min(len(picked), cap):>5} đã chọn")
    return out


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  {path.relative_to(REPO)}: {len(rows)} dòng, {path.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true",
                    help="dùng parquet đã có trong data/external/raw")
    args = ap.parse_args()

    print("[1/4] tải parquet")
    paths = download(skip=args.skip_download)

    print("[2/4] nguồn 1 — seed từ bảng BTC")
    icd, rx = build_seed()
    write_jsonl(EXT / "seed" / "icd_seed.jsonl", icd)
    write_jsonl(EXT / "seed" / "rxnorm_seed.jsonl", rx)
    print(f"  ICD: {len({r['code'] for r in icd})} mã duy nhất, TB "
          f"{st.mean(r['n_words'] for r in icd):.2f} từ (gold 3,53 từ)")

    print("[3/4] nguồn 2 — mtsamples")
    mts = filter_mtsamples(paths["mtsamples"][0])
    write_jsonl(EXT / "en_notes" / "mtsamples_filtered.jsonl",
                [{"id": f"mts_{i:04d}", **d} for i, d in enumerate(mts)])
    n_lab = sum(1 for d in mts if d["n_lab"])
    print(f"  có viết tắt lab: {n_lab}/{len(mts)} ({100 * n_lab / max(len(mts), 1):.0f}%), test 8%")

    print("[4/4] nguồn 3 — corpus tiếng Việt")
    matchers = build_icd_matchers([r for r in icd] + load_alias(
        KB / "icd10_aliases.csv.gz", "code", 1, 99))
    vi = filter_vietnamese(paths, matchers)
    write_jsonl(EXT / "vi_corpus" / "vi_filtered.jsonl", vi)
    if vi:
        print(f"  tên ICD/file TB {st.mean(d['n_icd'] for d in vi):.1f} (test 5,5)")

    print("\nxong. license từng nguồn: data/external/README.md")


if __name__ == "__main__":
    main()
