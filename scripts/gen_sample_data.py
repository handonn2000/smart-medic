#!/usr/bin/env python3
"""Sinh bệnh án tiếng Việt tổng hợp làm dữ liệu train — bản ĐỘC LẬP cho master.

Khác bản ở nhánh feature: script này KHÔNG phụ thuộc gì ngoài thư viện chuẩn và
hai bảng ban tổ chức đã có sẵn trên master:

    data/knowledge_base/ICD10.csv     (36.689 mã, cột "Mã" + "Tên bệnh")
    data/knowledge_base/RXNORM.csv    (637.977 dòng, lọc tty IN/BN)

Không cần data/kb/, không cần src/smart_medic/, không cần tải dữ liệu ngoài.

CÁCH LÀM — hai nguồn dữ liệu, chung một cách giữ offset đúng tuyệt đối.

A. TỰ SINH (synthetic): code chọn thực thể trước, LLM viết văn quanh chúng.

    1. compose : bốc một bộ thực thể (chẩn đoán/thuốc/triệu chứng/xét nghiệm) theo
                 phân bố đo từ gold, rồi gọi LLM viết bệnh án bọc mỗi cụm trong 〔 〕.
    2. emit    : bóc dấu 〔 〕, offset tính NGAY LÚC BÓC nên không bao giờ lệch.

Thứ tự này là kết quả của một lần đo: cách ngược lại (LLM viết khung có ô trống,
code điền cụm vào) cho 33% câu vô nghĩa về y khoa, vì code điền không biết ràng
buộc ngữ nghĩa mà LLM đã đặt vào câu ("thấy có 〈chướng bụng〉 trong phân").
python scripts/gen_sample_data.py restyle --n 30 --use-api --model gpt-4o
B. DỊCH (translated): lấy bệnh án tiếng Anh thật của mtsamples, dịch sang tiếng
   Việt và bắt LLM bọc luôn thực thể trong 〔TYPE|...〕 NGAY TRONG BẢN DỊCH.

    3. translate : dịch + bọc dấu, bóc dấu để lấy offset, rồi gán mã ICD/RxNorm
                   bằng gazetteer dựng từ chính bảng của ban tổ chức.

Vì sao bọc dấu lúc dịch chứ không dịch xong rồi dò lại vị trí: dò lại phải khớp
chuỗi trên bản dịch, mà tên bệnh trong bảng ICD là tên WHO trang trọng ("Đái tháo
đường không phụ thuộc insulin có biến chứng thận") gần như không bao giờ xuất hiện
nguyên văn trong văn xuôi bệnh án — dò lại cho recall ~0 ở CHẨN_ĐOÁN. Bọc lúc dịch
thì offset tính lúc bóc dấu, sai số bằng 0 theo cách dựng, y hệt đường A.

    python scripts/gen_sample_data.py compose --n 200 --use-api
    python scripts/gen_sample_data.py emit
    python scripts/gen_sample_data.py translate --n 100
    python scripts/gen_sample_data.py verify

Đầu ra ở data/generated_medical_records/{synthetic,translated}/: text/*.txt là văn
bản sạch, annotations/*.json là nhãn, intermediate/ là file trung gian.

compose cần OPENAI_API_KEY khi có --use-api; không có thì nó chỉ ghi ra bộ thực
thể và prompt để bạn tự gọi model nào cũng được, rồi nạp lại bằng --composed FILE.
translate cũng vậy: không có --use-api thì nó ghi prompt ra đĩa, nạp lại bằng
--translated FILE. Đặt OPENAI_BASE_URL nếu dùng endpoint tương thích OpenAI.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import random
import re
import statistics as st
import sys
import unicodedata as ud
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KB = REPO / "data" / "knowledge_base"
EXT = REPO / "data" / "external"

#: Cây thư mục đầu ra. Một gốc duy nhất, tách theo NGUỒN (tự sinh / dịch từ
#: mtsamples) rồi mới tách theo VAI TRÒ (trung gian / văn bản / nhãn) — cách cũ
#: rải ba vai trò ra ba chỗ khác nhau trong data/ nên không nói được thư mục nào
#: thuộc lô nào khi có nhiều nguồn.
BASE_DIR = REPO / "data" / "generated_medical_records"

SYNTHETIC_DIR = BASE_DIR / "synthetic"
SYNTHETIC_WORK = SYNTHETIC_DIR / "intermediate"
SYNTHETIC_TEXT = SYNTHETIC_DIR / "text"
SYNTHETIC_ANNOTATIONS = SYNTHETIC_DIR / "annotations"

TRANSLATED_DIR = BASE_DIR / "translated"
TRANSLATED_WORK = TRANSLATED_DIR / "intermediate"
TRANSLATED_TEXT = TRANSLATED_DIR / "text"
TRANSLATED_ANNOTATIONS = TRANSLATED_DIR / "annotations"

RESTYLED_DIR = BASE_DIR / "restyled"
RESTYLED_WORK = RESTYLED_DIR / "intermediate"
RESTYLED_TEXT = RESTYLED_DIR / "text"
RESTYLED_ANNOTATIONS = RESTYLED_DIR / "annotations"


SEED = 20260727
BRACKET = re.compile(r"〔([^〔〕]{1,80})〕")

#: Dấu bọc thực thể ở đường DỊCH: 〔TYPE|văn bản〕. Khác dấu 〔 〕 trơn của đường
#: tự sinh vì ở đó type đã biết trước (code bốc cụm rồi mới nhờ LLM viết), còn ở
#: đây type do LLM quyết lúc dịch nên phải nằm trong dấu.
BRACKET_TYPED = re.compile(r"〔([^\s|〔〕]{2,24})\|([^〔〕]{1,80})〕")

ENTITY_TYPES = ("CHẨN_ĐOÁN", "TRIỆU_CHỨNG", "THUỐC",
                "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM")

#: LLM viết nhãn bằng ASCII cho chắc (tiếng Việt có dấu trong marker dễ bị nó
#: gõ sai dấu, và một marker sai dấu là một span mất trắng). Bảng này quy đổi
#: lại về đúng tên type của ban tổ chức.
TYPE_ALIASES = {
    "DX": "CHẨN_ĐOÁN", "SYM": "TRIỆU_CHỨNG", "DRUG": "THUỐC",
    "TEST": "TÊN_XÉT_NGHIỆM", "RES": "KẾT_QUẢ_XÉT_NGHIỆM",
}


#: Tần số tên thuốc đo trên 3.612 bệnh án tiếng Anh (mtsamples), nhúng thẳng vào
#: script để master không phụ thuộc file ngoài. Vì sao cần: bảng RxNorm không có
#: tín hiệu độ phổ thông nào (mọi dòng cùng trọng số), nên bốc đều từ 27.537 tên
#: IN/BN cho ra "silicon dioxide", "trientine" — đây là nguyên nhân của 14/90 câu
#: bị chấm 0 điểm ở lô thử. Bảng này chỉ 402 tên và phủ 14/19 thuốc gold, nên cách
#: bốc là TRỘN: 75% theo tần số, 25% từ cả bảng (5 thuốc gold còn lại — bumetanide,
#: eliquis, gleevec, levofloxacin, metoclopramide — chỉ có ở bảng đầy đủ).
DRUG_FREQ = {
    "coumadin": 67, "aspirin": 55, "tylenol": 38, "prednisone": 36, "oxygen": 34, "lasix": 29,
    "lisinopril": 25, "water": 25, "morphine": 24, "albuterol": 23, "levaquin": 23,
    "flomax": 21, "metoprolol": 20, "synthroid": 20, "lipitor": 19, "tomorrow": 19,
    "benadryl": 18, "cocaine": 18, "digoxin": 18, "fentanyl": 18, "hydrochlorothiazide": 17,
    "adderall": 16, "atenolol": 16, "heroin": 16, "phenergan": 16, "amoxicillin": 15,
    "xanax": 15, "bactrim": 14, "clindamycin": 14, "folic acid": 14, "levothyroxine": 14,
    "ambien": 13, "diovan": 13, "hydralazine": 13, "metformin": 13, "percocet": 13,
    "toprol": 13, "advair": 12, "allegra": 12, "barium": 12, "ceftriaxone": 12, "claritin": 12,
    "codeine": 12, "nexium": 12, "omeprazole": 12, "prilosec": 12, "tamoxifen": 12,
    "zocor": 12, "accutane": 11, "ativan": 11, "demerol": 11, "lidocaine": 11, "motrin": 11,
    "vitamin d": 11, "zantac": 11, "cardizem": 10, "ibuprofen": 10, "lantus": 10, "lead": 10,
    "methadone": 10, "paxil": 10, "plavix": 10, "prevacid": 10, "unasyn": 10, "clonidine": 9,
    "doxycycline": 9, "nitroglycerin": 9, "perform": 9, "pravachol": 9, "zithromax": 9,
    "augmentin": 8, "carboplatin": 8, "cipro": 8, "colace": 8, "cozaar": 8, "humulin": 8,
    "keflex": 8, "labetalol": 8, "procainamide": 8, "coreg": 7, "crestor": 7,
    "cyclosporine": 7, "erythromycin": 7, "flagyl": 7, "keppra": 7, "medrol": 7,
    "metronidazole": 7, "protonix": 7, "reglan": 7, "simvastatin": 7, "verapamil": 7,
    "vitamin k": 7, "zyrtec": 7, "abilify": 6, "aciphex": 6, "advil": 6, "buspar": 6,
    "cialis": 6, "compazine": 6, "cortisone": 6, "epinephrine": 6, "hydrea": 6, "lamictal": 6,
    "nasonex": 6, "norvasc": 6, "plaquenil": 6, "prinivil": 6, "ritalin": 6, "seroquel": 6,
    "solu-medrol": 6, "vancomycin": 6, "xopenex": 6, "zonegran": 6, "ciprodex": 5,
    "dilantin": 5, "femara": 5, "fosamax": 5, "furosemide": 5, "heparin": 5, "iodine": 5,
    "lamisil": 5, "lanoxin": 5, "lotensin": 5, "lotrimin": 5, "miralax": 5, "morning after": 5,
    "neurontin": 5, "pepcid": 5, "provera": 5, "singulair": 5, "vitamin e": 5, "warfarin": 5,
    "wellbutrin": 5, "zetia": 5, "actonel": 4, "actos": 4, "arimidex": 4, "betadine": 4,
    "cardura": 4, "carvedilol": 4, "celebrex": 4, "chlorthalidone": 4, "decadron": 4,
    "detrol": 4, "doripenem": 4, "elidel": 4, "enalapril": 4, "famotidine": 4, "fiber": 4,
    "gabapentin": 4, "hydrocodone": 4, "hydroxychloroquine": 4, "imuran": 4, "klonopin": 4,
    "lexapro": 4, "lithium": 4, "lovastatin": 4, "lupron": 4, "lyrica": 4, "macrodantin": 4,
    "marcaine": 4, "methotrexate": 4, "nystatin": 4, "phenobarbital": 4, "premarin": 4,
    "propofol": 4, "proscar": 4, "restart": 4, "rocaltrol": 4, "soma": 4, "tetracycline": 4,
    "timoptic": 4, "trazodone": 4, "vesicare": 4, "viagra": 4, "vitamin b12": 4, "zoloft": 4,
    "amlodipine": 3, "aricept": 3, "atrovent": 3, "bactroban": 3, "benicar": 3, "caffeine": 3,
    "carafate": 3, "carnitine": 3, "cephalexin": 3, "cymbalta": 3, "ditropan": 3, "enablex": 3,
    "escherichia coli": 3, "evista": 3, "feldene": 3, "feosol": 3, "ferrous sulfate": 3,
    "glyburide": 3, "humalog": 3, "isordil": 3, "lactulose": 3, "latex": 3, "lopressor": 3,
    "loratadine": 3, "lovenox": 3, "lumigan": 3, "lutein": 3, "macrobid": 3, "minipress": 3,
    "naprosyn": 3, "oxycodone": 3, "pacerone": 3, "polysporin": 3, "procrit": 3,
    "pulmicort": 3, "qvar": 3, "remeron": 3, "senokot": 3, "tandem": 3, "temodar": 3,
    "tramadol": 3, "valtrex": 3, "zanaflex": 3, "abraxane": 2, "adriamycin": 2, "afrin": 2,
    "aldactone": 2, "allopurinol": 2, "alprazolam": 2, "altace": 2, "antivert": 2,
    "aquaphor": 2, "aranesp": 2, "arava": 2, "atripla": 2, "avalide": 2, "avapro": 2,
    "avelox": 2, "azithromycin": 2, "bayer aspirin": 2, "bumex": 2, "cefazolin": 2,
    "cefuroxime": 2, "cellcept": 2, "cetacaine": 2, "chantix": 2, "cimetidine": 2,
    "ciprofloxacin": 2, "cisplatin": 2, "citronella oil": 2, "cleocin": 2, "collagen": 2,
    "copaxone": 2, "cutivate": 2, "depakote": 2, "depo-provera": 2, "dexamethasone": 2,
    "dicyclomine": 2, "diphenhydramine": 2, "diprivan": 2, "dyazide": 2, "effexor": 2,
    "enoxaparin": 2, "estrace": 2, "etoposide": 2, "flonase": 2, "flovent": 2, "fortaz": 2,
    "gemfibrozil": 2, "glipizide": 2, "glucotrol": 2, "helicobacter pylori": 2, "holmium": 2,
    "hydrocortisone": 2, "hydromorphone": 2, "imodium": 2, "indocin": 2, "invega": 2,
    "isoproterenol": 2, "ixempra": 2, "kenalog": 2, "kerosene": 2, "lomotil": 2, "lopid": 2,
    "lotrel": 2, "maxzide": 2, "metamucil": 2, "mirapex": 2, "mobic": 2, "namenda": 2,
    "nitrofurantoin": 2, "norco": 2, "novolin": 2, "orapred": 2, "paraffin": 2, "peridex": 2,
    "pravastatin": 2, "proctofoam": 2, "propranolol": 2, "proventil": 2, "provigil": 2,
    "react": 2, "rhinocort": 2, "rozerem": 2, "serevent": 2, "spiriva": 2, "spironolactone": 2,
    "synalar": 2, "tazorac": 2, "tekturna": 2, "timolol": 2, "topamax": 2, "triamcinolone": 2,
    "triamterene": 2, "tussionex": 2, "ultram": 2, "uric acid": 2, "valium": 2, "vasotec": 2,
    "vytorin": 2, "welchol": 2, "acyclovir": 1, "alendronate": 1, "alphagan": 1, "amaryl": 1,
    "amitriptyline": 1, "anaprox": 1, "apple juice": 1, "aromasin": 1, "atropine": 1,
    "avastin": 1, "benzoyl peroxide": 1, "botox": 1, "brimonidine": 1, "caduet": 1,
    "caverject": 1, "celexa": 1, "citalopram": 1, "clarinex": 1, "clavulanate": 1,
    "climara": 1, "clonazepam": 1, "clopidogrel": 1, "colestid": 1, "combivent": 1,
    "condylox": 1, "cyclobenzaprine": 1, "daypro": 1, "depo-medrol": 1, "depo-testosterone": 1,
    "desmopressin": 1, "diclofenac": 1, "diflucan": 1, "digitek": 1, "docusate": 1,
    "doxorubicin": 1, "elavil": 1, "equagesic": 1, "faslodex": 1, "fenofibrate": 1,
    "fluoxetine": 1, "gengraf": 1, "glucophage": 1, "haloperidol": 1, "hyzaar": 1,
    "ixabepilone": 1, "kadian": 1, "levitra": 1, "lidoderm": 1, "lorazepam": 1, "malarone": 1,
    "meloxicam": 1, "micardis": 1, "minocin": 1, "mucinex": 1, "nasacort": 1, "nicotine": 1,
    "nifedipine": 1, "novolog": 1, "octreotide": 1, "oxaprozin": 1, "paroxetine": 1,
    "pediarix": 1, "phenylpropanolamine": 1, "phoslo": 1, "pred forte": 1, "prograf": 1,
    "prozac": 1, "raloxifene": 1, "ranitidine": 1, "ropinirole": 1, "skelaxin": 1,
    "staphylococcus epidermidis": 1, "sudafed": 1, "tacrolimus": 1, "theophylline": 1,
    "trimethoprim": 1, "tums": 1, "valganciclovir": 1, "varivax": 1, "vicoprofen": 1,
    "vitamin b6": 1, "vitamin d3": 1, "xylocaine": 1, "ziac": 1,
}

#: Phân bố chương ICD trong gold (203 mã). Seed thì gần như đều mọi chương, nên bốc
#: đều sẽ sinh ra bệnh cảnh lệch: 80 mã chương O (sản khoa) gán bừa cho bệnh nhân nam
#: là nguồn câu vô nghĩa lớn nhất đo được ở cách cũ.
GOLD_CHAPTERS = {
    "I": 43, "K": 40, "E": 32, "A": 27, "D": 23, "J": 19, "N": 13, "C": 12,
    "M": 11, "L": 10, "F": 8, "S": 7, "G": 6, "B": 5, "Q": 3, "H": 3,
    "P": 1, "T": 1, "O": 1,
}

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

#: Alias ICD phải bỏ: chúng là MẢNH VỠ của việc tách tên theo dấu phẩy, không
#: phải tên bệnh. Q41 tên đầy đủ là "Không có, tịt và hẹp ruột non bẩm sinh" —
#: tách ra thì mảnh đầu là "Không có", và nó khớp mọi câu phủ định trong bệnh án.
#: Đo trên 5 bản dịch thử: "Không có" bị gán CHẨN_ĐOÁN + mã Q41 sáu lần trong
#: hai tài liệu, nhiều hơn bất kỳ chẩn đoán thật nào.
ICD_STOP = {
    "không có", "không rõ", "không đặc hiệu", "không xác định", "chưa xác định",
    "biến chứng", "biến chứng khác", "tổn thương", "tổn thương khác",
    "di chứng", "bệnh khác", "các bệnh khác", "rối loạn khác", "nguyên nhân khác",
    "căng thẳng", "tình trạng khác", "bệnh lý khác", "khối u", "triệu chứng",
    "dấu hiệu", "hội chứng khác", "nhiễm trùng khác", "biểu hiện khác",
}

#: Dấu phủ định, đo trên 41 span isNegated của gold: "phủ nhận" 18 lần (nhiều
#: nhất), "không ..." 12, "không có" 2, "không phải"/"không kèm" 1, viết tắt "k" 2.
#: "Chưa ghi nhận" không xuất hiện lần nào ở gold nhưng giữ vì có trong test.
NEG_CUES = ("Không ", "Không có ", "Không kèm ", "Không phải ",
            "Phủ nhận ", "Chưa ghi nhận ")

# Section có ngữ cảnh assertion — đo từ gold: mọi span trong "Thuốc trước khi
# nhập viện" và "Các bệnh lý mạn tính" đều mang isHistorical.
#: Dạng viết tắt ("TS:", "TS gia đình:") có từ khi thêm bước restyle: thể loại
#: bệnh án chép tay ghi tiêu đề cụt, và bệnh án thật của đề thi cũng vậy. Không
#: có mấy dòng này thì toàn bộ isHistorical/isFamily của thể loại đó mất trắng.
HIST_SECTIONS = (
    "Tiền sử bệnh", "Thuốc trước khi nhập viện", "Các bệnh lý mạn tính",
    "Tiền sử bệnh nội khoa", "Các thủ thuật đã thực hiện",
    "Tiền sử", "TS bệnh", "TS nội khoa", "TS",
)

FAMILY_SECTIONS = ("Tiền sử gia đình", "TS gia đình", "TS GĐ", "Tiền sử GĐ")

#: Prompt viết bệnh án. Ký tự 〔 〕 chọn vì không có trong bảng BTC lẫn chữ tiếng
#: Việt, nên bóc lại không nhập nhằng.
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
   mục Chẩn đoán và các bệnh còn lại vào Tiền sử bệnh. LUÔN viết được; đừng từ chối.
8. Ở mục Tiền sử bệnh, viết 1-2 câu phủ định mở đầu bằng "Phủ nhận" hoặc "Không có",
   và các cụm bị phủ định PHẢI LÀ CỤM LẤY TỪ DANH SÁCH, bọc 〔 〕, nằm cùng câu với
   từ phủ định và trước dấu chấm kết câu. Đúng:
       Phủ nhận tiền sử 〔viêm phổi〕 và 〔đái tháo đường type 2〕.
   Sai: "Phủ nhận tiền sử tai biến mạch máu não." (bệnh này không có trong danh
   sách nên không bọc được, câu thành vô ích). 4,2% span của bệnh án thật là phủ
   định, và "phủ nhận" là cách viết phổ biến nhất — 18/41 lần."""


# --------------------------------------------------------------- đọc bảng BTC

def load_icd(min_words: int = 2, max_words: int = 5) -> list[dict]:
    """Đọc data/knowledge_base/ICD10.csv -> [{code, alias}].

    File có 5 dòng tiêu đề trang trước header thật (dòng bắt đầu bằng "STT,Mã"),
    và mã hoá lẫn lộn nên đọc với errors="replace".

    Lọc alias 2-5 từ: span CHẨN_ĐOÁN của gold dài TB 4,05 từ, tên ICD một từ thì
    quá chung ("Sốc", "Ngất") còn trên 5 từ thì gần như không xuất hiện nguyên văn
    trong bệnh án thật.
    """
    path = KB / "ICD10.csv"
    if not path.exists():
        sys.exit(f"thiếu {path.relative_to(REPO)} — bảng ICD của ban tổ chức")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = next((i for i, l in enumerate(lines) if l.startswith("STT,Mã")), 0)
    rows = csv.DictReader(lines[head:])
    out, seen = [], set()
    for row in rows:
        code = (row.get("Mã") or "").strip()
        name = (row.get("Tên bệnh ") or row.get("Tên bệnh") or "").strip()
        if not code or not name or (row.get("Hiệu lực") or "").strip() == "Không":
            continue
        # Tên nhiều mảnh ngăn bằng dấu phẩy. Mảnh ĐẦU gần như luôn là tên bệnh
        # ("Tabes sống lưng"), mảnh SAU thì 5.796/5.918 là bổ ngữ chứ không phải
        # tên riêng: "không đặc hiệu", "gãy kín", "mức độ chưa xác định". Phân biệt
        # bằng chữ đầu: mảnh sau viết HOA (122 cái, "Parkinson do giang mai") mới là
        # biến thể tên thật. Giữ hết mảnh sau thì 12% alias là bổ ngữ vô nghĩa.
        pieces = re.split(r"\s*[,;]\s*", name)
        for idx_p, alias in enumerate(pieces):
            alias = alias.strip(" .")
            if idx_p and not alias[:1].isupper():
                continue
            n_words = len(alias.split())
            if not (min_words <= n_words <= max_words) or len(alias) < 6:
                continue
            key = alias.lower()
            if key in seen or key in ICD_STOP:
                continue
            seen.add(key)
            out.append({"code": code, "alias": alias})
    return out


#: Bảng RxNorm đầy đủ (RxNorm_full_*/rrf/RXNREL.RRF) — quan hệ giữa các khái niệm.
#: RXNORM.csv mà repo đang dùng chỉ là RXNCONSO (tên gọi), không có quan hệ nào.
RXNREL_GLOB = "RxNorm_full_*/rrf/RXNREL.RRF"
BRAND_MAP_CACHE = KB / "brand_to_ingredient.json"


def load_brand_to_ingredient(rebuild: bool = False) -> dict[str, list[str]]:
    """Bảng biệt dược -> hoạt chất, dựng từ RXNREL.RRF.

    VÌ SAO CẦN: đo trên 20 file gold của ban tổ chức, 16/16 span THUỐC có mã đều
    mang mã HOẠT CHẤT (tty=IN) — 'levothyroxine' 10582, 'omeprazole' 7646 — không
    một mã biệt dược nào. Trong khi dữ liệu sinh ra hiện tại có 475/890 span mang
    mã biệt dược (tty=BN): 'Synthroid' 224920 thay vì 10582, 'Lipitor' 153165 thay
    vì 83367. Cùng một thuốc, khác quy ước mã — dạy model trả sai loại mã.

    RXNCONSO (tức RXNORM.csv) KHÔNG nối được hai thứ đó: nó chỉ có tên gọi, quan hệ
    tradename_of nằm ở RXNREL.RRF của bản full. Đây là lý do cần bản full.

    Dòng RRF đọc theo chiều RXCUI2 --RELA--> RXCUI1, nên 'tradename_of' cho ta
    RXCUI2 (biệt dược) -> RXCUI1 (hoạt chất). Kiểm bằng ca đã biết: Lipitor 153165
    -> 83367 (atorvastatin), Synthroid 224920 -> 10582 (levothyroxine, đúng bằng
    mã gold gán cho 'levothyroxine').

    File RXNREL.RRF nặng ~530 MB nên kết quả được cache lại; xoá cache để dựng lại.
    """
    if BRAND_MAP_CACHE.exists() and not rebuild:
        return json.loads(BRAND_MAP_CACHE.read_text(encoding="utf-8"))
    src = next(iter(sorted(KB.glob(RXNREL_GLOB))), None)
    if src is None:
        return {}
    print(f"  dựng bảng biệt dược->hoạt chất từ {src.name} (chỉ lần đầu)...")
    fwd: dict[str, set] = collections.defaultdict(set)
    with src.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            f = line.split("|")
            if len(f) < 12 or f[10] != "RXNORM" or f[2] != "CUI" or f[6] != "CUI":
                continue
            if f[7] == "tradename_of":
                fwd[f[4]].add(f[0])
            elif f[7] == "has_tradename":
                fwd[f[0]].add(f[4])
    out = {k: sorted(v) for k, v in fwd.items() if v}
    BRAND_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BRAND_MAP_CACHE.write_text(json.dumps(out), encoding="utf-8")
    print(f"  {len(out)} biệt dược có hoạt chất -> {BRAND_MAP_CACHE.relative_to(REPO)}")
    return out


def load_rxnorm(max_words: int = 5, map_brands: bool = True) -> list[dict]:
    """Đọc data/knowledge_base/RXNORM.csv -> [{rxcui, alias}], chỉ tty IN/BN.

    IN = hoạt chất, BN = biệt dược. Đo trên gold: 13/13 thuốc tra được trong bảng
    đều thuộc đúng hai loại này; các tty khác (SCD, DP, PSN...) là dạng bào chế
    đầy đủ kiểu "Tremfya 100 MG/ML Auto-Injector", không phải cách bệnh án viết.
    """
    path = KB / "RXNORM.csv"
    if not path.exists():
        sys.exit(f"thiếu {path.relative_to(REPO)} — bảng RxNorm của ban tổ chức")
    out, seen = [], set()
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("tty") or "").strip() not in ("IN", "BN"):
                continue
            if (row.get("suppress") or "").strip() not in ("", "N"):
                continue
            alias = (row.get("str") or "").strip()
            rxcui = (row.get("rxcui") or "").strip()
            # 5.802/23.355 tên trong bảng viết HOA hết ("WARTICIDE", "HEPARIN") —
            # bệnh án không viết vậy: chỉ 1/102 span THUỐC của gold viết HOA hết.
            # Giữ nguyên chuỗi ngắn (E.E.S., BCG) vì đó là viết tắt thật.
            if alias.isupper() and len(alias) > 4:
                alias = alias.title()
            if not alias or not rxcui or not (4 <= len(alias) <= 40):
                continue
            if len(alias.split()) > max_words or alias.lower() in DRUG_STOP:
                continue
            key = alias.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"rxcui": rxcui, "alias": alias})

    # "codes" là mã ĐEM ĐI GÁN NHÃN, "rxcui" giữ mã gốc để verify còn tra được dữ
    # liệu sinh ra từ trước. Biệt dược phối hợp (Augmentin, Hyzaar...) cho ra nhiều
    # hoạt chất thì gán hết: chúng đều là hoạt chất thật của thuốc đó, và 20 file
    # gold không có ca phối hợp nào để suy ra quy ước, nên không đoán bừa lấy một.
    brands = load_brand_to_ingredient() if map_brands else {}
    for row in out:
        row["codes"] = brands.get(row["rxcui"]) or [row["rxcui"]]
    return out


def common_drugs(rx: list[dict]) -> list[dict]:
    """Lọc theo bảng tần số nhúng sẵn (DRUG_FREQ)."""
    return [r for r in rx if r["alias"].lower() in DRUG_FREQ]

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
                       "candidates": list(pick["codes"])})
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
        # Cụm là mảnh vỡ của tên ICD ("Không xác định", "Nhiễm trùng khác") thì
        # bỏ NHÃN nhưng giữ CHỮ: nó vẫn nằm trong câu LLM đã viết, chỉ là không
        # phải chẩn đoán nên không được gán mã. Xem ICD_STOP.
        if item is not None and surface.lower() in ICD_STOP:
            item = None
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

#: Đầu dòng dạng danh sách: "3. ", "3) ", "- ", "•", và tổ hợp lồng nhau.
LIST_MARKER = re.compile(r"^[\s>]*(?:(?:\d+|[a-zA-Z])[.)]\s*|[-–—•*+]\s*)+")


def strip_list_marker(head: str) -> str:
    """Bỏ số thứ tự / gạch đầu dòng khỏi tiêu đề mục.

    Cần từ khi có bước restyle: thể loại dàn ý viết tiêu đề là "3. Tiền sử gia đình:",
    và so khớp thẳng thì startswith("Tiền sử gia đình") sai — đo trên lô restyle đầu,
    TOÀN BỘ isFamily/isHistorical bị mất, tỉ lệ span có assertion tụt còn 6%.
    """
    return LIST_MARKER.sub("", head).strip()


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
    # {2,40} chứ không {3,40}: tiêu đề viết tắt "TS:" chỉ 2 ký tự. Đánh đổi là các
    # dòng đo đạc kiểu "M: 82 ck/ph" cũng bị coi là tiêu đề và che mất tiêu đề mục
    # thật phía trên — nhưng che thì ra assertion RỖNG, tức nhãn thiếu chứ không sai.
    for m in re.finditer(r"(?m)^([^\n:]{2,40}):", text[:offset]):
        head = strip_list_marker(m.group(1))
    if any(head.startswith(h) for h in FAMILY_SECTIONS):
        out.append("isFamily")
    elif any(head.startswith(h) for h in HIST_SECTIONS):
        out.append("isHistorical")

    before = line[:offset - line_start].lower()
    if any(re.search(cue.strip().lower() + r"\b[^.;]{0,30}$", before) for cue in NEG_CUES):
        out.append("isNegated")
    return out

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


# --------------------------------------------------------------- hậu xử lý

def postprocess(rng: random.Random, text: str, records: list[dict], args
                ) -> tuple[str, list[dict]] | tuple[None, None]:
    """Chèn hai bẫy đo được trên test, rồi suy assertion.

    KHÁC bản ở nhánh feature: bản này KHÔNG hấp thu chỗ lọt (đoạn LLM tự viết ra
    một tên bệnh có trong bảng nhưng không nằm trong bộ thực thể). Hấp thu cần
    dựng matcher trên toàn bộ alias ICD, chậm và không cần cho việc sinh văn bản
    mẫu. Hệ quả: nhãn có thể THIẾU vài span (false negative), không bao giờ SAI.
    """
    # bẫy ***: đo trên test — 30/100 file có ít nhất một cụm bị che, và span bị
    # che thì candidates phải rỗng vì không tra được mã từ chuỗi dấu sao.
    kept: list[dict] = []
    shift = 0
    for rec in sorted(records, key=lambda r: r["position"]):
        s, e = rec["position"][0] + shift, rec["position"][1] + shift
        if rec["type"] == "THUỐC" and rng.random() < args.mask_rate:
            masked = "*" * (e - s)
            text = text[:s] + masked + text[e:]
            kept.append({**rec, "text": masked, "candidates": [],
                         "position": [s, s + len(masked)]})
        else:
            kept.append({**rec, "position": [s, e]})
    records = kept

    for rec in records:
        rec["assertions"] = assertions_at(text, rec["position"][0])
        s, e = rec["position"]
        if text[s:e] != rec["text"]:
            return None, None

    # bẫy NFD: đo trên test — 20/100 file không ở dạng NFC. Phải chuẩn hoá cả text
    # của từng span, không chỉ văn bản: tìm chuỗi NFC trong văn bản NFD luôn hỏng.
    if rng.random() < args.nfd_rate:
        text_nfd = ud.normalize("NFD", text)
        shifted = reindex(text_nfd, [{**r, "text": ud.normalize("NFD", r["text"])}
                                     for r in records])
        if shifted is None:
            return None, None
        text, records = text_nfd, shifted
    return text, records


# =========================================================== ĐƯỜNG DỊCH mtsamples
# ------------------------------------------------------- nguồn bệnh án tiếng Anh

#: Thứ tự ưu tiên khi bốc theo danh mục. Đây là các chuyên khoa nội có bệnh cảnh
#: gần với test của ban tổ chức nhất; các spec còn lại trong file (Surgery, Office
#: Notes, Letters...) vẫn dùng được nhưng xếp sau, xem MTSAMPLES_EXTRA.
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

#: Danh mục bù khi 8 danh mục trên không đủ số bản cần: file chỉ có 457 note và
#: phân bố rất lệch (Endocrinology 4 note, Cardiovascular 39). Không có bảng bù
#: này thì `translate --n 100` chỉ ra ~76 bản.
MTSAMPLES_EXTRA = [
    "Consult - History and Phy.",
    "SOAP / Chart / Progress Notes",
    "Emergency Room Reports",
    "Discharge Summary",
    "Urology",
    "Pediatrics - Neonatal",
    "Obstetrics / Gynecology",
    "Rheumatology",
    "Dermatology",
    "ENT - Otolaryngology",
    "Psychiatry / Psychology",
    "Podiatry",
    "Bariatrics",
    "Ophthalmology",
    "Allergy / Immunology",
    "Surgery",
]

#: Prefix ngắn cho tên file. Tên spec có dấu cách, gạch và dấu chấm nên không
#: dùng thẳng làm tên file được.
CATEGORY_PREFIXES = {
    "Cardiovascular / Pulmonary": "cardio",
    "Gastroenterology": "gastro",
    "Neurology": "neuro",
    "Orthopedic": "ortho",
    "Nephrology": "nephro",
    "Endocrinology": "endo",
    "General Medicine": "general",
    "Hematology - Oncology": "hemato",
    "Consult - History and Phy.": "consult",
    "SOAP / Chart / Progress Notes": "soap",
    "Emergency Room Reports": "emerg",
    "Discharge Summary": "discharge",
    "Urology": "uro",
    "Pediatrics - Neonatal": "peds",
    "Obstetrics / Gynecology": "obgyn",
    "Rheumatology": "rheum",
    "Dermatology": "derma",
    "ENT - Otolaryngology": "ent",
    "Psychiatry / Psychology": "psych",
    "Podiatry": "podia",
    "Bariatrics": "bariat",
    "Ophthalmology": "ophtha",
    "Allergy / Immunology": "allergy",
    "Surgery": "surg",
}

#: Tiêu đề mục trong mtsamples. File dùng dạng NỐI LIỀN bằng dấu phẩy chứ không
#: xuống dòng — ",HISTORY OF PRESENT ILLNESS: , The patient is a 52-year-old..." —
#: nên mẫu tách mục phải neo vào dấu phẩy/đầu chuỗi, không neo vào "\n" như bệnh
#: án đã format sẵn.
MTS_SECTION = re.compile(r"(?:^|[,.])\s*([A-Z][A-Z0-9 /&'\-]{2,40}):\s*,?\s*")


def parse_mtsamples_sections(text: str) -> dict[str, str]:
    """Tách bệnh án mtsamples thành {TÊN MỤC: nội dung}.

    Mục thường gặp: REASON FOR VISIT, HISTORY OF PRESENT ILLNESS, ALLERGIES,
    MEDICATIONS, PAST MEDICAL HISTORY, REVIEW OF SYSTEMS, PHYSICAL EXAMINATION,
    LABORATORY DATA, IMPRESSION, PLAN. Không tách được mục nào thì trả về toàn
    bộ văn bản dưới khoá rỗng để bước sau vẫn dịch được.
    """
    marks = list(MTS_SECTION.finditer(text))
    if not marks:
        return {"": text.strip()}
    sections: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip().strip(",").strip()
        if body:
            sections[m.group(1).strip()] = body
    return sections


def normalize_mtsamples_text(text: str) -> str:
    """Đưa bệnh án mtsamples về dạng mỗi mục một khối, tiêu đề chiếm trọn dòng.

    Bản gốc nhồi cả bệnh án vào một dòng dài ngăn bằng dấu phẩy. Đưa cho LLM dịch
    nguyên dạng đó thì bản dịch cũng ra một khối liền — mà `verify` đo tỉ lệ file
    có dòng tiêu đề mục (test 67%), và `assertions_at` phải dò ngược tiêu đề mục
    gần nhất để suy isHistorical/isFamily. Không có tiêu đề thì cả hai đều hỏng.
    """
    out = []
    for head, body in parse_mtsamples_sections(text).items():
        body = re.sub(r"\s*,\s*(?=\d+\.\s)", "\n", body)   # ",1. ESRD" -> xuống dòng
        # tiểu mục trong thân bài, cả dạng HOA HẾT ("HEART:") lẫn dạng Hoa Đầu Từ
        # ("Vital Signs:") — mtsamples nối chúng bằng dấu phẩy vào câu trước
        body = re.sub(r"[ \t]*[.,][ \t]*(?=(?:[A-Z]{2,}[A-Z /]*|[A-Z][a-z]+(?: [A-Za-z]+){0,3}):)",
                      "\n", body)
        body = re.sub(r"\.[ \t]*,[ \t]*", ". ", body)      # ".,O2 saturation" -> ". O2..."
        body = re.sub(r"[ \t]{2,}", " ", body).strip()
        out.append(f"{head}:\n{body}" if head else body)
    return "\n\n".join(out)


def fetch_mtsamples(categories: list[str], n_per_cat: int = 15,
                    source: str = "auto", rng: random.Random | None = None,
                    total: int | None = None, min_lab: int = 0) -> list[dict]:
    """Nạp bệnh án tiếng Anh từ kho mtsamples đã lọc sẵn của repo.

    KHÔNG crawl mtsamples.com: repo đã có sẵn 457 note đã lọc ở
    data/external/en_notes/mtsamples_filtered.jsonl (trường: id, src, spec, text),
    chính là kho đã dùng để đo bảng DRUG_FREQ ở đầu file. Crawl lại vừa thừa vừa
    phải xử lý robots.txt, và sẽ cho ra kho khác với kho các hằng số này đo trên.

    Bốc đều theo danh mục để bản dịch phủ nhiều chuyên khoa; danh mục nào thiếu
    thì bù từ MTSAMPLES_EXTRA cho đủ `total`.

    Trong mỗi danh mục, note NHIỀU XÉT NGHIỆM được ưu tiên (trường n_lab có sẵn
    trong kho). Lý do đo được ở lô thử 5 bản: 310/457 note của kho là ghi chú tái
    khám, KHÔNG có trị số xét nghiệm nào — bốc ngẫu nhiên trúng toàn loại đó thì
    KẾT_QUẢ_XÉT_NGHIỆM chỉ ra 4 span/5 tài liệu, không phải vì đánh dấu sót mà vì
    bản gốc không có gì để đánh dấu. Ngẫu nhiên vẫn giữ ở các note cùng mức n_lab.
    """
    rng = rng or random.Random(SEED)
    path = Path(source) if source != "auto" else EXT / "en_notes" / "mtsamples_filtered.jsonl"
    if not path.exists():
        sys.exit(f"thiếu {path} — khôi phục bằng:\n"
                 f"  git show bd6c440:data/external/en_notes/mtsamples_filtered.jsonl"
                 f" > {path}")

    by_spec: dict[str, list[dict]] = collections.defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        note = json.loads(line)
        if note.get("text") and note.get("n_lab", 0) >= min_lab:
            by_spec[note.get("spec", "")].append(note)
    for notes in by_spec.values():
        rng.shuffle(notes)                       # ngẫu nhiên trong cùng mức n_lab
        notes.sort(key=lambda r: -r.get("n_lab", 0))   # sort ổn định: giữ thứ tự trên

    taken: list[dict] = []
    seen: set[str] = set()

    def take(spec: str, k: int) -> None:
        for note in by_spec.get(spec, []):
            if k <= 0 or (total is not None and len(taken) >= total):
                return
            if note["id"] in seen:
                continue
            seen.add(note["id"])
            taken.append({"id": note["id"], "category": spec,
                          "text": normalize_mtsamples_text(note["text"])})
            k -= 1

    for spec in categories:
        take(spec, n_per_cat)
    # bù cho đủ số: vòng đầu vét nốt các danh mục chính, vòng sau lấy danh mục phụ
    if total is not None:
        for spec in list(categories) + MTSAMPLES_EXTRA + sorted(by_spec):
            if len(taken) >= total:
                break
            take(spec, total - len(taken))
    return taken


# --------------------------------------------------- gazetteer tra mã ICD/RxNorm

#: Tách từ để dò cụm: giữ chữ có dấu tiếng Việt (\w với re.UNICODE), giữ số, và
#: nối các mảnh ngăn bằng gạch nối ("LDL-cholesterol" là MỘT từ, không phải hai).
TOKEN_RE = re.compile(r"\w+(?:[-'’]\w+)*", re.UNICODE)


def norm_token(tok: str) -> str:
    return ud.normalize("NFC", tok).casefold()


class Gazetteer:
    """Dò cụm nhiều từ trong văn bản, khớp dài nhất thắng.

    Đánh chỉ mục theo TỪ ĐẦU của cụm chứ không ghép một regex khổng lồ: bảng ICD
    cho ~40k alias, một regex alternation cỡ đó biên dịch rất chậm và dò còn chậm
    hơn. Với chỉ mục theo từ đầu thì mỗi vị trí trong văn bản chỉ phải thử vài
    alias cùng từ mở đầu.
    """

    def __init__(self, entries: list[tuple[str, dict]], sub_index: bool = False):
        self.index: dict[str, list[tuple[tuple[str, ...], dict]]] = {}
        self.exact: dict[tuple[str, ...], dict] = {}
        #: Chỉ mục CỤM CON: mọi đoạn liền ≥2 từ của alias -> alias ngắn nhất chứa nó.
        #: Cần vì bảng ICD ghi tên trang trọng còn bác sĩ viết tên gọn: bảng có
        #: "Bệnh lý tăng huyết áp" (I10), bệnh án viết "Tăng huyết áp" — không có
        #: chỉ mục này thì chẩn đoán phổ biến nhất trong bệnh án lại không có mã.
        self.sub: dict[tuple[str, ...], tuple[int, str, dict]] = {}
        for alias, payload in entries:
            toks = tuple(norm_token(t) for t in TOKEN_RE.findall(alias))
            if not toks:
                continue
            self.index.setdefault(toks[0], []).append((toks, payload))
            self.exact.setdefault(toks, payload)
            if not sub_index:
                continue
            key_code = payload.get("code") or (payload.get("codes") or [""])[0]
            rank = (len(toks), key_code)
            for i in range(len(toks)):
                for j in range(i + 2, len(toks) + 1):
                    piece = toks[i:j]
                    if piece == toks:
                        continue
                    cur = self.sub.get(piece)
                    # alias NGẮN NHẤT thắng: nó là tên chung nhất chứa cụm này,
                    # alias dài hơn là biến thể có thêm bổ ngữ mà bệnh án không viết
                    if cur is None or rank < (cur[0], cur[1]):
                        self.sub[piece] = (*rank, payload)
        for bucket in self.index.values():
            bucket.sort(key=lambda x: -len(x[0]))

    def lookup(self, phrase: str) -> dict | None:
        """Khớp NGUYÊN CỤM (đã chuẩn hoá) — dùng để gán mã cho span LLM đã bọc."""
        return self.exact.get(tuple(norm_token(t) for t in TOKEN_RE.findall(phrase)))

    def lookup_partial(self, phrase: str) -> dict | None:
        """Cụm là một ĐOẠN CON của alias nào đó — nước cuối khi hai cách trên trượt."""
        hit = self.sub.get(tuple(norm_token(t) for t in TOKEN_RE.findall(phrase)))
        return hit[2] if hit else None

    def find_all(self, text: str) -> list[tuple[int, int, dict]]:
        """Quét toàn văn bản -> [(start, end, payload)], không chồng lấn."""
        spans = [(m.start(), m.end(), norm_token(m.group())) for m in TOKEN_RE.finditer(text)]
        out: list[tuple[int, int, dict]] = []
        i = 0
        while i < len(spans):
            for toks, payload in self.index.get(spans[i][2], ()):
                n = len(toks)
                if i + n <= len(spans) and all(spans[i + k][2] == toks[k] for k in range(n)):
                    out.append((spans[i][0], spans[i + n - 1][1], payload))
                    i += n
                    break
            else:
                i += 1
        return out

    def best_inside(self, phrase: str) -> dict | None:
        """Cụm dài nhất tra được NẰM TRONG một span — dùng khi không khớp nguyên cụm.

        Cần vì LLM bọc theo lối bệnh án ("đái tháo đường type 2 biến chứng thận")
        còn bảng ICD ghi theo lối WHO; phần lõi thì trùng, phần bổ ngữ thì không.
        """
        found = self.find_all(phrase)
        if not found:
            return None
        return max(found, key=lambda f: f[1] - f[0])[2]


def build_term_mapping(icd_list: list[dict], rx_list: list[dict]
                       ) -> tuple[Gazetteer, Gazetteer]:
    """Dựng hai gazetteer tra mã, từ CHÍNH bảng của ban tổ chức.

    Không cần bảng ánh xạ Anh-Việt riêng như bản nháp của kế hoạch dự tính: bảng
    ICD10.csv của ban tổ chức đã là tiếng Việt sẵn (cột "Tên bệnh"), nên tra thẳng
    trên bản dịch được. Còn tên thuốc thì prompt bắt giữ nguyên tiếng Anh, đúng
    dạng alias RxNorm — cũng tra thẳng được. Một bảng ánh xạ tự dựng thêm chỉ tạo
    ra tầng sai số thứ hai giữa hai bảng đã có.
    """
    icd_gaz = Gazetteer([(r["alias"], {"code": r["code"], "alias": r["alias"]})
                         for r in icd_list], sub_index=True)
    rx_gaz = Gazetteer([(r["alias"], {"codes": r["codes"], "alias": r["alias"]})
                        for r in rx_list], sub_index=True)
    return icd_gaz, rx_gaz


# ------------------------------------------------------------- dịch + bọc thực thể

TRANSLATE_SYS = """Bạn dịch bệnh án tiếng Anh sang tiếng Việt theo văn phong bệnh viện Việt Nam,
ĐỒNG THỜI đánh dấu mọi thực thể y khoa ngay trong bản dịch.

CÁCH ĐÁNH DẤU — bọc thực thể trong 〔LOẠI|nội dung〕, dùng đúng 5 mã loại sau:
  〔DX|...〕    tên bệnh, chẩn đoán            ví dụ: 〔DX|đái tháo đường type 2〕
  〔SYM|...〕   triệu chứng, dấu hiệu           ví dụ: 〔SYM|đau ngực khi gắng sức〕
  〔DRUG|...〕  tên thuốc                       ví dụ: 〔DRUG|aspirin〕
  〔TEST|...〕  tên xét nghiệm, thăm dò         ví dụ: 〔TEST|công thức máu toàn phần〕
  〔RES|...〕   kết quả xét nghiệm              ví dụ: 〔RES|1.3 mg/dL〕

BA CHỖ HAY ĐÁNH DẤU SAI, để ý kỹ:
  a. TÊN CHẤT XÉT NGHIỆM là 〔TEST|...〕, KHÔNG phải 〔SYM|...〕. Các chất như
     bilirubin, creatinine, phosphatase kiềm, cholesterol, hemoglobin, albumin,
     natri, kali là ĐỐI TƯỢNG được đo — chúng là xét nghiệm, không phải triệu chứng.
     Đúng: 〔TEST|bilirubin〕 〔RES|1.2 mg/dL〕     Sai: 〔SYM|bilirubin〕
  b. MỌI TRỊ SỐ đi kèm xét nghiệm đều phải bọc 〔RES|...〕, kể cả số trần không
     có đơn vị. Mục "Kết quả xét nghiệm" của bệnh án thật gần như dòng nào cũng
     có một 〔TEST|...〕 và một 〔RES|...〕 đi cặp — đừng bỏ trống trị số.
     Đúng: 〔TEST|HCT〕 〔RES|34.8〕, 〔TEST|BUN〕 〔RES|37〕, 〔TEST|LDL〕 〔RES|158 mg/dL〕.
     〔RES|...〕 cũng dùng cho kết luận chẩn đoán hình ảnh:
     〔TEST|X-quang ngực〕 cho thấy 〔RES|không có tổn thương khu trú〕.
  c. Liều thuốc (50 mg, 2 lần/ngày) KHÔNG phải kết quả xét nghiệm — không bọc.

QUY TẮC DỊCH:
1. GIỮ NGUYÊN TIẾNG ANH, không dịch, không phiên âm:
   - tên thuốc: aspirin, metformin, lisinopril, CellCept, Cozaar...
   - viết tắt xét nghiệm: WBC, HGB, HCT, BUN, HbA1c, LDL, HDL, AST, ALT, CRP, INR, ECG...
2. DỊCH sang tiếng Việt:
   - tên bệnh: diabetes -> đái tháo đường · hypertension -> tăng huyết áp
   - triệu chứng: chest pain -> đau ngực · shortness of breath -> khó thở
   - tên xét nghiệm dạng đầy đủ: Complete Blood Count -> công thức máu toàn phần
3. Tiêu đề mục dịch theo lối bệnh án Việt Nam. TIÊU ĐỀ PHẢI CHIẾM TRỌN MỘT DÒNG,
   kết thúc bằng dấu hai chấm, nội dung xuống dòng dưới:
       REASON FOR VISIT / CHIEF COMPLAINT   -> Lý do vào viện:
       HISTORY OF PRESENT ILLNESS           -> Bệnh sử:
       SUBJECTIVE                           -> Bệnh sử:
       OBJECTIVE                            -> Khám thực thể:
       PAST MEDICAL HISTORY                 -> Tiền sử bệnh:
       FAMILY HISTORY                       -> Tiền sử gia đình:
       ALLERGIES                            -> Dị ứng:
       MEDICATIONS                          -> Thuốc đang dùng:
       REVIEW OF SYSTEMS                    -> Khám các cơ quan:
       PHYSICAL EXAMINATION                 -> Khám thực thể:
       LABORATORY DATA / LABS               -> Kết quả xét nghiệm:
       IMPRESSION / ASSESSMENT / DIAGNOSIS  -> Chẩn đoán:
       PLAN / RECOMMENDATIONS               -> Hướng điều trị:
   Đúng:
       Bệnh sử:
       Bệnh nhân nam 52 tuổi, 〔DX|bệnh thận giai đoạn cuối〕...
   Sai: "Bệnh sử: Bệnh nhân nam 52 tuổi..." (tiêu đề dính vào nội dung).
4. Đánh dấu ĐẦY ĐỦ: mỗi lần một thực thể xuất hiện là một lần bọc, kể cả khi
   lặp lại ở mục khác. Bệnh án thật nhắc chẩn đoán ở cả Bệnh sử, Tiền sử và
   Chẩn đoán — bọc cả ba lần.
5. Dấu 〔 〕 chỉ được bọc ĐÚNG cụm thực thể, KHÔNG bọc kèm từ dẫn, liều lượng
   hay dấu câu. Đúng: 〔DRUG|metoprolol〕 50 mg x 2 lần/ngày.
   Sai: 〔DRUG|metoprolol 50 mg x 2 lần/ngày〕.
6. KHÔNG lồng dấu 〔 〕 vào nhau. KHÔNG dùng ký tự 〔 〕 cho mục đích khác.
7. Giữ nguyên tuổi, giới, số đo, liều lượng, mốc thời gian của bản gốc.
   Bệnh án gốc có bao nhiêu mục thì bản dịch có bấy nhiêu mục, không lược bớt.
8. Chỉ trả về bản dịch. KHÔNG giải thích, KHÔNG dùng markdown, KHÔNG dấu **."""


def unwrap_typed(marked: str, allowed: set[tuple[str, str]] | None = None
                 ) -> tuple[str, list[dict]] | str:
    """Bóc dấu 〔LOẠI|...〕 -> (văn bản sạch, records), offset tính NGAY LÚC BÓC.

    Cùng một cách với unwrap() ở đường tự sinh, khác mỗi chỗ loại thực thể đọc từ
    trong dấu thay vì tra bundle. Trả về str mô tả lý do khi không dùng được.

    `allowed` (dùng ở bước restyle): tập (mã loại, nội dung) được phép gán nhãn.
    Dấu nằm ngoài tập này là do LLM bịa thêm lúc viết lại — BỎ NHÃN nhưng GIỮ CHỮ,
    tức chỉ mất một nhãn chứ không sai nhãn. Bỏ được an toàn vì offset của các span
    khác tính trên chuỗi cuối cùng, không phụ thuộc span này có được ghi hay không.
    """
    marked = re.sub(r"\*\*(?!\*)", "", marked)
    marked = re.sub(r"(?m)^#{1,6}[ ]*", "", marked)

    # Dấu 〔 〕 hỏng (thiếu mã loại, lồng nhau, thiếu vế đóng) phải bỏ TRƯỚC vòng
    # tính offset, không phải sau: bỏ sau thì mọi offset đứng sau vị trí đó lệch
    # đúng bằng số ký tự vừa bỏ — cùng loại lỗi mà unwrap() gặp với dấu **.
    good = [(m.start(), m.end()) for m in BRACKET_TYPED.finditer(marked)]
    if not good:
        return "không có dấu 〔 〕 nào — LLM bỏ qua định dạng"
    keep, prev = [], 0
    for start, end in good:
        keep.append(marked[prev:start].replace("〔", "").replace("〕", ""))
        keep.append(marked[start:end])
        prev = end
    keep.append(marked[prev:].replace("〔", "").replace("〕", ""))
    marked = "".join(keep)

    parts: list[str] = []
    records: list[dict] = []
    pos = 0
    for m in BRACKET_TYPED.finditer(marked):
        parts.append(marked[pos:m.start()])
        offset = sum(len(p) for p in parts)
        tag, surface = m.group(1), m.group(2).strip()
        ctype = TYPE_ALIASES.get(tag, tag if tag in ENTITY_TYPES else None)
        if allowed is not None and (tag, norm_surface(surface)) not in allowed:
            ctype = None
        if surface and ctype:
            records.append({"text": surface, "type": ctype, "candidates": [],
                            "assertions": [],
                            "position": [offset, offset + len(surface)]})
        parts.append(surface)
        pos = m.end()
    parts.append(marked[pos:])
    text = "".join(parts)

    if not records:
        return "không mã loại nào đọc được (LLM đặt tên loại lạ)"
    for rec in records:
        s, e = rec["position"]
        if text[s:e] != rec["text"]:
            return "offset lệch sau khi bóc dấu"
    return text, records


# ----------------------------------------------------------- gán mã + gom span

def overlaps(pos1: list[int], pos2: list[int]) -> bool:
    """Hai span có chồng lấn không."""
    return not (pos1[1] <= pos2[0] or pos2[1] <= pos1[0])


def remove_overlapping_spans(records: list[dict]) -> list[dict]:
    """Bỏ span chồng lấn: span LLM đánh dấu thắng, sau đó span dài thắng.

    Ưu tiên span LLM chứ không thuần theo độ dài, vì gazetteer dò được cả những
    cụm nằm TRONG span LLM đã bọc (alias ICD "viêm phổi" nằm trong "viêm phổi
    thuỳ dưới phải") — thuần theo độ dài thì vẫn đúng, nhưng khi dài bằng nhau,
    nhãn của LLM sát ngữ cảnh câu hơn nhãn tra từ điển.
    """
    ordered = sorted(records, key=lambda r: (r["position"][0],
                                             r.get("_src", 1),
                                             -(r["position"][1] - r["position"][0])))
    kept: list[dict] = []
    for rec in ordered:
        if not any(overlaps(rec["position"], k["position"]) for k in kept):
            kept.append(rec)
    return kept


def link_candidates(records: list[dict], icd_gaz: Gazetteer, rx_gaz: Gazetteer) -> None:
    """Gán mã ICD cho CHẨN_ĐOÁN và RxCUI cho THUỐC, sửa tại chỗ.

    Ba type còn lại để rỗng: đo trên gold, TÊN_XÉT_NGHIỆM và KẾT_QUẢ_XÉT_NGHIỆM
    có 0% span mang mã, và bảng của ban tổ chức không có mục nào tra được cho
    TRIỆU_CHỨNG.
    """
    for rec in records:
        gaz = {"CHẨN_ĐOÁN": icd_gaz, "THUỐC": rx_gaz}.get(rec["type"])
        if gaz is None or "*" in rec["text"]:
            continue
        hit = (gaz.lookup(rec["text"]) or gaz.best_inside(rec["text"])
               or gaz.lookup_partial(rec["text"]))
        if hit:
            rec["candidates"] = [hit["code"]] if "code" in hit else list(hit["codes"])


#: Gazetteer của SYMPTOMS/TEST_NAMES dựng một lần rồi dùng lại: sweep chạy mỗi
#: tài liệu một lần, dựng lại trong vòng lặp là phí.
_PHRASE_GAZ: dict[str, Gazetteer] = {}


def _phrase_gazetteer(key: str, phrases: list[str]) -> Gazetteer:
    if key not in _PHRASE_GAZ:
        _PHRASE_GAZ[key] = Gazetteer([(p, {}) for p in phrases])
    return _PHRASE_GAZ[key]


def sweep_gazetteers(text: str, icd_gaz: Gazetteer, rx_gaz: Gazetteer) -> list[dict]:
    """Dò thêm thực thể LLM bỏ sót, bằng từ điển.

    Chỉ bổ sung chứ không thay thế nhãn của LLM: mọi span dò được ở đây sẽ bị
    remove_overlapping_spans loại nếu đè lên span LLM đã bọc.

    Ngưỡng số từ tối thiểu là kết quả soát tay 5 bản dịch đầu, không phải phòng xa:
      - ICD >=3 từ. Alias ICD 2 từ phần lớn trùng TRIỆU_CHỨNG chứ không phải chẩn
        đoán ("Đau lưng" M54, "Đau khớp" M25.5) — quét vào thì cùng một cụm bị gán
        CHẨN_ĐOÁN ở tài liệu này, TRIỆU_CHỨNG ở tài liệu kia, dạy model mâu thuẫn.
      - cụm triệu chứng/xét nghiệm >=2 từ. Cụm 1 từ khớp cả khi nó chỉ là nửa của
        từ ghép: "phù" khớp trong "phù hợp", "mệt" trong "mệt mỏi" — tách từ theo
        khoảng trắng không phân biệt được, mà tiếng Việt thì từ ghép viết rời.
    Thuốc giữ ngưỡng 1 từ: tên thuốc là tiếng Anh giữa văn bản Việt nên không có
    chuyện trùng nửa từ ghép, và phần lớn tên thuốc vốn chỉ một từ.
    """
    found: list[dict] = []
    for gaz, ctype, key, min_tok in ((icd_gaz, "CHẨN_ĐOÁN", "code", 3),
                                     (rx_gaz, "THUỐC", "codes", 1)):
        for start, end, payload in gaz.find_all(text):
            if len(TOKEN_RE.findall(text[start:end])) < min_tok:
                continue
            found.append({"text": text[start:end], "type": ctype,
                          "candidates": ([payload[key]] if key == "code"
                                         else list(payload[key])), "assertions": [],
                          "position": [start, end], "_src": 1})
    for phrases, ctype in ((SYMPTOMS, "TRIỆU_CHỨNG"), (TEST_NAMES, "TÊN_XÉT_NGHIỆM")):
        for start, end, _ in _phrase_gazetteer(ctype, phrases).find_all(text):
            if len(TOKEN_RE.findall(text[start:end])) < 2:
                continue
            found.append({"text": text[start:end], "type": ctype, "candidates": [],
                          "assertions": [], "position": [start, end], "_src": 1})
    return found


def extract_entities_from_mtsamples(marked_vi: str,
                                    icd_gaz: Gazetteer, rx_gaz: Gazetteer,
                                    allowed: set[tuple[str, str]] | None = None
                                    ) -> tuple[str, list[dict]] | str:
    """Từ bản dịch CÓ DẤU -> (văn bản sạch, records đầy đủ mã + assertion).

    Khác chữ ký trong bản nháp kế hoạch ở hai chỗ, và cả hai đều là hệ quả của
    việc bọc dấu lúc dịch:
      - nhận `marked_vi` (bản dịch còn dấu) chứ không phải `text_vi` đã sạch, vì
        vị trí span nằm ở chính dấu 〔 〕 — bỏ dấu trước rồi dò lại là quay về cách
        cho recall ~0 ở CHẨN_ĐOÁN đã nói ở đầu file;
      - trả về CẢ văn bản sạch, vì chỉ có hàm này biết văn bản sau khi bóc dấu
        trông thế nào, mà offset thì tính trên đúng chuỗi đó.
    """
    res = unwrap_typed(marked_vi, allowed=allowed)
    if isinstance(res, str):
        return res
    text_vi, records = res
    for rec in records:
        rec["_src"] = 0
    records = remove_overlapping_spans(records + sweep_gazetteers(text_vi, icd_gaz, rx_gaz))
    for rec in records:
        rec.pop("_src", None)
    link_candidates(records, icd_gaz, rx_gaz)
    for rec in records:
        rec["assertions"] = assertions_at(text_vi, rec["position"][0])
        s, e = rec["position"]
        if text_vi[s:e] != rec["text"]:
            return "offset lệch sau khi gom span"
    return text_vi, sorted(records, key=lambda r: r["position"])


# ------------------------------------------------ bước 3': dịch mtsamples -> nhãn

def cmd_translate(args) -> int:
    rng = random.Random(args.seed + 2)
    TRANSLATED_WORK.mkdir(parents=True, exist_ok=True)
    TRANSLATED_TEXT.mkdir(parents=True, exist_ok=True)
    TRANSLATED_ANNOTATIONS.mkdir(parents=True, exist_ok=True)

    print("đọc bảng ban tổ chức...")
    icd = load_icd()
    rx = load_rxnorm()
    icd_gaz, rx_gaz = build_term_mapping(icd, common_drugs(rx) if args.common_drugs_only else rx)
    print(f"  gazetteer: {len(icd_gaz.exact)} cụm ICD | {len(rx_gaz.exact)} tên thuốc")

    # Nạp lại từ file bản dịch: lấy DANH SÁCH BỆNH ÁN TỪ CHÍNH FILE ĐÓ, không bốc
    # lại từ kho. Bốc lại là sai: thứ tự bốc phụ thuộc seed/tham số lọc, đổi một
    # tham số (thêm --min-lab chẳng hạn) là bản dịch bị ghép vào bệnh án gốc khác,
    # trong khi nhãn vẫn "đúng" so với bản dịch nên verify không phát hiện được.
    preloaded = None
    if args.translated:
        rows = [json.loads(l) for l in
                Path(args.translated).read_text(encoding="utf-8").splitlines() if l.strip()]
        if rows and all(r.get("category") is not None and "text_vi_marked" in r for r in rows):
            preloaded = rows

    if preloaded is not None:
        samples = [{"id": r.get("source_id", r["id"]), "category": r["category"],
                    "text": r.get("text_en", ""), "file_id": r["id"]} for r in preloaded]
        print(f"nạp {len(samples)} bệnh án kèm bản dịch từ {args.translated}")
    else:
        cats = MTSAMPLES_CATEGORIES[:args.n_categories]
        n_per_cat = max(1, args.n // max(len(cats), 1))
        samples = fetch_mtsamples(cats, n_per_cat, args.source, rng,
                                  total=args.n, min_lab=args.min_lab)
    if not samples:
        sys.exit("không nạp được bệnh án nào từ mtsamples")
    spread = collections.Counter(s["category"] for s in samples)
    if preloaded is None:
        print(f"đã nạp {len(samples)}/{args.n} bệnh án từ mtsamples")
    for spec, k in spread.most_common():
        print(f"    {k:3d}  {spec}")

    # id có prefix chuyên khoa để nhìn tên file là biết bệnh cảnh
    counters: collections.Counter = collections.Counter()
    for s in samples:
        if s.get("file_id"):
            continue
        prefix = CATEGORY_PREFIXES.get(s["category"], "other")
        counters[prefix] += 1
        s["file_id"] = f"mtsamples_{prefix}_{counters[prefix]:04d}"

    path_trans = TRANSLATED_WORK / "translation_process.jsonl"
    prompts = [f"Dịch bệnh án sau sang tiếng Việt và đánh dấu thực thể:\n\n{s['text']}"
               for s in samples]

    if args.translated:
        loaded = {json.loads(l)["id"]: json.loads(l).get("text_vi_marked", "")
                  for l in Path(args.translated).read_text(encoding="utf-8").splitlines() if l.strip()}
        marked = [loaded.get(s["file_id"]) or loaded.get(s["id"], "") for s in samples]
        print(f"nạp sẵn {sum(1 for m in marked if m)} bản dịch từ {args.translated}")
    elif args.use_api:
        print(f"dịch bằng {args.model}...")
        marked = call_api(prompts, TRANSLATE_SYS, args.model, args.max_tokens)
    else:
        path_p = TRANSLATED_WORK / "translation_prompts.jsonl"
        with path_p.open("w", encoding="utf-8") as fh:
            for s, p in zip(samples, prompts):
                fh.write(json.dumps({"id": s["file_id"], "source_id": s["id"],
                                     "category": s["category"], "system": TRANSLATE_SYS,
                                     "prompt": p}, ensure_ascii=False) + "\n")
        print(f"  chưa gọi API — prompt ở {path_p.relative_to(REPO)}")
        print(f"  gọi model nào cũng được rồi nạp lại: translate --translated FILE")
        print(f"  (FILE mỗi dòng: {{\"id\": \"mtsamples_cardio_0001\","
              f" \"text_vi_marked\": \"...\"}})")
        return 0

    # ghi nhật ký dịch trước khi lọc — bản bị loại vẫn cần xem lại được
    with path_trans.open("w", encoding="utf-8") as fh:
        for s, mk in zip(samples, marked):
            fh.write(json.dumps({"id": s["file_id"], "source_id": s["id"],
                                 "category": s["category"], "text_en": s["text"],
                                 "text_vi_marked": mk}, ensure_ascii=False) + "\n")
    print(f"đã dịch {sum(1 for m in marked if m)} bản -> {path_trans.relative_to(REPO)}")

    n_ok = n_mask = n_nfd = 0
    reasons: collections.Counter = collections.Counter()
    by_type: collections.Counter = collections.Counter()
    for s, mk in zip(samples, marked):
        if not mk:
            reasons["không có bản dịch"] += 1
            continue
        res = extract_entities_from_mtsamples(mk, icd_gaz, rx_gaz)
        if isinstance(res, str):
            reasons[res] += 1
            continue
        text, records = res
        if len(records) < args.min_spans:
            reasons[f"dưới {args.min_spans} span"] += 1
            continue
        # Bẫy *** hiệu chỉnh theo SỐ SPAN THUỐC của chính tài liệu này. Dùng thẳng
        # một tỉ lệ mỗi-span như đường tự sinh thì sai mốc: bundle tự sinh có 3-5
        # thuốc, còn mục "Thuốc đang dùng" của mtsamples thường 8-12 — cùng
        # mask_rate 0,12 cho ra 68% FILE có bẫy thay vì 30% như đo trên test.
        n_drug = sum(1 for r in records if r["type"] == "THUỐC")
        per_span = 1 - (1 - args.mask_file_rate) ** (1 / n_drug) if n_drug else 0.0
        text, records = postprocess(
            rng, text, records,
            argparse.Namespace(mask_rate=per_span, nfd_rate=args.nfd_rate))
        if text is None:
            reasons["hậu xử lý hỏng offset"] += 1
            continue
        n_ok += 1
        n_mask += sum(1 for r in records if "*" in r["text"])
        n_nfd += int(text != ud.normalize("NFC", text))
        for r in records:
            by_type[r["type"]] += 1
        (TRANSLATED_TEXT / f"{s['file_id']}.txt").write_text(text, encoding="utf-8")
        (TRANSLATED_ANNOTATIONS / f"{s['file_id']}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"đã xuất {n_ok}/{len(samples)} bản dùng được")
    print(f"  văn bản: {TRANSLATED_TEXT.relative_to(REPO)}")
    print(f"  nhãn:    {TRANSLATED_ANNOTATIONS.relative_to(REPO)}")
    print(f"  bẫy ***: {n_mask} span | NFD: {n_nfd} file")
    if reasons:
        print(f"  loại: {dict(reasons)}")
    print(f"  span theo type: {dict(by_type)}")
    return 0


# ================================================ ĐỔI THỂ LOẠI cho khớp đề thi

#: Tỉ lệ thể loại đo trên 100 file data/test. Bản dịch mtsamples ra 100% "văn xuôi
#: lâm sàng có tiêu đề mục" — tức chỉ khớp 17% đề thi. PRD §7.3 gọi thẳng đây là
#: việc phải làm: "Nhãn bạc & prompt few-shot phải phủ nhiều thể loại".
RESTYLE_GENRES: dict[str, tuple[int, str]] = {
    "dan_y": (45, """Viết lại thành DÀN Ý GẠCH ĐẦU DÒNG / ĐÁNH SỐ, kiểu bản ghi tóm tắt bệnh án.
- Mục lớn đánh số "1.", "2." ... ; ý con dùng "-" thụt vào đầu dòng.
- Câu cụt, không cần chủ ngữ, kiểu ghi chép nhanh: "- sốt cao 3 ngày", "- đã dùng ...".
- Có thể có mục "Lời khuyên dành cho bạn:" hoặc "Hướng xử trí:" ở cuối."""),

    "van_xuoi": (17, """Giữ dạng VĂN XUÔI LÂM SÀNG có tiêu đề mục như bản gốc, nhưng viết tự nhiên hơn:
- Bỏ bớt vài tiêu đề mục, gộp nội dung vào đoạn văn liền mạch.
- Câu dài, nhiều mệnh đề, giọng bác sĩ ghi bệnh án."""),

    "pho_bien": (15, """Viết lại thành BÀI PHỔ BIẾN KIẾN THỨC Y KHOA cho người đọc phổ thông.
- Mở đầu bằng câu hỏi kiểu "X là bệnh gì?" rồi giải thích chung.
- Nói về bệnh NÓI CHUNG, không nói về một bệnh nhân cụ thể: đổi "bệnh nhân sốt cao"
  thành "người bệnh có thể sốt cao", "bệnh thường khởi phát với ...".
- Có thể liệt kê triệu chứng, nguyên nhân, cách phòng ngừa."""),

    "hoi_dap": (14, """Viết lại thành HỎI–ĐÁP giữa người bệnh và bác sĩ trên diễn đàn y tế.
- Bắt đầu bằng "Hỏi: Kính chào bác sĩ! ..." — người bệnh tự kể bệnh mình bằng lời dân dã,
  xưng "em"/"tôi", có chi tiết đời thường (đi làm xa, ăn uống thất thường...).
- Rồi "Trả lời:" — bác sĩ giải thích và tư vấn.
- Dùng lối nói dân dã thay thuật ngữ khi hợp: "đau bao tử", "đi tiêu ra máu", "men gan cao"."""),

    "xuong_dong": (9, """Viết lại thành BỆNH ÁN CHÉP TAY vội, thô ráp:
- XUỐNG DÒNG CỨNG giữa câu, mỗi dòng chỉ 30-50 ký tự, ngắt ở chỗ bất kỳ kể cả giữa mệnh đề.
  NHƯNG KHÔNG ĐƯỢC ngắt dòng vào giữa một cụm 〔...〕 — cụm nào dài thì cho hẳn xuống dòng dưới.
- Dùng viết tắt bệnh viện: BN, TS, HA, M (mạch), NYHA III-IV, TTT, ck/ph, đ/n.
  CHỈ viết tắt ở phần chữ NGOÀI dấu 〔 〕. Bên trong dấu giữ nguyên si:
  〔DX|tăng huyết áp〕 KHÔNG được rút thành 〔DX|tăng HA〕.
- Tiêu đề mục ghi cụt kiểu "TS:", "TS gia đình:", "Khám:", "Thuốc:".
- Dùng "->" thay cho "dẫn đến"; bỏ bớt dấu câu; có thể sai chính tả nhẹ ("điêu trị").
- Không cần tiêu đề mục đầy đủ, ghi cụt: "Khám:", "TS:"."""),
}

RESTYLE_SYS = """Bạn viết lại một bệnh án tiếng Việt sang THỂ LOẠI VĂN BẢN KHÁC.

RÀNG BUỘC TUYỆT ĐỐI — đọc kỹ, đây là phần quan trọng nhất:

1. Văn bản có các cụm được bọc trong 〔LOẠI|nội dung〕. Bạn PHẢI giữ lại TẤT CẢ,
   NGUYÊN VĂN, cả mã loại lẫn nội dung bên trong, kể cả khi câu quanh nó đổi hoàn toàn.
   Đúng:  gốc "Bệnh nhân có 〔DX|đái tháo đường type 2〕."
          viết lại "- tiền sử 〔DX|đái tháo đường type 2〕"
   Sai:   "- tiền sử đái tháo đường type 2"        (mất dấu)
   Sai:   "- tiền sử 〔DX|tiểu đường〕"              (đổi chữ bên trong dấu)
   Sai:   "- tiền sử 〔DIAGNOSIS|đái tháo đường type 2〕"  (đổi mã loại)

2. KHÔNG tạo dấu 〔 〕 mới cho cụm chưa có. Thà để trần còn hơn bọc thêm.

3. KHÔNG thêm bệnh, thuốc, xét nghiệm hay trị số nào không có trong bản gốc.
   Mọi thông tin y khoa phải giữ đúng: tuổi, giới, liều lượng, trị số, mốc thời gian.
   Được phép bỏ bớt câu rườm rà, đổi trật tự, đổi cách xưng hô, đổi giọng văn.

4. Giữ nguyên ngôn ngữ của cụm trong dấu: tên thuốc tiếng Anh vẫn tiếng Anh.

5. Chỉ trả về văn bản đã viết lại. KHÔNG giải thích, KHÔNG markdown, KHÔNG dấu **.

THỂ LOẠI CẦN VIẾT LẠI:
"""


def norm_surface(s: str) -> str:
    """Gộp mọi khoảng trắng về một dấu cách — dùng khi đối chiếu nội dung dấu.

    Thể loại "bệnh án chép tay" ngắt dòng cứng mỗi 30-50 ký tự, và LLM ngắt cả
    vào GIỮA dấu: 〔TEST|MRI⏎MRCP〕. So khớp thô thì cụm đó khác 〔TEST|MRI MRCP〕
    của bản gốc nên bị coi là bịa và mất nhãn — 4/6 nhãn mất ở lô đầu là do đúng
    lỗi này. Bản thân span vẫn hợp lệ: chuỗi trong văn bản có xuống dòng thật,
    offset vẫn khớp từng ký tự, chỉ việc ĐỐI CHIẾU là cần bỏ qua khoảng trắng.
    """
    return re.sub(r"\s+", " ", s).strip()


def marker_set(marked: str) -> collections.Counter:
    """Đa tập (mã loại, nội dung) của mọi dấu 〔 〕 — dùng để đối chiếu trước/sau."""
    return collections.Counter((m.group(1), norm_surface(m.group(2)))
                               for m in BRACKET_TYPED.finditer(marked))


def check_restyle(before: str, after: str, min_keep: float) -> str | None:
    """Trả lý do loại, hoặc None nếu bản viết lại dùng được.

    Ngưỡng giữ dấu để RẤT THẤP, và đây là chỗ tôi đã đặt sai ở lượt đầu: để 80%
    thì 4/5 bản bị loại với tỉ lệ giữ 31-71%, trong khi đọc tay thì cả 4 đều tốt.
    Lý do: bỏ bớt nội dung CHÍNH LÀ việc đổi thể loại — bài phổ biến kiến thức
    không kể hết 6 thuốc của một bệnh nhân, bệnh án chép vội cũng lược nhiều.

    Bỏ bớt dấu KHÔNG làm sai nhãn: offset tính trên chuỗi cuối cùng nên các span
    còn lại vẫn đúng từng ký tự, chỉ là tài liệu có ít span hơn — mà số span tối
    thiểu đã có --min-spans canh rồi. Hai rủi ro thật (LLM bịa dấu mới, hoặc đổi
    chữ bên trong dấu) do tập `allowed` ở unwrap_typed chặn, không phải hàm này.
    Ngưỡng ở đây chỉ còn để bắt trường hợp model bỏ hẳn nhiệm vụ.
    """
    if len(after) < 200:
        return "bản viết lại quá ngắn"
    src, dst = marker_set(before), marker_set(after)
    if not src:
        return "bản gốc không có dấu nào"
    kept = sum((src & dst).values()) / sum(src.values())
    if kept < min_keep:
        return f"chỉ giữ {kept:.0%} dấu (cần >={min_keep:.0%})"
    return None


def cmd_restyle(args) -> int:
    rng = random.Random(args.seed + 3)
    RESTYLED_WORK.mkdir(parents=True, exist_ok=True)
    RESTYLED_TEXT.mkdir(parents=True, exist_ok=True)
    RESTYLED_ANNOTATIONS.mkdir(parents=True, exist_ok=True)

    src = Path(args.source) if args.source else TRANSLATED_WORK / "translation_process.jsonl"
    if not src.exists():
        sys.exit(f"chưa có {src} — chạy translate trước")
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("text_vi_marked")]
    if args.n:
        rows = rows[:args.n]
    if not rows:
        sys.exit(f"{src} không có bản dịch nào dùng được")

    print("đọc bảng ban tổ chức...")
    icd_gaz, rx_gaz = build_term_mapping(load_icd(), load_rxnorm())

    names = list(RESTYLE_GENRES)
    weights = [RESTYLE_GENRES[g][0] for g in names]
    for r in rows:
        r["genre"] = args.genre if args.genre else rng.choices(names, weights)[0]
    spread = collections.Counter(r["genre"] for r in rows)
    print(f"viết lại {len(rows)} bản, thể loại theo tỉ lệ đo trên data/test:")
    for g, k in spread.most_common():
        print(f"    {k:3d}  {g}")

    path_out = RESTYLED_WORK / "restyle_process.jsonl"
    prompts = [f"Viết lại văn bản sau:\n\n{r['text_vi_marked']}" for r in rows]

    if args.restyled:
        loaded = {json.loads(l)["id"]: json.loads(l).get("text_restyled", "")
                  for l in Path(args.restyled).read_text(encoding="utf-8").splitlines() if l.strip()}
        out = [loaded.get(r["id"], "") for r in rows]
        print(f"nạp sẵn {sum(1 for x in out if x)} bản viết lại từ {args.restyled}")
    elif args.use_api:
        # gọi theo TỪNG NHÓM thể loại: mỗi thể loại là một system prompt khác nhau,
        # mà call_api chỉ nhận một system cho cả lô
        out = [""] * len(rows)
        for g in names:
            idx = [i for i, r in enumerate(rows) if r["genre"] == g]
            if not idx:
                continue
            print(f"  thể loại {g} ({len(idx)} bản)...")
            got = call_api([prompts[i] for i in idx],
                           RESTYLE_SYS + RESTYLE_GENRES[g][1], args.model, args.max_tokens)
            for i, txt in zip(idx, got):
                out[i] = txt
    else:
        path_p = RESTYLED_WORK / "restyle_prompts.jsonl"
        with path_p.open("w", encoding="utf-8") as fh:
            for r, p in zip(rows, prompts):
                fh.write(json.dumps({"id": r["id"], "genre": r["genre"],
                                     "system": RESTYLE_SYS + RESTYLE_GENRES[r["genre"]][1],
                                     "prompt": p}, ensure_ascii=False) + "\n")
        print(f"  chưa gọi API — prompt ở {path_p.relative_to(REPO)}")
        print(f"  gọi model nào cũng được rồi nạp lại: restyle --restyled FILE")
        print(f"  (FILE mỗi dòng: {{\"id\": \"...\", \"text_restyled\": \"...\"}})")
        return 0

    with path_out.open("w", encoding="utf-8") as fh:
        for r, txt in zip(rows, out):
            fh.write(json.dumps({"id": r["id"], "genre": r["genre"],
                                 "category": r.get("category", ""),
                                 "text_vi_marked": r["text_vi_marked"],
                                 "text_restyled": txt}, ensure_ascii=False) + "\n")
    print(f"đã viết lại {sum(1 for x in out if x)} bản -> {path_out.relative_to(REPO)}")

    n_ok = n_mask = n_nfd = 0
    reasons: collections.Counter = collections.Counter()
    by_genre: collections.Counter = collections.Counter()
    for r, txt in zip(rows, out):
        if not txt:
            reasons["không có bản viết lại"] += 1
            continue
        why = check_restyle(r["text_vi_marked"], txt, args.min_keep)
        if why:
            reasons[why] += 1
            continue
        # Chỉ nhận dấu đã có ở bản gốc: LLM bịa thêm dấu thì bỏ NHÃN, giữ CHỮ.
        allowed = set(marker_set(r["text_vi_marked"]))
        res = extract_entities_from_mtsamples(txt, icd_gaz, rx_gaz, allowed=allowed)
        if isinstance(res, str):
            reasons[res] += 1
            continue
        text, records = res
        if len(records) < args.min_spans:
            reasons[f"dưới {args.min_spans} span"] += 1
            continue
        n_drug = sum(1 for x in records if x["type"] == "THUỐC")
        per_span = 1 - (1 - args.mask_file_rate) ** (1 / n_drug) if n_drug else 0.0
        text, records = postprocess(
            rng, text, records,
            argparse.Namespace(mask_rate=per_span, nfd_rate=args.nfd_rate))
        if text is None:
            reasons["hậu xử lý hỏng offset"] += 1
            continue
        n_ok += 1
        by_genre[r["genre"]] += 1
        n_mask += sum(1 for x in records if "*" in x["text"])
        n_nfd += int(text != ud.normalize("NFC", text))
        # Xoá bản cũ CỦA CHÍNH id này trước khi ghi: thể loại nằm trong tên file mà
        # mỗi lượt chạy bốc thể loại lại, nên chạy lần hai để lại file mồ côi của
        # lần một — verify đếm cả hai và báo số liệu trộn hai lô.
        for old in list(RESTYLED_TEXT.glob(f"{r['id']}_*.txt")):
            old.unlink()
        for old in list(RESTYLED_ANNOTATIONS.glob(f"{r['id']}_*.json")):
            old.unlink()
        stem = f"{r['id']}_{r['genre']}"
        (RESTYLED_TEXT / f"{stem}.txt").write_text(text, encoding="utf-8")
        (RESTYLED_ANNOTATIONS / f"{stem}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"đã xuất {n_ok}/{len(rows)} bản dùng được")
    print(f"  văn bản: {RESTYLED_TEXT.relative_to(REPO)}")
    print(f"  nhãn:    {RESTYLED_ANNOTATIONS.relative_to(REPO)}")
    print(f"  bẫy ***: {n_mask} span | NFD: {n_nfd} file")
    print(f"  theo thể loại: {dict(by_genre)}")
    if reasons:
        print(f"  loại: {dict(reasons)}")
    return 0


# ----------------------------------------------------------- bước 3: kiểm lại

#: Độ dài span trung bình (từ) đo trên gold — mốc để đối chiếu dữ liệu sinh ra.
#: Chỉ hai type này mang mã trong gold — ba type còn lại có 0% span có mã, nên
#: gộp chung vào một tỉ lệ "span có mã" làm loãng số: lô dịch giàu xét nghiệm tụt
#: còn 29% chỉ vì có nhiều span xét nghiệm, dù mã chẩn đoán/thuốc vẫn 74%.
CODEABLE_TYPES = ("CHẨN_ĐOÁN", "THUỐC")

GOLD_SPAN_LEN = {"CHẨN_ĐOÁN": 4.05, "TRIỆU_CHỨNG": 3.27, "THUỐC": 2.10,
                 "TÊN_XÉT_NGHIỆM": 3.71, "KẾT_QUẢ_XÉT_NGHIỆM": 5.32}


def verify_dataset(files: list[Path], icd_codes: set, rx_codes: set,
                   indent: str = "  ") -> dict:
    """Kiểm một lô nhãn, in thống kê, trả về {avg_spans, pct_with_code, errors}.

    Thư mục văn bản suy từ CHÍNH đường dẫn của từng file nhãn (…/annotations/x.json
    -> …/text/x.txt) chứ không nhận vào một thư mục chung: hàm này còn được gọi
    với lô trộn cả synthetic lẫn translated, hai lô nằm ở hai cây khác nhau.
    """
    bad: collections.Counter = collections.Counter()
    n_span = n_assert = n_mask = n_nfd = n_hdr = 0
    n_codeable = n_codeable_hit = 0
    lens: collections.defaultdict = collections.defaultdict(list)

    for path in files:
        records = json.loads(path.read_text(encoding="utf-8"))
        text_file = path.parent.parent / "text" / f"{path.stem}.txt"
        if not text_file.exists():
            bad["thiếu file văn bản đi kèm"] += 1
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
            if rec["type"] in CODEABLE_TYPES:
                n_codeable += 1
                n_codeable_hit += bool(rec["candidates"])
            n_assert += bool(rec["assertions"])
            lens[rec["type"]].append(len(rec["text"].split()))
            for code in rec["candidates"]:
                if code not in icd_codes and code not in rx_codes:
                    bad["mã không tra được trong bảng BTC"] += 1

    n = max(len(files), 1)
    avg_spans = n_span / n
    pct_code = 100 * n_codeable_hit / max(n_codeable, 1)
    print(f"{indent}{len(files)} tài liệu · {n_span} span · {avg_spans:.1f} span/file"
          f" (gold median 48)")
    print(f"{indent}  lỗi offset:        {sum(bad.values())}")
    print(f"{indent}  span có mã:        {pct_code:.0f}%"
          f"   (trên {n_codeable} span CHẨN_ĐOÁN+THUỐC; 3 type còn lại gold không gán mã)")
    print(f"{indent}  span có assertion: {100 * n_assert / max(n_span, 1):.0f}%")
    print(f"{indent}  file có bẫy ***:   {100 * n_mask / n:.0f}%   (test 30%)")
    print(f"{indent}  file dạng NFD:     {100 * n_nfd / n:.0f}%   (test 20%)")
    print(f"{indent}  file có tiêu đề:   {100 * n_hdr / n:.0f}%   (test 67%)")
    if lens:
        print(f"{indent}  độ dài span (từ) — sinh ra / gold:")
        for ctype in sorted(lens):
            print(f"{indent}    {ctype:22} {st.mean(lens[ctype]):5.2f}"
                  f"  {GOLD_SPAN_LEN.get(ctype, 0):5.2f}   n={len(lens[ctype])}")
    if bad:
        print(f"{indent}  LỖI: {dict(bad)}")
    return {"avg_spans": avg_spans, "pct_with_code": pct_code,
            "errors": sum(bad.values())}


#: Các nguồn dữ liệu sinh ra, theo thứ tự trong đường ống.
SOURCES = (("synthetic", SYNTHETIC_ANNOTATIONS),
           ("translated", TRANSLATED_ANNOTATIONS),
           ("restyled", RESTYLED_ANNOTATIONS))


def cmd_verify(args) -> int:
    got = [(name, sorted(d.glob("*.json"))) for name, d in SOURCES]
    got = [(name, files) for name, files in got if files]
    all_files = [f for _, files in got for f in files]
    if not all_files:
        sys.exit(f"chưa có tài liệu nào trong {BASE_DIR.relative_to(REPO)}"
                 f" — chạy emit, translate hoặc restyle trước")

    print(f"\n{'=' * 60}\n{'KIỂM TRA DỮ LIỆU SINH RA':^60}\n{'=' * 60}\n")
    for name, d in SOURCES:
        n = len(dict(got).get(name, []))
        print(f"  {name + ':':12} {n:3d} file  ({d.relative_to(REPO)})")
    print(f"  {'TỔNG:':12} {len(all_files):3d} file\n")

    icd_codes = {r["code"] for r in load_icd()}
    # Nhận cả mã gốc lẫn mã đã quy về hoạt chất: lô sinh trước khi có bảng ánh xạ
    # mang mã biệt dược, vẫn là mã tra được trong bảng BTC nên không phải lỗi.
    rx = load_rxnorm()
    rx_codes = {r["rxcui"] for r in rx} | {c for r in rx for c in r["codes"]}
    stats_all = verify_dataset(all_files, icd_codes, rx_codes)

    if len(got) > 1:
        print(f"\n{'=' * 60}\n{'SO SÁNH CÁC NGUỒN':^60}\n{'=' * 60}\n")
        stats = {}
        for name, files in got:
            print(f"{name.upper()}:")
            stats[name] = verify_dataset(files, icd_codes, rx_codes, indent="    ")
            print()
        names = [n for n, _ in got]
        print(f"{'-' * 60}")
        print(f"  {'':14}" + "".join(f"{n:>12}" for n in names) + f"{'mốc':>12}")
        print(f"  {'span/file':14}"
              + "".join(f"{stats[n]['avg_spans']:>12.1f}" for n in names) + f"{'48 (gold)':>12}")
        print(f"  {'span có mã':14}"
              + "".join(f"{stats[n]['pct_with_code']:>11.0f}%" for n in names) + f"{'>50%':>12}")
        print(f"  {'lỗi offset':14}"
              + "".join(f"{stats[n]['errors']:>12d}" for n in names) + f"{'0':>12}")

    return 1 if stats_all["errors"] else 0


# ------------------------------------------------------------------- gọi LLM

def call_api(prompts: list[str], system: str, model: str,
             max_tokens: int = 4000) -> list[str]:
    """Gọi OpenAI Chat Completions tuần tự bằng urllib — không thêm phụ thuộc.

    max_tokens 4000 chứ không thấp hơn: model reasoning tiêu hết hạn mức cho suy
    luận rồi trả về rỗng (finish_reason=length) ở lô thử đầu với 1500.

    Hai chỗ khác nhau giữa các dòng model, xử lý bằng thử-rồi-lùi thay vì đoán
    theo tên model (tên model đổi liên tục, đoán sai thì hỏng cả lô):
      - dòng reasoning (o-series, gpt-5) từ chối `max_tokens`, chỉ nhận
        `max_completion_tokens`; dòng cũ thì ngược lại. Gửi cái mới trước, HTTP
        400 nhắc tới tham số thì gửi lại bằng cái cũ.
      - dòng reasoning cũng từ chối `temperature` khác 1, nên không gửi
        `temperature` gì cả — mặc định của API là đủ.

    OPENAI_BASE_URL đổi được để trỏ sang endpoint tương thích OpenAI (Azure,
    vLLM, OpenRouter...) mà không phải sửa mã.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("thiếu OPENAI_API_KEY — bỏ --use-api để chỉ ghi prompt ra đĩa")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    tok_field = "max_completion_tokens"

    def send(prompt: str, field: str):
        body = json.dumps({
            "model": model, field: max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {key}",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)

    out = []
    for i, prompt in enumerate(prompts, 1):
        try:
            try:
                data = send(prompt, tok_field)
            except urllib.error.HTTPError as exc:
                # Lỗi của OpenAI nằm trong BODY, nhưng gateway tương thích có thể
                # để ở reason — đọc cả hai, nếu không nhánh lùi không kích hoạt.
                try:
                    msg = exc.read()[:400].decode("utf-8", "replace")
                except Exception:                                 # noqa: BLE001
                    msg = ""
                msg = f"{msg} {exc.reason}"
                other = "max_tokens" if tok_field == "max_completion_tokens" else "max_completion_tokens"
                if exc.code == 400 and tok_field in msg:
                    tok_field = other          # nhớ lại, khỏi thử hai lần mỗi prompt
                    data = send(prompt, tok_field)
                else:
                    raise urllib.error.HTTPError(
                        exc.url, exc.code, msg, exc.headers, None) from None
            choices = data.get("choices") or [{}]
            out.append((choices[0].get("message") or {}).get("content") or "")
        except urllib.error.HTTPError as exc:
            print(f"  [{i}/{len(prompts)}] HTTP {exc.code}: {exc.reason!r:.200}")
            out.append("")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  [{i}/{len(prompts)}] lỗi: {exc}")
            out.append("")
        if i % 10 == 0:
            print(f"  {i}/{len(prompts)}")
    return out


# ------------------------------------------------------- bước 1: bốc + viết văn

def cmd_compose(args) -> int:
    rng = random.Random(args.seed)
    SYNTHETIC_WORK.mkdir(parents=True, exist_ok=True)

    print("đọc bảng ban tổ chức...")
    icd = load_icd()
    rx = load_rxnorm()
    rx_common = common_drugs(rx)
    print(f"  ICD {len(icd)} alias / {len({r['code'] for r in icd})} mã"
          f" | RxNorm {len(rx)} alias (IN/BN), {len(rx_common)} trong bảng tần số")

    pools = {"icd": icd, "rx": rx, "rx_common": rx_common,
             "sym": list(SYMPTOMS), "test": list(TEST_NAMES), "res": list(RESULT_PHRASES)}
    bundles = [{"id": f"synthetic_{i:04d}", "bundle": sample_bundle(rng, pools)}
               for i in range(args.n)]
    path_b = SYNTHETIC_WORK / "entity_bundles.jsonl"
    with path_b.open("w", encoding="utf-8") as fh:
        for b in bundles:
            fh.write(json.dumps(b, ensure_ascii=False) + "\n")
    print(f"đã bốc {len(bundles)} bộ thực thể -> {path_b}")
    print(f"  TB {st.mean(len(b['bundle']) for b in bundles):.1f} cụm/bệnh án")

    prompts = ["DANH SÁCH CỤM BẮT BUỘC:\n" +
               "\n".join(f"- {it['type']}: {it['text']}" for it in b["bundle"])
               for b in bundles]
    path_c = SYNTHETIC_WORK / "composed_texts.jsonl"
    if args.use_api:
        texts = call_api(prompts, COMPOSE_SYS, args.model)
    elif args.composed:
        loaded = {json.loads(l)["id"]: json.loads(l)["composed"]
                  for l in Path(args.composed).read_text(encoding="utf-8").splitlines()}
        texts = [loaded.get(b["id"], "") for b in bundles]
    else:
        path_p = SYNTHETIC_WORK / "prompts.jsonl"
        with path_p.open("w", encoding="utf-8") as fh:
            for b, p in zip(bundles, prompts):
                fh.write(json.dumps({"id": b["id"], "system": COMPOSE_SYS,
                                     "prompt": p}, ensure_ascii=False) + "\n")
        print(f"  chưa gọi API — prompt ở {path_p}")
        print(f"  gọi model nào cũng được rồi nạp lại: emit --composed FILE")
        print(f"  (FILE mỗi dòng: {{\"id\": \"synthetic_0000\", \"composed\": \"...\"}})")
        return 0
    with path_c.open("w", encoding="utf-8") as fh:
        for b, t in zip(bundles, texts):
            fh.write(json.dumps({"id": b["id"], "composed": t}, ensure_ascii=False) + "\n")
    ok = sum(1 for t in texts if len(BRACKET.findall(t)) >= 12)
    print(f"đã viết {ok}/{len(texts)} bản dùng được -> {path_c}")
    return 0


# ------------------------------------------------------- bước 2: bóc dấu -> nhãn

def cmd_emit(args) -> int:
    rng = random.Random(args.seed + 1)
    src_c = Path(args.composed) if args.composed else SYNTHETIC_WORK / "composed_texts.jsonl"
    if not src_c.exists():
        sys.exit(f"chưa có {src_c} — chạy compose trước")
    src_b = SYNTHETIC_WORK / "entity_bundles.jsonl"
    if not src_b.exists():
        sys.exit(f"chưa có {src_b} — chạy compose trước")
    bundles = {json.loads(l)["id"]: json.loads(l)["bundle"]
               for l in src_b.read_text(encoding="utf-8").splitlines()}

    # Tra lại mã THUỐC theo bảng hiện tại thay vì dùng mã đã đóng băng trong bundle.
    # Bundle sinh ra trước khi có bảng biệt dược->hoạt chất nên mang mã biệt dược;
    # tra lại ở đây sửa được cả lô cũ mà không phải gọi API viết lại văn bản.
    drug_codes = {r["alias"].lower(): r["codes"] for r in load_rxnorm()}
    n_remap = 0
    for bundle in bundles.values():
        for item in bundle:
            if item["type"] != "THUỐC":
                continue
            codes = drug_codes.get(item["text"].lower())
            if codes and codes != item["candidates"]:
                item["candidates"] = list(codes)
                n_remap += 1
    if n_remap:
        print(f"  quy {n_remap} mã thuốc về hoạt chất theo bảng RxNorm đầy đủ")

    SYNTHETIC_ANNOTATIONS.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_TEXT.mkdir(parents=True, exist_ok=True)

    n_ok, n_mask, n_nfd = 0, 0, 0
    reasons: collections.Counter = collections.Counter()
    by_type: collections.Counter = collections.Counter()
    for line in src_c.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        bundle = bundles.get(row["id"])
        if not bundle or not row.get("composed"):
            reasons["không có bản viết"] += 1
            continue
        res = unwrap(row["composed"], bundle)
        if isinstance(res, str):
            reasons[res] += 1
            continue
        text, records = res
        text, records = postprocess(rng, text, records, args)
        if text is None:
            reasons["hậu xử lý hỏng offset"] += 1
            continue
        n_ok += 1
        n_mask += sum(1 for r in records if "*" in r["text"])
        n_nfd += int(text != ud.normalize("NFC", text))
        for r in records:
            by_type[r["type"]] += 1
        (SYNTHETIC_TEXT / f"{row['id']}.txt").write_text(text, encoding="utf-8")
        (SYNTHETIC_ANNOTATIONS / f"{row['id']}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"đã sinh {n_ok} tài liệu vào {SYNTHETIC_ANNOTATIONS.relative_to(REPO)}")
    print(f"  văn bản: {SYNTHETIC_TEXT.relative_to(REPO)}")
    print(f"  bẫy ***: {n_mask} span | NFD: {n_nfd} file")
    if reasons:
        print(f"  loại: {dict(reasons)}")
    print(f"  span theo type: {dict(by_type)}")
    return 0


# ---------------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sinh bệnh án tiếng Việt tổng hợp (bản độc lập)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("CÁCH LÀM")[1])
    # --seed khai ở cả cha lẫn từng lệnh con: argparse không cho đặt cờ của parser
    # cha SAU tên lệnh con, mà "compose --seed 7" là cách gõ tự nhiên hơn.
    ap.add_argument("--seed", type=int, default=SEED)
    sub = ap.add_subparsers(dest="cmd", required=True)
    seed_arg = argparse.ArgumentParser(add_help=False)
    seed_arg.add_argument("--seed", type=int, default=SEED)

    c = sub.add_parser("compose", parents=[seed_arg], help="bốc thực thể + gọi LLM viết bệnh án")
    c.add_argument("--n", type=int, default=200, help="số bệnh án cần sinh")
    c.add_argument("--use-api", action="store_true",
                   help="gọi OpenAI API (cần OPENAI_API_KEY)")
    c.add_argument("--model", default="gpt-4o",
                   help="model dùng khi --use-api")
    c.add_argument("--composed", help="nạp bản viết sẵn thay vì gọi API")

    e = sub.add_parser("emit", parents=[seed_arg], help="bóc dấu 〔 〕 -> văn bản + nhãn")
    e.add_argument("--composed", help="file bản viết (mặc định intermediate/composed_texts.jsonl)")
    e.add_argument("--mask-rate", type=float, default=0.12,
                   help="tỉ lệ span THUỐC bị che *** (mặc định cho ra 30%% FILE có bẫy, khớp test)")
    e.add_argument("--nfd-rate", type=float, default=0.20,
                   help="tỉ lệ file ở dạng NFD (test: 20/100 file)")

    t = sub.add_parser("translate", parents=[seed_arg],
                       help="dịch bệnh án mtsamples -> tiếng Việt + nhãn")
    t.add_argument("--n", type=int, default=100, help="số bệnh án cần dịch")
    t.add_argument("--n-categories", type=int, default=8,
                   help="số danh mục mtsamples bốc đều (mặc định 8)")
    t.add_argument("--use-api", action="store_true",
                   help="gọi OpenAI API (cần OPENAI_API_KEY)")
    t.add_argument("--model", default="gpt-4o", help="model dùng để dịch")
    t.add_argument("--max-tokens", type=int, default=4000,
                   help="hạn mức token mỗi bản dịch")
    t.add_argument("--source", default="auto",
                   help="'auto' = data/external/en_notes/mtsamples_filtered.jsonl,"
                        " hoặc đường dẫn file jsonl khác")
    t.add_argument("--translated", help="nạp bản dịch sẵn thay vì gọi API")
    t.add_argument("--min-lab", type=int, default=0,
                   help="chỉ lấy note có ít nhất N lần nhắc xét nghiệm"
                        " (kho: 147 note >=1, 69 note >=3, 41 note >=5)")
    t.add_argument("--min-spans", type=int, default=12,
                   help="ngưỡng span tối thiểu để giữ tài liệu (gold ít nhất 13)")
    t.add_argument("--common-drugs-only", action="store_true",
                   help="chỉ tra tên thuốc trong bảng tần số, ít nhiễu hơn nhưng sót nhiều")
    t.add_argument("--mask-file-rate", type=float, default=0.30,
                   help="tỉ lệ FILE có ít nhất một span THUỐC bị che *** (test: 30/100)")
    t.add_argument("--nfd-rate", type=float, default=0.20,
                   help="tỉ lệ file ở dạng NFD (test: 20/100 file)")

    r = sub.add_parser("restyle", parents=[seed_arg],
                       help="viết lại bản dịch sang các thể loại của đề thi")
    r.add_argument("--n", type=int, help="số bản viết lại (mặc định: tất cả)")
    r.add_argument("--use-api", action="store_true",
                   help="gọi OpenAI API (cần OPENAI_API_KEY)")
    r.add_argument("--model", default="gpt-4o", help="model dùng để viết lại")
    r.add_argument("--max-tokens", type=int, default=4000)
    r.add_argument("--source", help="file translation_process.jsonl (mặc định của translate)")
    r.add_argument("--restyled", help="nạp bản viết lại sẵn thay vì gọi API")
    r.add_argument("--genre", choices=list(RESTYLE_GENRES),
                   help="ép một thể loại duy nhất (mặc định: trộn theo tỉ lệ đo trên data/test)")
    r.add_argument("--min-keep", type=float, default=0.30,
                   help="tỉ lệ dấu 〔 〕 tối thiểu phải giữ lại thì mới nhận bản viết lại")
    r.add_argument("--min-spans", type=int, default=12)
    r.add_argument("--mask-file-rate", type=float, default=0.30)
    r.add_argument("--nfd-rate", type=float, default=0.20)

    sub.add_parser("verify", parents=[seed_arg], help="kiểm offset, mã, và đối chiếu với test")

    args = ap.parse_args()
    return {"compose": cmd_compose, "emit": cmd_emit, "translate": cmd_translate,
            "restyle": cmd_restyle, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
