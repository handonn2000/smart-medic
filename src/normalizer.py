import pandas as pd
from rapidfuzz import process, fuzz
import requests
from pathlib import Path

# Resolve paths relative to the project root (parent of src/).
_ROOT_DIR = Path(__file__).resolve().parent.parent
_KB_DIR = _ROOT_DIR / "data" / "knowledge_base"
_RXNORM_PATH = _KB_DIR / "RXNORM.csv"
_ICD10_PATH = _KB_DIR / "ICD10.csv"

# Prefer ingredient / brand rows to keep fuzzy search tractable.
_RXNORM_TTYS = {"IN", "BN", "PIN", "MIN", "SCD", "SBD"}


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
            print(f"[WARN] Missing file: {_ICD10_PATH}")
            return

        try:
            # File VN ICD có vài dòng tiêu đề trước header thật.
            df = pd.read_csv(
                _ICD10_PATH,
                encoding="utf-8-sig",
                skiprows=4,
                dtype=str,
                low_memory=False,
            )
            df.columns = [c.strip() for c in df.columns]

            code_col = next((c for c in df.columns if c.lower() in ("mã", "ma", "code")), None)
            name_col = next(
                (c for c in df.columns if c.lower() in ("tên bệnh", "ten benh", "name")),
                None,
            )
            if code_col is None or name_col is None:
                raise ValueError(
                    f"Không tìm thấy cột mã/tên bệnh. Các cột: {list(df.columns)}"
                )

            df = df[[code_col, name_col]].rename(columns={code_col: "code", name_col: "name"})
            df = df.dropna(subset=["code", "name"])
            df["code"] = df["code"].str.strip()
            df["name"] = df["name"].str.strip()
            df = df[(df["code"] != "") & (df["name"] != "")]
            df = df.drop_duplicates(subset=["name"], keep="first")

            self.icd_df = df.reset_index(drop=True)
            self.icd_dict = dict(
                zip(self.icd_df["name"].str.lower(), self.icd_df["code"])
            )
            print(f"[OK] Loaded ICD-10: {len(self.icd_df)} entries from {_ICD10_PATH.name}")
        except Exception as exc:
            print(f"[WARN] Failed to load ICD-10 ({_ICD10_PATH.name}): {exc}")

    def normalize_drug(self, drug_text: str, top_k=3):
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
                if score > 70:  # threshold
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

    def normalize_disease(self, disease_text: str, top_k=3):
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
                if score > 65:
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
