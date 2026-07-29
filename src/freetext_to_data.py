import argparse
import os
from underthesea import word_tokenize

# Keyword sources (Vietnamese clinical / NER literature & common hospital vocab):
# - ViMedNER / VietBioNER / PhoNER_COVID19 entity types
# - Hello Bacsi, Thu Cúc, VnExpress Sức khỏe (symptoms & diseases)
# - BvNTP nhà thuốc lists, BHYT drug appendix (medications)
# - Common Vietnamese lab / imaging / surgery terms


def load_keywords():
    return {
        "BENH_NHAN": [
            "bệnh nhân", "người bệnh", "bệnh nhi", "trẻ", "trẻ em", "trẻ sơ sinh",
            "trẻ bú mẹ", "bé", "nam", "nữ", "nam giới", "nữ giới", "ông", "bà",
            "cậu", "cô", "anh", "chị", "tuổi", "tuổi thọ", "bệnh sử", "tiền sử",
            "tiền sử bệnh", "tiền sử gia đình", "bệnh nền", "người nhà", "thân nhân",
            "người lớn", "người già", "người cao tuổi", "thai phụ", "sản phụ",
            "bà mẹ", "bệnh nhân nội trú", "bệnh nhân ngoại trú",
        ],
        "TRIEU_CHUNG": [
            # Tổng quát / toàn thân
            "sốt", "sốt cao", "sốt nhẹ", "sốt kéo dài", "rét run", "ớn lạnh",
            "mệt", "mệt mỏi", "uể oải", "suy nhược", "chán ăn", "ăn kém",
            "sụt cân", "tăng cân", "ra mồ hôi", "đổ mồ hôi đêm", "mất ngủ",
            "li bì", "lú lẫn", "choáng", "ngất", "hạ huyết áp", "tăng huyết áp", "vết loét",
            # Hô hấp
            "ho", "ho khan", "ho có đờm", "ho đờm", "ho ra máu", "khạc đờm",
            "khó thở", "thở nhanh", "thở gấp", "thở khò khè", "thở rít",
            "đau ngực", "tức ngực", "nghẹt mũi", "sổ mũi", "chảy mũi",
            "đau họng", "khàn tiếng", "khó nuốt", "đờm", "tím tái",
            # Tim mạch
            "hồi hộp", "đánh trống ngực", "nhịp tim nhanh", "nhịp tim chậm",
            "phù", "phù nề", "phù chân", "phù phổi", "đau thắt ngực",
            # Tiêu hóa
            "buồn nôn", "nôn", "nôn mửa", "ói", "đau bụng", "đầy bụng",
            "chướng bụng", "tiêu chảy", "táo bón", "đi ngoài", "phân đen",
            "phân máu", "ợ nóng", "ợ chua", "khó tiêu", "ỉa chảy",
            # Thần kinh / cơ xương khớp
            "đau đầu", "đau nửa đầu", "chóng mặt", "hoa mắt", "tê", "tê bì",
            "yếu liệt", "co giật", "run tay", "đau lưng", "đau cột sống",
            "đau khớp", "sưng khớp", "cứng khớp", "đau cơ", "nhức mỏi",
            "đau gối", "đau vai", "hạn chế vận động",
            # Da / mắt / tai
            "ban đỏ", "phát ban", "mẩn ngứa", "ngứa", "nổi mề đay",
            "bong da", "vàng da", "vàng mắt", "mắt đỏ", "môi đỏ", "lưỡi đỏ",
            "sung huyết", "sưng", "sưng hạch", "nổi hạch", "loét", "mụn mủ",
            "đau tai", "ù tai", "chảy mủ tai",
            # Tiết niệu / sản khoa
            "đái buốt", "đái dắt", "tiểu máu", "tiểu ra máu", "tiểu đêm", "bí tiểu",
            "đau lưng dưới", "ra máu âm đạo", "rong kinh", "đau bụng kinh",
            # hình ảnh học
            "độ tương phản", "Baker", "nang Baker"
        ],
        "BENH": [
            # Tim mạch
            "Kawasaki", "bệnh Kawasaki", "viêm mạch", "viêm mạch máu",
            "viêm tim", "viêm cơ tim", "viêm màng ngoài tim", "viêm nội tâm mạc",
            "phình động mạch", "phình động mạch vành", "hẹp động mạch vành",
            "nhồi máu cơ tim", "đột quỵ", "tai biến mạch máu não", "suy tim",
            "rung nhĩ", "loạn nhịp tim", "tăng huyết áp", "hạ huyết áp",
            "xơ vữa động mạch", "huyết khối", "thuyên tắc phổi",
            # Hô hấp
            "viêm phổi", "viêm phế quản", "viêm tiểu phế quản", "hen suyễn",
            "COPD", "lao phổi", "lao", "lao đa kháng thuốc",
            "viêm họng", "viêm amidan", "viêm xoang", "viêm thanh quản",
            "cúm", "cảm lạnh", "COVID-19", "SARS-CoV-2", "viêm mũi dị ứng",
            # Nội tiết / chuyển hóa
            "đái tháo đường", "tiểu đường", "Gout", "gút", "béo phì",
            "cường giáp", "suy giáp", "hội chứng chuyển hóa", "rối loạn lipid máu",
            # Cơ xương khớp
            "viêm khớp", "viêm khớp dạng thấp", "thoái hóa khớp", "thoái hóa",
            "loãng xương", "thoát vị đĩa đệm", "đau thần kinh tọa",
            "viêm bao gân", "lupus", "lupus ban đỏ hệ thống", "viêm bao gân", "viêm bao hoạt dịch",
            # Tiêu hóa / gan mật
            "viêm dạ dày", "loét dạ dày", "trào ngược dạ dày", "GERD",
            "viêm ruột thừa", "viêm đại tràng", "hội chứng ruột kích thích",
            "viêm gan", "viêm gan B", "viêm gan C", "xơ gan", "sỏi mật",
            "viêm tụy", "ung thư dạ dày", "ung thư gan", "ung thư đại tràng",
            # Thận / tiết niệu
            "viêm thận", "suy thận", "suy thận mạn", "sỏi thận",
            "nhiễm khuẩn tiết niệu", "viêm bàng quang", "ung thư thận",
            # Thần kinh / tâm thần
            "động kinh", "Parkinson", "Alzheimer", "sa sút trí tuệ",
            "đau nửa đầu", "migraine", "trầm cảm", "lo âu", "đột tử",
            "u thần kinh",
            # Nhiễm khuẩn / khác
            "nhiễm trùng", "nhiễm khuẩn", "nhiễm virus", "nhiễm nấm",
            "nhiễm khuẩn huyết", "nhiễm trùng huyết", "sốc nhiễm khuẩn",
            "sốt xuất huyết", "sốt rét", "sởi", "thủy đậu", "zona",
            "HIV", "AIDS", "ung thư", "ung thư phổi", "ung thư vú",
            "thiếu máu", "thiếu máu thiếu sắt", "bạch cầu cấp",
            "tràn dịch", "tràn dịch khớp", "tràn dịch màng phổi",
        ],
        "XET_NGHIEM": [
            # Xét nghiệm máu / sinh hóa
            "xét nghiệm", "xét nghiệm máu", "công thức máu", "sinh hóa máu",
            "CRP", "ESR", "VS", "procalcitonin", "PCT",
            "đường huyết", "glucose máu", "HbA1c", "đường huyết đói",
            "Axit Uric", "acid uric", "ure", "creatinin", "creatinine",
            "men gan", "AST", "ALT", "SGOT", "SGPT", "bilirubin",
            "albumin", "protein máu", "cholesterol", "triglycerid",
            "HDL", "LDL", "điện giải đồ", "natri", "kali", "canxi",
            "CK", "CK-MB", "troponin", "BNP", "NT-proBNP",
            "D-dimer", "INR", "PT", "aPTT", "fibrinogen",
            "TSH", "FT4", "FT3", "T3", "T4", "PSA", "AFP", "CEA",
            "CA125", "CA19-9", "beta-HCG", "ferritin", "vitamin D",
            "vitamin B12", "hồng cầu", "bạch cầu", "tiểu cầu", "hemoglobin",
            "hematocrit", "Hct", "Hb", "WBC", "RBC", "PLT",
            # Vi sinh / miễn dịch
            "cấy máu", "cấy đờm", "cấy nước tiểu", "kháng sinh đồ",
            "GeneXpert", "AFB", "Mantoux", "HIV test", "HBsAg", "Anti-HCV",
            "dengue NS1", "IgM", "IgG", "PCR", "RT-PCR", "antigen",
            # Chẩn đoán hình ảnh / chức năng
            "siêu âm", "siêu âm tim", "siêu âm bụng", "siêu âm Doppler",
            "ECG", "Điện tâm đồ", "điện tim", "Holter", "Holter ECG",
            "X-quang", "x quang", "x-quang ngực", "CT", "CT scan",
            "MRI", "cộng hưởng từ", "PET-CT", "nội soi", "nội soi dạ dày",
            "nội soi đại tràng", "nội soi phế quản", "đo chức năng hô hấp",
            "spirometry", "đo SpO2", "SpO2", "đo huyết áp", "mạch",
            "nhiệt độ", "cân nặng", "chiều cao", "BMI",
            "sinh thiết", "chọc dò", "chọc hút", "điện não đồ", "EEG",
            "điện cơ đồ", "EMG", "đo mật độ xương", "DEXA",
        ],
        "THUOC": [
            # Giảm đau / hạ sốt / kháng viêm
            "Paracetamol", "Acetaminophen", "Ibuprofen", "Diclofenac",
            "Naproxen", "Meloxicam", "Celecoxib", "Etoricoxib",
            "Aspirin", "ASA", "Nimesulide", "Tramadol", "Morphine",
            "Codein", "Nefopam", "Piroxicam", "Ketoprofen",
            # Corticoid
            "Prednisolon", "Prednisolone", "Methylprednisolon",
            "Dexamethason", "Hydrocortison", "Betamethason", "Triamcinolon",
            # Kháng sinh
            "Amoxicillin", "Amoxicilin", "Augmentin", "Ampicillin",
            "Cefuroxim", "Cefixim", "Ceftriaxone", "Cefotaxime",
            "Cephalexin", "Azithromycin", "Clarithromycin", "Erythromycin",
            "Ciprofloxacin", "Levofloxacin", "Ofloxacin", "Moxifloxacin",
            "Metronidazol", "Clindamycin", "Gentamycin", "Vancomycin",
            "Doxycyclin", "Cotrimoxazole", "Penicillin", "Meropenem",
            "Imipenem", "Piperacillin", "Tazobactam",
            # Tim mạch / huyết áp
            "Amlodipine", "Nifedipine", "Losartan", "Valsartan",
            "Telmisartan", "Enalapril", "Perindopril", "Ramipril",
            "Captopril", "Bisoprolol", "Metoprolol", "Atenolol",
            "Carvedilol", "Propranolol", "Furosemide", "Spironolactone",
            "Hydrochlorothiazide", "Clopidogrel", "Warfarin", "Rivaroxaban",
            "Apixaban", "Heparin", "Enoxaparin", "Digoxin", "Nitroglycerin",
            "Isosorbide", "Atorvastatin", "Rosuvastatin", "Simvastatin", "Hydralazine",
            "Zocor",
            # Tiểu đường / nội tiết
            "Metformin", "Gliclazide", "Glimepiride", "Sitagliptin",
            "Vildagliptin", "Saxagliptin", "Insulin", "Acarbose",
            "Empagliflozin", "Dapagliflozin", "Levothyroxine", "Methimazole",
            # Tiêu hóa
            "Omeprazol", "Esomeprazol", "Pantoprazol", "Lansoprazol",
            "Rabeprazol", "Ranitidin", "Famotidin", "Domperidon",
            "Metoclopramid", "Ondansetron", "Loperamide", "Smecta",
            "Lactulose", "Magnesium", "Antacid",
            # Hô hấp / dị ứng
            "Salbutamol", "Ventolin", "Budesonide", "Fluticasone",
            "Montelukast", "Theophylline", "Acetylcystein", "Ambroxol",
            "Bromhexine", "Loratadin", "Cetirizin", "Fexofenadine",
            "Chlorpheniramin", "Diphenhydramin", "Pseudoephedrin",
            # Thần kinh / tâm thần
            "Gabapentin", "Pregabalin", "Carbamazepin", "Valproate",
            "Phenytoin", "Sertraline", "Fluoxetine", "Escitalopram",
            "Amitriptylin", "Diazepam", "Alprazolam", "Lorazepam",
            "Haloperidol", "Risperidone", "Quetiapine",
            # Kawasaki / đặc hiệu / khác
            "IVIG", "immunoglobulin", "Colchicine", "Allopurinol",
            "Febuxostat", "Acyclovir", "Oseltamivir", "Tamiflu",
            "Tenofovir", "Lamivudine", "Rifampicin", "Isoniazid",
            "Pyrazinamide", "Ethambutol", "Albendazol", "Mebendazol",
            "Fluconazol", "Nystatin", "Ketoconazol",
        ],
        "PHAU_THUAT": [
            "phẫu thuật", "mổ", "can thiệp", "can thiệp mạch vành",
            "nong mạch", "đặt stent", "stent", "bypass", "bắc cầu mạch vành",
            "phẫu thuật tim", "mổ tim hở", "thay van tim", "cấy máy tạo nhịp",
            "phẫu thuật nội soi", "nội soi ổ bụng", "cắt ruột thừa",
            "cắt túi mật", "cắt dạ dày", "cắt đại tràng", "cắt tử cung",
            "sinh mổ", "mổ lấy thai", "phẫu thuật chỉnh hình",
            "thay khớp", "thay khớp gối", "thay khớp háng", "nẹp vít",
            "cố định xương", "ghép thận", "ghép gan", "ghép tủy",
            "cắt amidan", "nạo VA", "phẫu thuật thần kinh",
            "mổ thoát vị", "cắt bỏ u", "sinh thiết phẫu thuật",
            "chọc hút dịch", "dẫn lưu", "mở khí quản", "đặt nội khí quản",
            "thở máy", "lọc máu", "chạy thận", "thẩm phân phúc mạc",
            "xạ trị", "hóa trị", "điều trị nhắm đích", "phẫu thuật thẩm mỹ",
            "tái tạo dây chằng"
        ],
        "TAC_NHAN_NGOAI_SINH": [
            "chấn thương", "té", "ngã"
        ]
    }


def _build_keyword_patterns(keywords=None):
    """Danh sách (entity_type, keyword) ưu tiên cụm dài trước để greedy match."""
    keywords = keywords or load_keywords()
    patterns = []
    for entity_type, kws in keywords.items():
        for kw in kws:
            kw_norm = " ".join(kw.lower().split())
            if kw_norm:
                patterns.append((entity_type, kw_norm))
    # Dài hơn trước; cùng độ dài thì giữ thứ tự ổn định
    patterns.sort(key=lambda x: (-len(x[1]), x[0], x[1]))
    return patterns


def label_words(words, patterns=None):
    """
    Gán nhãn BIO theo khớp cụm từ khóa trên chuỗi token.
    Chỉ gán nhãn khi token (hoặc chuỗi token liên tiếp) khớp đúng keyword,
    không dùng cả câu làm context (tránh mọi từ bị gán BENH_NHAN).
    """
    if patterns is None:
        patterns = _build_keyword_patterns()

    n = len(words)
    labels = ["O"] * n
    i = 0
    while i < n:
        matched = False
        for entity_type, kw in patterns:
            joined = ""
            for j in range(i, n):
                token = words[j].lower().strip()
                if not token:
                    break
                joined = token if j == i else f"{joined} {token}"
                if joined == kw:
                    labels[i] = f"B-{entity_type}"
                    for k in range(i + 1, j + 1):
                        labels[k] = f"I-{entity_type}"
                    i = j + 1
                    matched = True
                    break
                if not kw.startswith(joined):
                    break
            if matched:
                break
        if not matched:
            i += 1
    return labels


def convert_to_train_format(text_list, output_file="data/train.txt"):
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    patterns = _build_keyword_patterns()

    with open(output_file, "w", encoding="utf-8") as f:
        for text in text_list:
            words = [w for w in word_tokenize(text) if w.strip()]
            labels = label_words(words, patterns)

            for word, label in zip(words, labels):
                f.write(f"{word} {label}\n")

            f.write("\n")  # separator giữa các mẫu

    print(f"✅ Đã tạo file train với {len(text_list)} mẫu tại {output_file}")


def load_texts_from_folder(folder):
    """Đọc toàn bộ file .txt trong folder; mỗi file là một mẫu free-text."""
    if not os.path.isdir(folder):
        raise NotADirectoryError(f"Input path is not a folder: {folder}")

    txt_files = sorted(
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.lower().endswith(".txt") and os.path.isfile(os.path.join(folder, name))
    )
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in folder: {folder}")

    samples = []
    for path in txt_files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            samples.append(text)
    return samples, txt_files


def parse_args():
    parser = argparse.ArgumentParser(
        description="Chuyển free-text y tế trong folder thành dữ liệu NER dạng train."
    )
    parser.add_argument(
        "-f",
        "--folder",
        required=True,
        help="Đường dẫn folder chứa các file .txt free-text y tế.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="data/train.txt",
        help="Đường dẫn file output (mặc định: data/train.txt).",
    )
    return parser.parse_args()


# ====================== MAIN ======================
# python src/freetext_to_data.py -f data/generated_medical_records/translated/text -o data/training1.txt
if __name__ == "__main__":
    args = parse_args()

    samples, txt_files = load_texts_from_folder(args.folder)
    convert_to_train_format(samples, args.output)
    print(f"Hoàn thành! Đã xử lý {len(txt_files)} file .txt → {len(samples)} mẫu.")
