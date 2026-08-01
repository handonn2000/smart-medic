"""
entity_linker.py — tầng CHUẨN HOÁ (candidates, 0.4 điểm)

Định tuyến theo type:
    THUỐC       -> RxNorm  (RxCUI)   : RxNav findRxcuiByString -> approximateTerm
    CHẨN_ĐOÁN   -> ICD-10           : dense retrieval (SapBERT-multi) + lexical fallback
    TRIỆU_CHỨNG -> []  (bỏ trống -> Jaccard=1 vì GT cũng rỗng)

Chiến thuật bám metric:
  * Luôn phát ra 1 mã tốt nhất cho THUỐC/CHẨN_ĐOÁN. Bỏ trống KHÔNG lợi hơn đoán
    sai (cả hai đều Jaccard=0), nên đã có type thì cứ đoán.
  * Chỉ phát nhiều mã khi thật sự tin có nhiều (Jaccard phạt mã thừa).
  * Triệu chứng: candidates rỗng.

Phụ thuộc (phần dense): pip install transformers torch numpy scikit-learn requests

NOTE: production inference still goes through `src/normalizer.py`. Drug string cleanup
lives there (`normalize_drug_string`); this module keeps the SapBERT / RxNav sketch for
the denser path once it is wired in. Dense top-k uses NumPy matmul (same as FAISS
IndexFlatIP on ~12k ICD rows) — no faiss package required.
"""
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import requests
import torch
from transformers import AutoModel, AutoTokenizer
from sklearn.feature_extraction.text import TfidfVectorizer

try:
    from normalizer import normalize_drug_string
except ImportError:  # running as a script from repo root
    from src.normalizer import normalize_drug_string  # type: ignore

# Prefer the on-disk copy so inference/test does not hit the HF Hub every run.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_SAPBERT = _REPO_ROOT / "models" / "sapbert"
_HF_SAPBERT = "cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR"
DEFAULT_SAPBERT = str(_LOCAL_SAPBERT if _LOCAL_SAPBERT.is_dir() else _HF_SAPBERT)


# ==========================================================================
# 1. RxNorm cho THUỐC
# ==========================================================================

def rxnorm_link(text: str, base="https://rxnav.nlm.nih.gov/REST") -> Optional[str]:
    """Trả về RxCUI (str) hoặc None. Online — dùng khi môi trường chấm có internet.
    Nếu chấm offline: tải RxNorm full (RRF) hoặc chạy RxNav-in-a-box (Docker) rồi
    trỏ `base` vào nó — cùng endpoint, không đổi code."""
    q = normalize_drug_string(text)
    # 1) exact-or-normalized (bỏ qua thứ tự từ, dạng muối, mở rộng viết tắt)
    try:
        r = requests.get(f"{base}/rxcui.json",
                         params={"name": q, "search": 2}, timeout=5).json()
        ids = r.get("idGroup", {}).get("rxnormId")
        if ids:
            return ids[0]
        # 2) approximate (chịu được thừa từ / viết tắt lạ / sai chính tả)
        r = requests.get(f"{base}/approximateTerm.json",
                         params={"term": q, "maxEntries": 1}, timeout=5).json()
        cand = r.get("approximateGroup", {}).get("candidate")
        if cand:
            return cand[0].get("rxcui")
    except requests.RequestException:
        return None
    return None


# ==========================================================================
# 2. ICD-10 cho CHẨN_ĐOÁN — dense retrieval đa ngôn ngữ + lexical fallback
# ==========================================================================
class SapBertEncoder:
    """Bi-encoder đa ngôn ngữ cho biomedical EL. XLM-R nên nuốt tiếng Việt tốt."""
    def __init__(self, model_name=DEFAULT_SAPBERT, device="cpu", max_len=25):
        self.torch = torch
        # local_files_only when loading from models/sapbert — no Hub round-trip.
        local_only = Path(model_name).is_dir()
        self.tok = AutoTokenizer.from_pretrained(model_name, local_files_only=local_only)
        self.model = AutoModel.from_pretrained(
            model_name, local_files_only=local_only
        ).to(device).eval()
        self.device, self.max_len = device, max_len

    def encode(self, names: List[str], bs=128):
        embs = []
        for i in range(0, len(names), bs):
            toks = self.tok(names[i:i + bs], padding="max_length",
                            max_length=self.max_len, truncation=True,
                            return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                cls = self.model(**toks)[0][:, 0, :]     # [CLS] = biểu diễn
            embs.append(cls.cpu().numpy())
        v = np.concatenate(embs, 0).astype("float32")
        v /= (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)  # cosine qua inner-product
        return v


class IcdLinker:
    """alias_rows: list dict {"code","name"} lấy từ Danh mục ICD-10 của Bộ Y tế
    (mỗi mã kèm tên tiếng Việt + tiếng Anh; nhiều alias cho 1 mã đều thêm được)."""

    # Keep #2 only when it is close to #1; drop it when the gap is large or both are weak.
    MARGIN = 0.2
    MIN_SCORE = 0.2

    def __init__(self, alias_rows: List[Dict], encoder: SapBertEncoder):
        self.codes = [r["code"] for r in alias_rows]
        self.names = [r["name"] for r in alias_rows]
        self.encoder = encoder
        # Rows are already L2-normalised by SapBertEncoder.encode, so matmul = cosine.
        self.vecs = encoder.encode(self.names)  # (N, D) float32
        # lexical fallback: char n-gram không phân biệt dấu
        self.tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self.lex = self.tfidf.fit_transform(self.names)

    def retrieve(self, mention: str, k=10) -> List[str]:
        return [code for code, _ in self.retrieve_scored(mention, k=k)]

    def retrieve_scored(self, mention: str, k=10) -> List[tuple]:
        """Top-k ICD codes with similarity scores (dense cosine, else TF-IDF)."""
        q = self.encoder.encode([mention])  # (1, D)
        k = min(k, len(self.codes))
        sims = (self.vecs @ q.T).ravel()    # (N,) inner product == cosine
        idx = np.argpartition(-sims, kth=k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        dense = [(self.codes[i], float(sims[i])) for i in idx]
        # gộp thêm ứng viên lexical để cứu các ca dịch khác biệt lớn
        lq = self.tfidf.transform([mention])
        lex_sims = (self.lex @ lq.T).toarray().ravel()
        lex_idx = np.argsort(-lex_sims)[:k]
        lex = [(self.codes[i], float(lex_sims[i])) for i in lex_idx]
        seen, merged = set(), []
        for c, score in dense + lex:
            if c not in seen:
                seen.add(c)
                merged.append((c, score))
        return merged

    def dense_top_k(self, mention: str, k=2) -> List[tuple]:
        """Top-k unique ICD codes by SapBERT cosine, highest first."""
        q = self.encoder.encode([mention])
        sims = (self.vecs @ q.T).ravel()
        order = np.argsort(-sims)
        out: List[tuple] = []
        seen: set = set()
        for i in order:
            code = self.codes[i]
            if code in seen:
                continue
            seen.add(code)
            out.append((code, float(sims[i])))
            if len(out) >= k:
                break
        return out

    @staticmethod
    def select_by_margin(
        scored: List[tuple],
        margin: float = MARGIN,
        min_score: float = MIN_SCORE,
    ) -> List[tuple]:
        """Always keep #1; keep #2 only if close and not both weak.

        - score1 - score2 > margin  → drop #2
        - both scores < min_score   → keep #1 only
        - otherwise with two cands  → keep both
        """
        if not scored:
            return []
        if len(scored) == 1:
            return scored[:1]

        (c1, s1), (c2, s2) = scored[0], scored[1]
        if s1 < min_score and s2 < min_score:
            return [(c1, s1)]
        if s1 - s2 > margin:
            return [(c1, s1)]
        return [(c1, s1), (c2, s2)]

    def link_candidates(
        self,
        mention: str,
        k=2,
        margin: float = MARGIN,
        min_score: float = MIN_SCORE,
    ) -> List[tuple]:
        """Return up to k (code, score) pairs after the margin rule."""
        return self.select_by_margin(
            self.dense_top_k(mention, k=k), margin=margin, min_score=min_score
        )

    def link(self, mention: str) -> Optional[str]:
        scored = self.link_with_score(mention)
        return scored[0] if scored else None

    def link_with_score(self, mention: str) -> Optional[tuple]:
        """Return (code, score) for the top-1 candidate, or None."""
        cands = self.link_candidates(mention, k=2)
        return cands[0] if cands else None


# ==========================================================================
# 3. Định tuyến theo type
# ==========================================================================
def assign_candidates(concept: Dict, icd_linker: Optional[IcdLinker] = None) -> List[str]:
    t = concept["type"]
    if t == "THUỐC":
        code = rxnorm_link(concept["text"])
        return [code] if code else []
    if t in ("CHẨN_ĐOÁN", "BỆNH") and icd_linker is not None:
        return [code for code, _ in icd_linker.link_candidates(concept["text"])]
    return []                                   # TRIỆU_CHỨNG -> rỗng


# ==========================================================================
# 4. Demo phần thuần Python (chuẩn hoá chuỗi thuốc)
# ==========================================================================
if __name__ == "__main__":
    for s in ["amlodipine 10 mg po daily",
              "acetaminophen 325-650 mg po q6h:prn",
              "clonazepam 0.5 mg po qam:prn",
              "docusate sodium 100 mg po bid",
              "nystatin oral suspension 5 ml po qid:prn"]:
        print(f"{s!r:45} -> {normalize_drug_string(s)!r}")
