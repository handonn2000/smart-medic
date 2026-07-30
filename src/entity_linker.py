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

Phụ thuộc (phần dense): pip install transformers torch faiss-cpu requests

NOTE: production inference still goes through `src/normalizer.py`. Drug string cleanup
lives there (`normalize_drug_string`); this module keeps the SapBERT / RxNav sketch for
the denser path once it is wired in.
"""
from typing import List, Dict, Optional

import requests

try:
    from normalizer import normalize_drug_string
except ImportError:  # running as a script from repo root
    from src.normalizer import normalize_drug_string  # type: ignore


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
    def __init__(self, model_name="cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR",
                 device="cpu", max_len=25):
        import torch
        from transformers import AutoTokenizer, AutoModel
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(device).eval()
        self.device, self.max_len = device, max_len

    def encode(self, names: List[str], bs=128):
        import numpy as np
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
    def __init__(self, alias_rows: List[Dict], encoder: SapBertEncoder):
        import faiss
        self.codes = [r["code"] for r in alias_rows]
        self.names = [r["name"] for r in alias_rows]
        self.encoder = encoder
        vecs = encoder.encode(self.names)
        self.index = faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(vecs)
        # lexical fallback: char n-gram không phân biệt dấu
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self.lex = self.tfidf.fit_transform(self.names)

    def retrieve(self, mention: str, k=10) -> List[str]:
        import numpy as np
        q = self.encoder.encode([mention])
        _, idx = self.index.search(q, k)
        dense = [self.codes[i] for i in idx[0]]
        # gộp thêm ứng viên lexical để cứu các ca dịch khác biệt lớn
        lq = self.tfidf.transform([mention])
        sims = (self.lex @ lq.T).toarray().ravel()
        lex = [self.codes[i] for i in np.argsort(-sims)[:k]]
        seen, merged = set(), []
        for c in dense + lex:
            if c not in seen:
                seen.add(c)
                merged.append(c)
        return merged

    def link(self, mention: str) -> Optional[str]:
        # top-1. NÊN thêm cross-encoder rerank (kiểu ClinLinker 2 pha) nếu có
        # dữ liệu train cặp (mention, code) — nâng đáng kể top-1.
        cands = self.retrieve(mention, k=10)
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
        code = icd_linker.link(concept["text"])
        return [code] if code else []
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
