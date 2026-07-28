# Kế hoạch Tích hợp mtsamples vào gen_sample_data.py

## 📋 Tổng quan

Mở rộng script hiện tại để hỗ trợ **dịch và mapping bệnh án từ mtsamples**, cho phép kết hợp dữ liệu synthetic và real-translated để tăng chất lượng training data.

---

## 🎯 Mục tiêu

- ✅ Dịch 100-200 bệnh án từ mtsamples (configurable)
- ✅ Đa dạng thể loại (chuyên khoa khác nhau)
- ✅ Mapping thuật ngữ y tế Anh → Việt
- ✅ Tính toán lại offset sau khi dịch
- ✅ Gắn nhãn tương thích với format hiện tại
- ✅ Tích hợp vào workflow compose → emit → verify

---

## 🔧 Các thay đổi cần thực hiện

### **0. Cập nhật constants cho cấu trúc folder mới**

**Vị trí:** Đầu file, sau imports (khoảng dòng 46-53)

```python
# THAY THẾ các constants cũ:
# WORK = REPO / "data" / "synth" / "work"
# OUT_LABELS = REPO / "data" / "synth"
# OUT_TEXT = REPO / "data" / "train_input"

# BẰNG cấu trúc mới:
BASE_DIR = REPO / "data" / "generated_medical_records"

# Synthetic paths
SYNTHETIC_DIR = BASE_DIR / "synthetic"
SYNTHETIC_WORK = SYNTHETIC_DIR / "intermediate"
SYNTHETIC_TEXT = SYNTHETIC_DIR / "text"
SYNTHETIC_ANNOTATIONS = SYNTHETIC_DIR / "annotations"

# Translated paths
TRANSLATED_DIR = BASE_DIR / "translated"
TRANSLATED_WORK = TRANSLATED_DIR / "intermediate"
TRANSLATED_TEXT = TRANSLATED_DIR / "text"
TRANSLATED_ANNOTATIONS = TRANSLATED_DIR / "annotations"

# Backward compatibility (để không break existing code)
WORK = SYNTHETIC_WORK
OUT_LABELS = SYNTHETIC_ANNOTATIONS
OUT_TEXT = SYNTHETIC_TEXT
```

### **1. Thêm hàm crawl/load mtsamples**

**Vị trí:** Sau dòng 50, trước `DRUG_FREQ`

```python
# Thêm sau dòng 50 (sau BRACKET = ...)

MTSAMPLES_CATEGORIES = [
    "Cardiovascular / Pulmonary",
    "Gastroenterology", 
    "Neurology",
    "Orthopedic",
    "Nephrology",
    "Endocrinology",
    "General Medicine",
    "Hematology - Oncology",
]

# Mapping category → prefix ngắn gọn cho tên file
CATEGORY_PREFIXES = {
    "Cardiovascular / Pulmonary": "cardio",
    "Gastroenterology": "gastro",
    "Neurology": "neuro",
    "Orthopedic": "ortho",
    "Nephrology": "nephro",
    "Endocrinology": "endo",
    "General Medicine": "general",
    "Hematology - Oncology": "hemato",
}

def fetch_mtsamples(categories: list[str], n_per_cat: int = 15) -> list[dict]:
    """Tải bệnh án từ mtsamples.com theo danh mục.
    
    Returns:
        [{"id": "mtsamples_cardio_0001", "category": "Cardiovascular / Pulmonary", 
          "text": "...", "entities": [...]}]
    """
    # TODO: Implement crawling hoặc load từ dataset có sẵn
    # Có thể dùng: https://github.com/mtsamples/mtsamples
    pass

def parse_mtsamples_sections(text: str) -> dict[str, str]:
    """Parse các section từ bệnh án mtsamples.
    
    Sections: HISTORY, PHYSICAL EXAMINATION, MEDICATIONS, LAB DATA, DIAGNOSIS
    """
    sections = {}
    pattern = r"([A-Z][A-Z\s]+):\s*\n(.*?)(?=\n[A-Z][A-Z\s]+:|\Z)"
    for match in re.finditer(pattern, text, re.DOTALL):
        sections[match.group(1).strip()] = match.group(2).strip()
    return sections
```

---

### **2. Thêm hàm dịch với OpenAI/Claude**

**Vị trí:** Sau hàm `call_api()` (khoảng dòng 730)

```python
# Thêm sau hàm call_api() (sau dòng 700)

def translate_medical_text(text: str, model: str = "gpt-4o") -> str:
    """Dịch văn bản y khoa Anh → Việt, giữ nguyên thuật ngữ quan trọng.
    
    Args:
        text: Văn bản tiếng Anh
        model: Model dùng để dịch
    
    Returns:
        Văn bản tiếng Việt
    """
    system_prompt = """Bạn là chuyên gia dịch thuật y khoa Anh-Việt.

QUY TẮC DỊCH:
1. Dịch sang tiếng Việt văn phong bệnh viện Việt Nam
2. GIỮ NGUYÊN các thuật ngữ sau bằng tiếng Anh:
   - Tên thuốc (aspirin, metformin, lisinopril...)
   - Viết tắt xét nghiệm (WBC, HbA1c, LDL, HDL, ECG...)
3. Dịch các thuật ngữ sau:
   - Tên bệnh: diabetes → đái tháo đường
   - Triệu chứng: chest pain → đau ngực
   - Xét nghiệm (dạng đầy đủ): Complete Blood Count → công thức máu toàn phần
4. Chuyển format sections:
   - "HISTORY OF PRESENT ILLNESS:" → "Bệnh sử:"
   - "PHYSICAL EXAMINATION:" → "Khám thực thể:"
   - "MEDICATIONS:" → "Thuốc đang dùng:"
   - "LABORATORY DATA:" → "Kết quả xét nghiệm:"
   - "DIAGNOSIS:" → "Chẩn đoán:"
5. Giữ cấu trúc markdown, xuống dòng như bản gốc
6. KHÔNG thêm giải thích, chỉ trả về văn bản đã dịch"""

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("thiếu OPENAI_API_KEY")
    
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    
    body = json.dumps({
        "model": model,
        "max_completion_tokens": 3000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Dịch bệnh án sau sang tiếng Việt:\n\n{text}"}
        ],
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
    
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
        return (data.get("choices", [{}])[0].get("message", {}).get("content", ""))
```

---

### **3. Thêm hàm mapping thuật ngữ và NER**

**Vị trí:** Sau `translate_medical_text()`

```python
# Thêm sau translate_medical_text()

def extract_entities_from_mtsamples(text_en: str, text_vi: str, 
                                    icd_map: dict, rx_map: dict) -> list[dict]:
    """Trích xuất entities từ bệnh án đã dịch và mapping với bảng BTC.
    
    Args:
        text_en: Văn bản gốc tiếng Anh
        text_vi: Văn bản đã dịch tiếng Việt
        icd_map: {tên_bệnh_tiếng_anh_lower: {"code": "K73", "alias": "Viêm gan mãn"}}
        rx_map: {tên_thuốc_lower: {"rxcui": "5224", "alias": "Heparin"}}
    
    Returns:
        [{"text": "đái tháo đường", "type": "CHẨN_ĐOÁN", "candidates": ["E11"], 
          "position": [45, 62], "assertions": []}]
    """
    records = []
    
    # 1. Tìm tên thuốc (giữ nguyên tiếng Anh sau khi dịch)
    for drug_en, info in rx_map.items():
        alias = info["alias"]
        # Tìm trong văn bản Việt (thuốc giữ nguyên tiếng Anh)
        for match in re.finditer(r'\b' + re.escape(alias) + r'\b', text_vi, re.IGNORECASE):
            records.append({
                "text": match.group(),
                "type": "THUỐC",
                "candidates": [info["rxcui"]],
                "position": [match.start(), match.end()],
                "assertions": []
            })
    
    # 2. Tìm tên bệnh (đã dịch sang Việt)
    for icd_info in icd_map.values():
        alias = icd_info["alias"]
        for match in re.finditer(r'\b' + re.escape(alias) + r'\b', text_vi, re.IGNORECASE):
            records.append({
                "text": match.group(),
                "type": "CHẨN_ĐOÁN",
                "candidates": [icd_info["code"]],
                "position": [match.start(), match.end()],
                "assertions": []
            })
    
    # 3. Tìm triệu chứng (từ danh sách SYMPTOMS)
    for symptom in SYMPTOMS:
        for match in re.finditer(r'\b' + re.escape(symptom) + r'\b', text_vi):
            records.append({
                "text": match.group(),
                "type": "TRIỆU_CHỨNG",
                "candidates": [],
                "position": [match.start(), match.end()],
                "assertions": []
            })
    
    # 4. Tìm xét nghiệm (giữ viết tắt tiếng Anh hoặc đã dịch)
    for test_name in TEST_NAMES:
        for match in re.finditer(r'\b' + re.escape(test_name) + r'\b', text_vi, re.IGNORECASE):
            records.append({
                "text": match.group(),
                "type": "TÊN_XÉT_NGHIỆM",
                "candidates": [],
                "position": [match.start(), match.end()],
                "assertions": []
            })
    
    # 5. Loại bỏ overlap (ưu tiên span dài hơn)
    records = remove_overlapping_spans(records)
    
    # 6. Suy assertion (isNegated, isHistorical, isFamily)
    for rec in records:
        rec["assertions"] = assertions_at(text_vi, rec["position"][0])
    
    return sorted(records, key=lambda r: r["position"])

def remove_overlapping_spans(records: list[dict]) -> list[dict]:
    """Loại bỏ các span chồng lấn, ưu tiên span dài hơn."""
    sorted_recs = sorted(records, key=lambda r: (r["position"][0], -(r["position"][1] - r["position"][0])))
    kept = []
    for rec in sorted_recs:
        if not any(overlaps(rec["position"], k["position"]) for k in kept):
            kept.append(rec)
    return kept

def overlaps(pos1: list[int], pos2: list[int]) -> bool:
    """Kiểm tra 2 span có chồng lấn không."""
    return not (pos1[1] <= pos2[0] or pos2[1] <= pos1[0])

def build_term_mapping(icd_list: list[dict], rx_list: list[dict]) -> tuple[dict, dict]:
    """Xây dựng mapping Anh → Việt cho ICD và RxNorm.
    
    Returns:
        (icd_map, rx_map)
        icd_map: {english_term_lower: {"code": "K73", "alias": "Viêm gan mãn"}}
    """
    # TODO: Cần có bảng ánh xạ Anh-Việt (có thể crawl từ Wikipedia hoặc dùng GPT)
    # Tạm thời dùng heuristic đơn giản
    icd_map = {}
    # Ví dụ: "chronic hepatitis" → "Viêm gan mãn" (K73)
    # Cần có bảng mapping chuẩn
    
    rx_map = {r["alias"].lower(): r for r in rx_list}
    return icd_map, rx_map
```

---

### **4. Thêm lệnh mới: `translate`**

**Vị trí:** 
- Hàm `cmd_translate()`: Thêm trước `cmd_compose()` (khoảng dòng 740)
- Phần CLI: Thêm vào `main()`, sau `sub.add_parser("verify")` (khoảng dòng 850)

```python
# Thêm vào hàm main(), sau sub.add_parser("verify")

def cmd_translate(args) -> int:
    """Dịch bệnh án từ mtsamples và tạo nhãn."""
    rng = random.Random(args.seed)
    
    # Tạo cấu trúc folder mới
    TRANSLATED_WORK.mkdir(parents=True, exist_ok=True)
    TRANSLATED_TEXT.mkdir(parents=True, exist_ok=True)
    TRANSLATED_ANNOTATIONS.mkdir(parents=True, exist_ok=True)
    
    print("đọc bảng ban tổ chức...")
    icd = load_icd()
    rx = load_rxnorm()
    
    print("xây dựng mapping thuật ngữ...")
    icd_map, rx_map = build_term_mapping(icd, rx)
    
    print(f"tải {args.n} bệnh án từ mtsamples...")
    # Chia đều theo danh mục
    n_per_cat = args.n // len(MTSAMPLES_CATEGORIES)
    samples = fetch_mtsamples(MTSAMPLES_CATEGORIES[:args.n_categories], n_per_cat)
    
    print(f"đã tải {len(samples)} bệnh án")
    
    # File lưu trữ với tên rõ ràng
    path_trans = TRANSLATED_WORK / "translation_process.jsonl"
    translated = []
    
    # Counter cho mỗi category
    category_counters = {}
    
    for i, sample in enumerate(samples, 1):
        # Tạo ID với prefix category
        category = sample["category"]
        prefix = CATEGORY_PREFIXES.get(category, "unknown")
        
        if prefix not in category_counters:
            category_counters[prefix] = 1
        else:
            category_counters[prefix] += 1
        
        file_id = f"mtsamples_{prefix}_{category_counters[prefix]:04d}"
        
        print(f"  [{i}/{len(samples)}] Dịch {file_id}...")
        
        # Dịch
        text_vi = translate_medical_text(sample["text"], args.model)
        
        # Trích xuất entities
        records = extract_entities_from_mtsamples(
            sample["text"], text_vi, icd_map, rx_map
        )
        
        # Lưu
        translated.append({
            "id": file_id,
            "category": category,
            "text_en": sample["text"],
            "text_vi": text_vi,
            "records": records
        })
        
        if i % 10 == 0:
            # Lưu checkpoint
            with path_trans.open("w", encoding="utf-8") as fh:
                for item in translated:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    # Lưu cuối cùng
    with path_trans.open("w", encoding="utf-8") as fh:
        for item in translated:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"đã dịch {len(translated)} bản → {path_trans}")
    
    # Export sang format cuối cùng
    n_ok = 0
    for item in translated:
        if len(item["records"]) >= 12:  # Ngưỡng tối thiểu
            # Lưu text
            text_file = TRANSLATED_TEXT / f"{item['id']}.txt"
            text_file.write_text(item["text_vi"], encoding="utf-8")
            
            # Lưu annotations
            ann_file = TRANSLATED_ANNOTATIONS / f"{item['id']}.json"
            ann_file.write_text(
                json.dumps(item["records"], ensure_ascii=False, indent=2), 
                encoding="utf-8"
            )
            n_ok += 1
    
    print(f"đã xuất {n_ok}/{len(translated)} bản dùng được")
    print(f"  văn bản: {TRANSLATED_TEXT.relative_to(REPO)}")
    print(f"  nhãn: {TRANSLATED_ANNOTATIONS.relative_to(REPO)}")
    
    return 0

# Thêm vào phần CLI (trong hàm main, sau verify parser)
t = sub.add_parser("translate", parents=[seed_arg], 
                   help="dịch bệnh án từ mtsamples → tiếng Việt + nhãn")
t.add_argument("--n", type=int, default=100, 
               help="số bệnh án cần dịch (mặc định 100)")
t.add_argument("--n-categories", type=int, default=8,
               help="số danh mục mtsamples (mặc định 8 - đa dạng)")
t.add_argument("--model", default="gpt-4o",
               help="model dùng để dịch")
t.add_argument("--source", default="auto",
               help="nguồn mtsamples: 'auto' (crawl), hoặc đường dẫn file JSON")

# Thêm vào dict routing
return {
    "compose": cmd_compose, 
    "emit": cmd_emit, 
    "verify": cmd_verify,
    "translate": cmd_translate  # ← THÊM
}[args.cmd](args)
```

---

### **5. Cập nhật các lệnh hiện tại (compose, emit)**

**Vị trí:** Trong các hàm `cmd_compose()` và `cmd_emit()`

```python
# Trong cmd_compose() - thay đổi tên file output
def cmd_compose(args) -> int:
    rng = random.Random(args.seed)
    SYNTHETIC_WORK.mkdir(parents=True, exist_ok=True)  # ← Thay đổi
    
    # ...
    
    # Thay đổi tên file
    bundles = [{"id": f"synthetic_{i:04d}", "bundle": sample_bundle(rng, pools)}  # ← synthetic_*
               for i in range(1, args.n + 1)]
    
    path_b = SYNTHETIC_WORK / "entity_bundles.jsonl"  # ← Tên rõ ràng
    # ...
    
    path_c = SYNTHETIC_WORK / "composed_texts.jsonl"  # ← Tên rõ ràng
    # ...

# Trong cmd_emit() - cập nhật paths
def cmd_emit(args) -> int:
    rng = random.Random(args.seed + 1)
    src_c = Path(args.composed) if args.composed else SYNTHETIC_WORK / "composed_texts.jsonl"
    
    if not src_c.exists():
        sys.exit(f"chưa có {src_c} — chạy compose trước")
    
    bundles = {json.loads(l)["id"]: json.loads(l)["bundle"]
               for l in (SYNTHETIC_WORK / "entity_bundles.jsonl").read_text(encoding="utf-8").splitlines()}
    
    SYNTHETIC_TEXT.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_ANNOTATIONS.mkdir(parents=True, exist_ok=True)
    
    # ... logic như cũ ...
    
    # Khi lưu file
    (SYNTHETIC_TEXT / f"{row['id']}.txt").write_text(text, encoding="utf-8")
    (SYNTHETIC_ANNOTATIONS / f"{row['id']}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"đã sinh {n_ok} tài liệu vào {SYNTHETIC_ANNOTATIONS.relative_to(REPO)}")
    print(f"  văn bản: {SYNTHETIC_TEXT.relative_to(REPO)}")
```

---

### **6. Cập nhật verify để hỗ trợ cả translated**

**Vị trí:** Sửa hàm `cmd_verify()` (dòng 630-670)

```python
# Sửa trong cmd_verify(), dòng ~630

def cmd_verify(args) -> int:
    # Quét cả hai thư mục
    synthetic_files = sorted(SYNTHETIC_ANNOTATIONS.glob("*.json"))
    translated_files = sorted(TRANSLATED_ANNOTATIONS.glob("*.json"))
    all_files = synthetic_files + translated_files
    
    if not all_files:
        sys.exit(f"chưa có tài liệu nào trong {BASE_DIR.relative_to(REPO)}")
    
    print(f"\n{'='*60}")
    print(f"{'KIỂM TRA DỮ LIỆU SINH RA':^60}")
    print(f"{'='*60}\n")
    print(f"  📁 Synthetic:  {len(synthetic_files):3d} files  ({SYNTHETIC_ANNOTATIONS.relative_to(REPO)})")
    print(f"  📁 Translated: {len(translated_files):3d} files  ({TRANSLATED_ANNOTATIONS.relative_to(REPO)})")
    print(f"  📊 TỔNG:       {len(all_files):3d} files\n")
    
    # Load ICD và RxNorm để verify mã
    icd_codes = {r["code"] for r in load_icd()}
    rx_codes = {r["rxcui"] for r in load_rxnorm()}
    
    # Stats chung
    stats_all = verify_dataset(all_files, icd_codes, rx_codes, BASE_DIR)
    
    # Stats riêng cho từng loại (nếu cả 2 đều có)
    if synthetic_files and translated_files:
        print(f"\n{'='*60}")
        print(f"{'SO SÁNH CHI TIẾT':^60}")
        print(f"{'='*60}\n")
        
        print("📊 SYNTHETIC:")
        stats_syn = verify_dataset(synthetic_files, icd_codes, rx_codes, SYNTHETIC_ANNOTATIONS)
        
        print("\n📊 TRANSLATED:")
        stats_trs = verify_dataset(translated_files, icd_codes, rx_codes, TRANSLATED_ANNOTATIONS)
        
        # So sánh
        print(f"\n{'='*60}")
        print(f"{'ĐÁNH GIÁ':^60}")
        print(f"{'='*60}\n")
        print(f"  Avg spans/file:")
        print(f"    Synthetic:  {stats_syn['avg_spans']:.1f}")
        print(f"    Translated: {stats_trs['avg_spans']:.1f}")
        print(f"    Target:     48.0 (gold median)")
        
        print(f"\n  Span có mã:")
        print(f"    Synthetic:  {stats_syn['pct_with_code']:.0f}%")
        print(f"    Translated: {stats_trs['pct_with_code']:.0f}%")
        print(f"    Target:     >50%")
    
    return 1 if stats_all['errors'] > 0 else 0

def verify_dataset(files: list, icd_codes: set, rx_codes: set, base_path: Path) -> dict:
    """Verify một dataset và trả về stats."""
    bad = collections.Counter()
    n_span = n_cand = n_assert = n_mask = n_nfd = n_hdr = 0
    lens = collections.defaultdict(list)
    
    for path in files:
        records = json.loads(path.read_text(encoding="utf-8"))
        
        # Tìm file text tương ứng
        text_dir = base_path.parent / "text"
        text_file = text_dir / f"{path.stem}.txt"
        
        if not text_file.exists():
            bad["file text không tồn tại"] += 1
            continue
            
        raw = text_file.read_text(encoding="utf-8")
        n_nfd += int(raw != ud.normalize("NFC", raw))
        n_hdr += bool(re.search(r"(?m)^[^\n]{3,40}:\s*$", raw))
        n_mask += int(any("*" in r["text"] for r in records))
        
        for rec in records:
            n_span += 1
            start, end = rec["position"]
            if raw[start:end] != rec["text"]:
                bad["text != raw[position]"] += 1
                continue
            n_cand += bool(rec["candidates"])
            n_assert += bool(rec["assertions"])
            lens[rec["type"]].append(len(rec["text"].split()))
            for code in rec["candidates"]:
                if code not in icd_codes and code not in rx_codes:
                    bad["mã không tra được trong bảng BTC"] += 1
    
    n = len(files)
    avg_spans = n_span / n if n > 0 else 0
    pct_with_code = 100 * n_cand / max(n_span, 1)
    
    print(f"  {n} tài liệu · {n_span} span · {avg_spans:.1f} span/file")
    print(f"    Lỗi offset:        {sum(bad.values())}")
    print(f"    Span có mã:        {pct_with_code:.0f}%")
    print(f"    Span có assertion: {100 * n_assert / max(n_span, 1):.0f}%")
    print(f"    File có bẫy ***:   {100 * n_mask / n:.0f}%")
    print(f"    File dạng NFD:     {100 * n_nfd / n:.0f}%")
    print(f"    File có tiêu đề:   {100 * n_hdr / n:.0f}%")
    
    if lens:
        print(f"\n  Độ dài span (từ):")
        ref = {"CHẨN_ĐOÁN": 4.05, "TRIỆU_CHỨNG": 3.27, "THUỐC": 2.10,
               "TÊN_XÉT_NGHIỆM": 3.71, "KẾT_QUẢ_XÉT_NGHIỆM": 5.32}
        for ctype in sorted(lens):
            avg = st.mean(lens[ctype])
            gold_avg = ref.get(ctype, 0)
            print(f"    {ctype:22} {avg:5.2f}  (gold: {gold_avg:5.2f})  n={len(lens[ctype])}")
    
    if bad:
        print(f"\n  ⚠️  LỖI: {dict(bad)}")
    
    return {
        'avg_spans': avg_spans,
        'pct_with_code': pct_with_code,
        'errors': sum(bad.values())
    }
```

---

## 📝 Workflow sau khi implement

### **Workflow hiện tại (giữ nguyên):**
```bash
python scripts/gen_sample_data.py compose --n 200 --use-api
python scripts/gen_sample_data.py emit
python scripts/gen_sample_data.py verify
```

### **Workflow mới (mtsamples):**
```bash
# Bước 1: Dịch mtsamples
python scripts/gen_sample_data.py translate --n 100 --model gpt-4o

# Bước 2: Verify (tự động nhận cả synthetic + translated)
python scripts/gen_sample_data.py verify
```

### **Workflow kết hợp:**
```bash
# Tạo 150 synthetic + 100 translated = 250 bệnh án
python scripts/gen_sample_data.py compose --n 150 --use-api
python scripts/gen_sample_data.py emit
python scripts/gen_sample_data.py translate --n 100
python scripts/gen_sample_data.py verify
```

---

## 🎯 Output mong đợi

### **Cấu trúc folder MỚI (rõ ràng và có tổ chức):**

```
data/
└── generated_medical_records/           # Thư mục chính chứa tất cả dữ liệu sinh ra
    ├── synthetic/                       # Dữ liệu tự sinh bởi GPT
    │   ├── intermediate/                # File trung gian (work files)
    │   │   ├── entity_bundles.jsonl    # Bundle thực thể đã bốc
    │   │   ├── composed_texts.jsonl    # Văn bản GPT đã viết (có dấu 〔〕)
    │   │   └── prompts.jsonl           # Prompts gửi cho LLM (optional)
    │   ├── text/                        # Văn bản sạch (không có nhãn)
    │   │   ├── synthetic_0001.txt
    │   │   ├── synthetic_0002.txt
    │   │   └── ...                      # 194 files
    │   └── annotations/                 # Nhãn NER (JSON)
    │       ├── synthetic_0001.json
    │       ├── synthetic_0002.json
    │       └── ...                      # 194 files
    │
    └── translated/                      # Dữ liệu dịch từ mtsamples ← MỚI
        ├── intermediate/                # File trung gian
        │   └── translation_process.jsonl  # Gồm text_en, text_vi, records
        ├── text/                        # Văn bản tiếng Việt đã dịch
        │   ├── mtsamples_cardio_0001.txt
        │   ├── mtsamples_gastro_0002.txt
        │   └── ...                      # 100 files (có prefix theo category)
        └── annotations/                 # Nhãn NER (JSON)
            ├── mtsamples_cardio_0001.json
            ├── mtsamples_gastro_0002.json
            └── ...                      # 100 files
```

### **So sánh cấu trúc cũ vs mới:**

| Cũ | Mới | Lý do |
|----|-----|-------|
| `data/synth/` | `data/generated_medical_records/synthetic/` | Rõ ràng hơn về mục đích |
| `data/train_input/` | `→ text/` | Tách riêng text và annotations |
| `cmp*.txt` | `synthetic_*.txt` | Tên file mô tả rõ nguồn gốc |
| `cmp*.json` | `synthetic_*.json` | Đồng nhất với text |
| `work/` | `intermediate/` | Tên chuẩn hơn trong ML pipeline |
| - | `translated/` | MỚI - dữ liệu mtsamples |
| `mt*.txt` | `mtsamples_{category}_*.txt` | Thêm category để dễ phân loại |

---

## ⚠️ Lưu ý quan trọng

### **1. Cần có bảng mapping Anh-Việt chuẩn**
- Hiện tại `build_term_mapping()` chỉ là skeleton
- Cần tạo file `data/knowledge_base/term_mapping.json`:
```json
{
  "diabetes mellitus type 2": {"vi": "Đái tháo đường type 2", "icd": "E11"},
  "hypertension": {"vi": "Tăng huyết áp", "icd": "I10"},
  "pneumonia": {"vi": "Viêm phổi", "icd": "J18"}
}
```

### **2. Nguồn mtsamples**
- Option 1: Crawl từ mtsamples.com (cần respect robots.txt)
- Option 2: Dùng dataset có sẵn từ GitHub: https://github.com/mtsamples/mtsamples
- Option 3: Tải manual và lưu vào `data/mtsamples/raw/*.txt`

### **3. Cost ước tính**
- Dịch 100 bản × ~500 từ/bản = 50,000 từ
- GPT-4o: ~$0.15-0.30 cho input + output
- **Tổng: ~$5-10 USD**

### **4. Chất lượng kiểm tra**
- Sau khi dịch, nên review thủ công 10-20 bản mẫu
- Kiểm tra:
  - ✅ Thuật ngữ dịch đúng
  - ✅ Offset mapping chính xác
  - ✅ Văn phong tự nhiên
  - ✅ Assertions (isNegated, isHistorical) đúng

---

## 🚀 Các bước triển khai

### **Phase 1: Infrastructure (1-2 giờ)**
1. ✅ Thêm các hàm utility (parse, mapping, overlap detection)
2. ✅ Tạo structure cho lệnh `translate`

### **Phase 2: Integration (2-3 giờ)**
3. ✅ Implement `fetch_mtsamples()` - load từ file hoặc API
4. ✅ Implement `translate_medical_text()` - wrapper OpenAI
5. ✅ Implement `extract_entities_from_mtsamples()` - NER + mapping

### **Phase 3: Testing (1-2 giờ)**
6. ✅ Test với 5-10 bản mẫu
7. ✅ Điều chỉnh prompt dịch
8. ✅ Fine-tune entity extraction

### **Phase 4: Production (30 phút)**
9. ✅ Chạy full 100 bản
10. ✅ Verify kết quả với `verify` command

---

## 📊 Metrics đánh giá

Sau khi implement, chạy verify và so sánh:

| Metric | Synthetic | Translated | Target |
|--------|-----------|------------|--------|
| Avg spans/file | 27.6 | ?? | 48 |
| Span có mã | 37% | ?? | >50% |
| Lỗi offset | 0 | ?? | 0 |
| Văn phong tự nhiên | ⭐⭐⭐ | ?? | ⭐⭐⭐⭐⭐ |

---

## 📚 Tài liệu tham khảo

- **mtsamples dataset**: https://github.com/mtsamples/mtsamples
- **ICD-10 mapping**: WHO ICD-10 classification
- **RxNorm**: https://www.nlm.nih.gov/research/umls/rxnorm/
- **Script gốc**: `/Users/handonn/Workplace/viettelAI/smart-medic/scripts/gen_sample_data.py`

---

## ✅ Checklist triển khai

- [ ] **Phase 0: Restructure (30 phút)**
  - [ ] Cập nhật constants (BASE_DIR, SYNTHETIC_*, TRANSLATED_*)
  - [ ] Cập nhật cmd_compose() để dùng folder mới
  - [ ] Cập nhật cmd_emit() để dùng folder mới
  - [ ] Test với data hiện tại (đảm bảo backward compatible)

- [ ] **Phase 1: Infrastructure (1-2 giờ)**
  - [ ] Thêm CATEGORY_PREFIXES mapping
  - [ ] Thêm các hàm utility (parse, mapping, overlap detection)
  - [ ] Tạo structure cho lệnh `translate`

- [ ] **Phase 2: Integration (2-3 giờ)**
  - [ ] Implement `fetch_mtsamples()` - load từ file hoặc API
  - [ ] Implement `translate_medical_text()` - wrapper OpenAI
  - [ ] Implement `extract_entities_from_mtsamples()` - NER + mapping
  - [ ] Implement `cmd_translate()` với file naming mới

- [ ] **Phase 3: Testing (1-2 giờ)**
  - [ ] Test với 5-10 bản mẫu
  - [ ] Verify cấu trúc folder đúng
  - [ ] Verify tên file rõ ràng (có category prefix)
  - [ ] Điều chỉnh prompt dịch
  - [ ] Fine-tune entity extraction

- [ ] **Phase 4: Production (30 phút)**
  - [ ] Chạy full 100 bản translated
  - [ ] Verify kết quả với `verify` command mới
  - [ ] So sánh synthetic vs translated

- [ ] **Phase 5: Documentation (15 phút)**
  - [ ] Cập nhật README với cấu trúc folder mới
  - [ ] Thêm ví dụ sử dụng với folder mới

---

## 📂 Migration Guide (cho dữ liệu cũ)

Nếu đã có dữ liệu cũ, chạy script migration:

```bash
# Script tự động migrate (tạo sau)
python scripts/migrate_to_new_structure.py

# Hoặc manual:
mkdir -p data/generated_medical_records/synthetic/{intermediate,text,annotations}
mv data/synth/work/* data/generated_medical_records/synthetic/intermediate/
mv data/train_input/cmp*.txt data/generated_medical_records/synthetic/text/
mv data/synth/cmp*.json data/generated_medical_records/synthetic/annotations/

# Rename files: cmp* → synthetic_*
cd data/generated_medical_records/synthetic/text
for f in cmp*.txt; do mv "$f" "synthetic_${f#cmp}"; done
cd ../annotations
for f in cmp*.json; do mv "$f" "synthetic_${f#cmp}"; done
```

---

**Tác giả:** Kiro AI  
**Ngày tạo:** 2025-01-28  
**Script target:** `scripts/gen_sample_data.py`  
**Ước tính thời gian:** 4-6 giờ (bao gồm testing)
