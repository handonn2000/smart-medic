import csv
import json
import re

import pandas as pd
from rapidfuzz import process, fuzz
import requests
from pathlib import Path

# Resolve paths relative to the project root (parent of src/).
_ROOT_DIR = Path(__file__).resolve().parent.parent
_KB_DIR = _ROOT_DIR / "data" / "knowledge_base"
_RXNORM_PATH = _KB_DIR / "RXNORM.csv"
_ICD10_PATH = _KB_DIR / "ICD10_VN.csv"
# BN/SBD/SCD → IN lookups are remote; cache on disk so the second run (and measure)
# does not re-hit RxNav for every brand.
_RXNORM_TO_IN_CACHE = _KB_DIR / "rxnorm_to_in.json"
_RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"

# Tên cột mã bệnh / tên bệnh, thử theo đúng thứ tự này và so khớp CHÍNH XÁC.
#
# Bản ICD-10 2020 của Bộ Y tế (ICD10_VN.csv) có NĂM cột bắt đầu bằng "MÃ" — MÃ CHƯƠNG,
# MÃ NHÓM CHÍNH, MÃ NHÓM PHỤ 1, MÃ NHÓM PHỤ 2, MÃ LOẠI — trước khi tới MÃ BỆNH, và bốn
# cột bắt đầu bằng "TÊN". So khớp kiểu "bắt đầu bằng" sẽ lấy MÃ CHƯƠNG: bảng còn 22 dòng
# tên chương thay vì 12.218 mã bệnh, mà chương trình vẫn chạy trơn — chỉ có điểm
# candidates lặng lẽ tụt. Danh sách này cũng còn nhận bản cũ (ICD10.csv, cột "Mã").
_ICD10_CODE_COLUMNS = ("mã bệnh", "mã", "ma", "code")
_ICD10_NAME_COLUMNS = ("tên bệnh", "ten benh", "name")

# Prefer ingredient / brand / clinical-drug rows to keep fuzzy search tractable.
_RXNORM_TTYS = {"IN", "BN", "PIN", "MIN", "SCD", "SBD"}
# Gold on the generated set is ingredient CUIs for every coded drug (896/896). Brand and
# product matches therefore have to be walked down to IN before they can score.
_TTY_NEEDS_IN = {"BN", "SBD", "SBDG", "SBDC", "SCD", "SCDG", "SCDC", "SCDF", "GPCK", "BPCK"}

_ROUTE = {
    "po", "iv", "im", "sc", "sq", "sl", "pr", "top", "inh", "ng",
    "pv", "id", "neb", "ophth", "otic", "nasal", "buccal", "rectal",
}
_FREQ = {
    "daily", "bid", "tid", "qid", "qd", "qod", "qhs", "qam", "qpm",
    "prn", "once", "weekly", "monthly", "hs", "ac", "pc", "stat",
}
_FREQ_RE = re.compile(r"^q\d+h$")  # q6h, q8h, q12h…

# Số mã trả về và ngưỡng fuzzy, đo bằng scripts/measure_normalizer.py trên 1.456 mã
# CHẨN_ĐOÁN + 980 mã THUỐC của annotations_gold:
#
#   * Trả MỘT mã thắng trả ba mã ở mọi ngưỡng, vì đáp án gần như luôn chỉ có một mã
#     (1.456/1.536 CHẨN_ĐOÁN, 814/952 THUỐC). candidates chấm bằng J = |giao|/|hợp|, nên
#     ba mã mà đúng một thì J tối đa còn 1/3 — thêm mã là tự hạ điểm chính mình.
#   * Ngưỡng cũ (65 và 70) loại mất 41,6% và 23,2% số mã ĐÚNG mà tra cứu đã tìm ra.
#   * Brand/product → ingredient: gold is IN for every coded drug; leaving a BN CUI
#     (Lasix 202991 vs furosemide 4603) scores 0 even when the name match is perfect.
#
# J trung bình mỗi span (trước bước brand→IN): CHẨN_ĐOÁN ~0.18; THUỐC ~0.31.
DEFAULT_TOP_K = 1
DISEASE_CUTOFF = 60
DRUG_CUTOFF = 55


def normalize_drug_string(text: str) -> str:
    """Drop route/frequency tokens; RxNorm SCD/IN names do not encode them.

    Shared with the entity_linker sketch — keep the token tables in sync if either grows.
    """
    out = []
    for tok in text.lower().split():
        tok = tok.split(":")[0]  # 'q6h:prn' → 'q6h'
        if not tok:
            continue
        if tok in _ROUTE or tok in _FREQ or _FREQ_RE.match(tok):
            continue
        out.append(tok)
    return " ".join(out).strip()


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
        self.rxnorm_tty = {}  # rxcui → tty of the row we matched
        self._to_in = self._load_to_in_cache()
        self._to_in_dirty = False
        self.load_dictionaries()
        import atexit
        atexit.register(self.flush_ingredient_cache)

    def load_dictionaries(self):
        """Tải dictionary mapping từ knowledge base."""
        self._load_rxnorm()
        self._load_icd10()

    @staticmethod
    def _load_to_in_cache() -> dict[str, str]:
        if not _RXNORM_TO_IN_CACHE.is_file():
            return {}
        try:
            data = json.loads(_RXNORM_TO_IN_CACHE.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items() if v}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[WARN] Could not read {_RXNORM_TO_IN_CACHE.name}: {exc}")
            return {}

    def _save_to_in_cache(self) -> None:
        try:
            _RXNORM_TO_IN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _RXNORM_TO_IN_CACHE.write_text(
                json.dumps(self._to_in, ensure_ascii=False, indent=0, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[WARN] Could not write {_RXNORM_TO_IN_CACHE.name}: {exc}")

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
            df["tty"] = df["tty"].fillna("").str.strip().str.upper()
            df = df[df["str"] != ""]

            if "lat" in df.columns:
                df = df[df["lat"].fillna("ENG").str.upper() == "ENG"]
            if "tty" in df.columns:
                filtered = df[df["tty"].isin(_RXNORM_TTYS)]
                if not filtered.empty:
                    df = filtered

            # Prefer IN over brand/product when the same surface string appears twice
            # (e.g. case variants already collapsed by drop_duplicates on str).
            tty_rank = {t: i for i, t in enumerate(["IN", "PIN", "MIN", "SCD", "SBD", "BN"])}
            df = df.assign(_rank=df["tty"].map(lambda t: tty_rank.get(t, 99)))
            df = df.sort_values("_rank").drop_duplicates(subset=["str"], keep="first")
            df = df.drop(columns=["_rank"]).rename(columns={"str": "name"})

            self.rxnorm_df = df.reset_index(drop=True)
            self.rxnorm_dict = dict(
                zip(self.rxnorm_df["name"].str.lower(), self.rxnorm_df["rxcui"])
            )
            self.rxnorm_tty = dict(
                zip(self.rxnorm_df["rxcui"].astype(str), self.rxnorm_df["tty"])
            )
            print(f"[OK] Loaded RxNorm: {len(self.rxnorm_df)} entries from {_RXNORM_PATH.name}")
        except Exception as exc:
            print(f"[WARN] Failed to load RxNorm ({_RXNORM_PATH.name}): {exc}")

    def to_ingredient(self, rxcui: str) -> str:
        """Walk a brand/product CUI down to its ingredient; identity for IN / unknowns."""
        rxcui = str(rxcui).strip()
        if not rxcui:
            return rxcui
        if rxcui in self._to_in:
            return self._to_in[rxcui]

        tty = self.rxnorm_tty.get(rxcui, "")
        if tty == "IN" or tty not in _TTY_NEEDS_IN:
            self._to_in[rxcui] = rxcui
            return rxcui

        resolved = self._fetch_ingredient(rxcui) or rxcui
        self._to_in[rxcui] = resolved
        # Defer disk writes: measure/inference resolve hundreds of CUIs; flushing each
        # one dominates runtime. Call flush_ingredient_cache() when the burst is done.
        self._to_in_dirty = True
        return resolved

    def flush_ingredient_cache(self) -> None:
        if getattr(self, "_to_in_dirty", False):
            self._save_to_in_cache()
            self._to_in_dirty = False

    def _fetch_ingredient(self, rxcui: str) -> str | None:
        """RxNav related?tty=IN — one call per unseen brand/product CUI."""
        try:
            resp = requests.get(
                f"{_RXNAV_BASE}/rxcui/{rxcui}/related.json",
                params={"tty": "IN"},
                timeout=5,
            )
            if resp.status_code != 200:
                return None
            for group in resp.json().get("relatedGroup", {}).get("conceptGroup", []):
                if group.get("tty") != "IN":
                    continue
                props = group.get("conceptProperties") or []
                if props:
                    return str(props[0]["rxcui"])
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return None
        return None

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
        """Trả về list candidates RxNorm (ingredient CUIs)."""
        if not drug_text or drug_text.strip() == "":
            return []

        text_lower = normalize_drug_string(drug_text)
        if not text_lower:
            return []

        raw_codes: list[str] = []

        # Exact match on the cleaned string
        if text_lower in self.rxnorm_dict:
            raw_codes = [self.rxnorm_dict[text_lower]]
        elif not self.rxnorm_df.empty:
            choices = self.rxnorm_df["name"].tolist()
            matches = process.extract(
                text_lower, choices, scorer=fuzz.token_sort_ratio, limit=top_k
            )
            for match, score, idx in matches:
                if score > DRUG_CUTOFF:
                    raw_codes.append(str(self.rxnorm_df.iloc[idx]["rxcui"]))
        else:
            # Fallback: RxNav approximate search when the local table did not load
            try:
                resp = requests.get(
                    f"{_RXNAV_BASE}/rxcui.json",
                    params={"name": text_lower, "search": 2},
                    timeout=5,
                )
                if resp.status_code == 200:
                    ids = resp.json().get("idGroup", {}).get("rxnormId") or []
                    raw_codes = [str(i) for i in ids[:top_k]]
            except requests.RequestException:
                pass

        # Deduplicate after BN/SCD → IN so two product forms of the same drug collapse.
        out: list[str] = []
        seen: set[str] = set()
        for code in raw_codes[:top_k]:
            ingredient = self.to_ingredient(code)
            if ingredient not in seen:
                seen.add(ingredient)
                out.append(ingredient)
        return out[:top_k]

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
