import json
import pandas as pd
from rapidfuzz import process, fuzz
import requests
from pathlib import Path

class MedicalNormalizer:
    def __init__(self):
        self.rxnorm_cache = {}
        self.icd10_cache = {}
        self.load_dictionaries()

    def load_dictionaries(self):
        """Tải dictionary mapping (bạn cần chuẩn bị file csv)"""
        # RxNorm (tải từ https://www.nlm.nih.gov/research/umls/rxnorm/ hoặc dùng public subset)
        try:
            self.rxnorm_df = pd.read_csv("data/dicts/rxnorm_vn_mapping.csv")
            self.rxnorm_dict = dict(zip(self.rxnorm_df['name'].str.lower(), 
                                      self.rxnorm_df['rxcui'].astype(str)))
        except:
            self.rxnorm_df = pd.DataFrame()
            print("⚠️ Chưa có file rxnorm_vn_mapping.csv")

        # ICD-10 VN
        try:
            self.icd_df = pd.read_csv("data/dicts/icd10_vn.csv")
            self.icd_dict = dict(zip(self.icd_df['name'].str.lower(), 
                                   self.icd_df['code'].astype(str)))
        except:
            self.icd_df = pd.DataFrame()
            print("⚠️ Chưa có file icd10_vn.csv")

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
            choices = self.rxnorm_df['name'].tolist()
            matches = process.extract(text_lower, choices, scorer=fuzz.token_sort_ratio, limit=top_k)
            candidates = []
            for match, score, idx in matches:
                if score > 70:  # threshold
                    rxcui = str(self.rxnorm_df.iloc[idx]['rxcui'])
                    candidates.append(rxcui)
            return candidates[:top_k]
        
        # Fallback: RxNav API (NLM)
        try:
            resp = requests.get(f"https://rxnav.nlm.nih.gov/REST/drugs.json?name={drug_text}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "drugGroup" in data and "conceptGroup" in data["drugGroup"]:
                    return [c["rxcui"] for c in data["drugGroup"]["conceptGroup"][0].get("conceptProperties", [])][:top_k]
        except:
            pass
        
        return ["UNKNOWN_RXNORM"]

    def normalize_disease(self, disease_text: str, top_k=3):
        """Trả về ICD-10 code"""
        text_lower = disease_text.lower().strip()
        
        if text_lower in self.icd_dict:
            return [self.icd_dict[text_lower]]
        
        if not self.icd_df.empty:
            choices = self.icd_df['name'].tolist()
            matches = process.extract(text_lower, choices, scorer=fuzz.token_sort_ratio, limit=top_k)
            candidates = []
            for match, score, idx in matches:
                if score > 65:
                    code = str(self.icd_df.iloc[idx]['code'])
                    candidates.append(code)
            return candidates[:top_k]
        
        return ["UNKNOWN_ICD10"]

    def normalize_test(self, test_text: str):
        """LOINC hoặc custom cho xét nghiệm"""
        # TODO: Thêm LOINC mapping tương tự
        return ["DEMO_LOINC"]

# ==================== Tích hợp vào Extractor ====================