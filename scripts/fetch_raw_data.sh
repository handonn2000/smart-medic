#!/usr/bin/env bash
# Kiểm tra & liệt kê nguồn thô cần cho `smk kb build`.
#
# KHÔNG tự tải: ba nguồn đều có điều kiện sử dụng riêng (SNOMED cần license
# của SNOMED International, RxNorm cần tài khoản UMLS/UTS, ICD-10 tiếng Việt
# lấy từ công bố của Bộ Y tế). Script này chỉ báo thiếu gì và lấy ở đâu.
#
# Dùng:  ./scripts/fetch_raw_data.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW="${SMK_RAW_DIR:-$ROOT/data/knowledge_base}"

missing=0

need() {  # need <đường dẫn> <mô tả> <nguồn lấy>
  if [[ -e "$RAW/$1" ]]; then
    size=$(du -sh "$RAW/$1" 2>/dev/null | cut -f1)
    printf '  ✓ %-46s %s\n' "$1" "$size"
  else
    printf '  ✗ %-46s THIẾU\n' "$1"
    printf '      %s\n      → %s\n' "$2" "$3"
    missing=$((missing + 1))
  fi
}

echo "Nguồn thô trong: $RAW"
echo

echo "── BẮT BUỘC — nhánh CHẨN_ĐOÁN ──"
need "icd/icd-10-vn.pdf" \
     "ICD-10 song ngữ Việt–Anh của BYT, 1.271 trang (có text layer, KHÔNG cần OCR)" \
     "Phụ lục Bảng danh mục ICD-10 — công bố của Bộ Y tế"
need "icd/ICD10.csv" \
     "Danh mục ICD-10 theo QĐ 4469/BYT — bổ sung 1.101 mã mở rộng 5 ký tự" \
     "Cổng dữ liệu Bộ Y tế"

echo
echo "── BẮT BUỘC — nhánh THUỐC ──"
need "rxnorm/rrf/RXNCONSO.RRF" \
     "Tên thuốc RxNorm (~1,2 triệu dòng)" \
     "https://www.nlm.nih.gov/research/umls/rxnorm/ — cần tài khoản UTS"
need "rxnorm/rrf/RXNREL.RRF" \
     "Quan hệ giữa các khái niệm thuốc" \
     "cùng bộ RxNorm Full Release"

echo
echo "── TUỲ CHỌN — enrichment E1 (SNOMED) ──"
need "snomed/CT_InternationalRF2/Snapshot/Terminology" \
     "SNOMED CT International, thư mục Snapshot (KHÔNG cần Full)" \
     "https://www.snomed.org/ — cần license quốc gia hoặc affiliate"

echo
echo "── TUỲ CHỌN — enrichment ATC (tên thuốc tiếng Việt) ──"
need "atc/ddd.csv" \
     "Bảng DDD của BYT theo ATC/DDD Index — cấp 608 tên hoạt chất TIẾNG VIỆT" \
     "Danh mục thuốc/DDD của Bộ Y tế VN; ATC trong RxNorm có SRL=0 (không hạn chế)"

echo
if (( missing )); then
  echo "→ Thiếu $missing nguồn. Nguồn TUỲ CHỌN thiếu vẫn build được"
  echo "  (\`smk kb enrich\` tự bỏ qua nguồn không có)."
  echo "  Thiếu nguồn BẮT BUỘC thì nhánh tương ứng sẽ rỗng."
  exit 1
fi
echo "→ Đủ nguồn. Chạy: smk kb build"
