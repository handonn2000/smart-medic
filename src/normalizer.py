import csv

import pandas as pd
from rapidfuzz import process, fuzz
import requests
from pathlib import Path

# Resolve paths relative to the project root (parent of src/).
_ROOT_DIR = Path(__file__).resolve().parent.parent
_KB_DIR = _ROOT_DIR / "data" / "knowledge_base"
_RXNORM_PATH = _KB_DIR / "RXNORM.csv"
_ICD10_PATH = _KB_DIR / "ICD10_VN.csv"

# Tên cột mã bệnh / tên bệnh, thử theo đúng thứ tự này và so khớp CHÍNH XÁC.
#
# Bản ICD-10 2020 của Bộ Y tế (ICD10_VN.csv) có NĂM cột bắt đầu bằng "MÃ" — MÃ CHƯƠNG,
# MÃ NHÓM CHÍNH, MÃ NHÓM PHỤ 1, MÃ NHÓM PHỤ 2, MÃ LOẠI — trước khi tới MÃ BỆNH, và bốn
# cột bắt đầu bằng "TÊN". So khớp kiểu "bắt đầu bằng" sẽ lấy MÃ CHƯƠNG: bảng còn 22 dòng
# tên chương thay vì 12.218 mã bệnh, mà chương trình vẫn chạy trơn — chỉ có điểm
# candidates lặng lẽ tụt. Danh sách này cũng còn nhận bản cũ (ICD10.csv, cột "Mã").
_ICD10_CODE_COLUMNS = ("mã bệnh", "mã", "ma", "code")
_ICD10_NAME_COLUMNS = ("tên bệnh", "ten benh", "name")

# Prefer ingredient / brand rows to keep fuzzy search tractable.
_RXNORM_TTYS = {"IN", "BN", "PIN", "MIN", "SCD", "SBD"}

# Số mã trả về và ngưỡng fuzzy, đo bằng scripts/measure_normalizer.py trên 1.456 mã
# CHẨN_ĐOÁN + 980 mã THUỐC của annotations_gold:
#
#   * Trả MỘT mã thắng trả ba mã ở mọi ngưỡng, vì đáp án gần như luôn chỉ có một mã
#     (1.456/1.536 CHẨN_ĐOÁN, 814/952 THUỐC). candidates chấm bằng J = |giao|/|hợp|, nên
#     ba mã mà đúng một thì J tối đa còn 1/3 — thêm mã là tự hạ điểm chính mình.
#   * Ngưỡng cũ (65 và 70) loại mất 41,6% và 23,2% số mã ĐÚNG mà tra cứu đã tìm ra.
#
# J trung bình mỗi span: CHẨN_ĐOÁN 0,146 -> 0,196; THUỐC 0,287 -> 0,312. Sửa ở đây thì
# chạy lại script đo, nó tự lấy ba hằng số này nên không lệch nhau được.
DEFAULT_TOP_K = 1
DISEASE_CUTOFF = 60
DRUG_CUTOFF = 55


def _column_of(header, wanted) -> int | None:
    """Vị trí cột khớp CHÍNH XÁC một trong `wanted`, theo thứ tự ưu tiên của `wanted`."""
    lowered = [str(cell).strip().lower() for cell in header]
    for name in wanted:
        if name in lowered:
            return lowered.index(name)
    return None


def read_icd10(path: Path) -> list[tuple[str, str]]:
    """[(mã bệnh, tên bệnh)] từ bảng ICD-10, tự tìm dòng header.

    Không đếm dòng tiêu đề bằng số cố định: bản của BTC (ICD10.csv) có 4 dòng trước
    header, bản 2020 của Bộ Y tế (ICD10_VN.csv) có 2, và tiêu đề bản 2020 là chuỗi trong
    ngoặc kép trải trên nhiều dòng vật lý. Đọc bằng csv chuẩn rồi dò header là cách duy
    nhất đổi file mà không phải sửa lại một con số ở đây.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    for index, row in enumerate(rows):
        code_at = _column_of(row, _ICD10_CODE_COLUMNS)
        name_at = _column_of(row, _ICD10_NAME_COLUMNS)
        if code_at is not None and name_at is not None:
            break
    else:
        raise ValueError(f"không thấy cột mã/tên bệnh trong {path.name}")

    out = []
    for row in rows[index + 1:]:
        if len(row) <= max(code_at, name_at):
            continue
        code, name = row[code_at].strip(), row[name_at].strip()
        if code and name:
            out.append((code, name))
    if not out:
        raise ValueError(f"{path.name}: header ở dòng {index + 1} nhưng không có dữ liệu")
    return out


class MedicalNormalizer:
    def __init__(self):
        self.rxnorm_cache = {}
        self.icd10_cache = {}
        self.rxnorm_df = pd.DataFrame()
        self.icd_df = pd.DataFrame()
        self.rxnorm_dict = {}
        self.icd_dict = {}
        self.load_dictionaries()

    def load_dictionaries(self):
        """Tải dictionary mapping từ knowledge base."""
        self._load_rxnorm()
        self._load_icd10()

    def _load_rxnorm(self):
        if not _RXNORM_PATH.is_file():
            print(f"[WARN] Missing file: {_RXNORM_PATH}")
            return

        try:
            df = pd.read_csv(
                _RXNORM_PATH,
                usecols=["rxcui", "str", "tty", "lat"],
                dtype=str,
                low_memory=False,
            )
            df = df.dropna(subset=["rxcui", "str"])
            df["str"] = df["str"].str.strip()
            df["rxcui"] = df["rxcui"].str.strip()
            df = df[df["str"] != ""]

            if "lat" in df.columns:
                df = df[df["lat"].fillna("ENG").str.upper() == "ENG"]
            if "tty" in df.columns:
                filtered = df[df["tty"].isin(_RXNORM_TTYS)]
                if not filtered.empty:
                    df = filtered

            df = df.drop_duplicates(subset=["str"], keep="first")
            df = df.rename(columns={"str": "name"})

            self.rxnorm_df = df.reset_index(drop=True)
            self.rxnorm_dict = dict(
                zip(self.rxnorm_df["name"].str.lower(), self.rxnorm_df["rxcui"])
            )
            print(f"[OK] Loaded RxNorm: {len(self.rxnorm_df)} entries from {_RXNORM_PATH.name}")
        except Exception as exc:
            print(f"[WARN] Failed to load RxNorm ({_RXNORM_PATH.name}): {exc}")

    def _load_icd10(self):
        if not _ICD10_PATH.is_file():
            print(f"[WARN] Missing file: {_ICD10_PATH}"
                  f" — mọi CHẨN_ĐOÁN sẽ không có mã nào")
            return

        try:
            rows = read_icd10(_ICD10_PATH)
            df = pd.DataFrame(rows, columns=["code", "name"])
            df = df.drop_duplicates(subset=["name"], keep="first")

            self.icd_df = df.reset_index(drop=True)
            self.icd_dict = dict(
                zip(self.icd_df["name"].str.lower(), self.icd_df["code"])
            )
            print(f"[OK] Loaded ICD-10: {len(self.icd_df)} entries from {_ICD10_PATH.name}")
        except Exception as exc:
            print(f"[WARN] Failed to load ICD-10 ({_ICD10_PATH.name}): {exc}"
                  f" — mọi CHẨN_ĐOÁN sẽ không có mã nào")

    def normalize_drug(self, drug_text: str, top_k=DEFAULT_TOP_K):
        """Trả về list candidates RxNorm"""
        if not drug_text or drug_text.strip() == "":
            return []

        text_lower = drug_text.lower().strip()

        # Exact match
        if text_lower in self.rxnorm_dict:
            return [self.rxnorm_dict[text_lower]]

        # Fuzzy matching
        if not self.rxnorm_df.empty:
            choices = self.rxnorm_df["name"].tolist()
            matches = process.extract(
                text_lower, choices, scorer=fuzz.token_sort_ratio, limit=top_k
            )
            candidates = []
            for match, score, idx in matches:
                if score > DRUG_CUTOFF:
                    rxcui = str(self.rxnorm_df.iloc[idx]["rxcui"])
                    candidates.append(rxcui)
            return candidates[:top_k]

        # Fallback: RxNav API (NLM)
        try:
            resp = requests.get(
                f"https://rxnav.nlm.nih.gov/REST/drugs.json?name={drug_text}",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "drugGroup" in data and "conceptGroup" in data["drugGroup"]:
                    return [
                        c["rxcui"]
                        for c in data["drugGroup"]["conceptGroup"][0].get(
                            "conceptProperties", []
                        )
                    ][:top_k]
        except Exception:
            pass

        # No guess beats a wrong guess: candidates are scored by Jaccard, so a code
        # that cannot possibly be right only enlarges the union and pushes J down.
        return []

    def normalize_disease(self, disease_text: str, top_k=DEFAULT_TOP_K):
        """Trả về ICD-10 code"""
        if not disease_text or disease_text.strip() == "":
            return []

        text_lower = disease_text.lower().strip()

        if text_lower in self.icd_dict:
            return [self.icd_dict[text_lower]]

        if not self.icd_df.empty:
            choices = self.icd_df["name"].tolist()
            matches = process.extract(
                text_lower, choices, scorer=fuzz.token_sort_ratio, limit=top_k
            )
            candidates = []
            for match, score, idx in matches:
                if score > DISEASE_CUTOFF:
                    code = str(self.icd_df.iloc[idx]["code"])
                    candidates.append(code)
            return candidates[:top_k]

        return []

    def normalize_test(self, test_text: str):
        """Không dùng khi chấm: gold để candidates RỖNG cho cả hai type xét nghiệm.

        Giữ lại vì chỉ đề bài của Vòng 1 mới không tính mã xét nghiệm; nếu vòng sau có
        thì thay bằng LOINC mapping ở đây. Trả về rỗng, KHÔNG trả mã giả: điền mã cho
        span mà đáp án để rỗng biến J = 1 (cả hai rỗng) thành J = 0.
        """
        return []
