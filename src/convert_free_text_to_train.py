import re
import os
from underthesea import word_tokenize

def load_keywords():
    """Từ điển keyword để gán nhãn tự động"""
    return {
        "BENH_NHAN": ["bệnh nhân", "trẻ", "nam", "nữ", "tuổi"],
        "TRIỆU_CHỨNG": ["sốt", "đau", "ho", "ban đỏ", "mắt đỏ", "môi đỏ", "lưỡi đỏ", "sưng", "bong da"],
        "BENH": ["Kawasaki", "viêm mạch", "viêm tim", "phình động mạch"],
        "XET_NGHIEM": ["siêu âm tim", "ECG", "CRP", "men gan", "cấy máu", "xét nghiệm"],
        "THUOC": ["IVIG", "aspirin", "ASA", "immunoglobulin"],
        "PHAU_THUAT": ["phẫu thuật", "can thiệp"]
    }

def assign_label(word, context):
    """Gán nhãn heuristic"""
    word_lower = word.lower()
    keywords = load_keywords()
    
    for entity_type, kws in keywords.items():
        if any(kw in word_lower or kw in context.lower() for kw in kws):
            return f"B-{entity_type}" if " " not in word else f"I-{entity_type}"
    return "O"

def convert_free_text_to_train(input_text_or_file, output_file="data/train.txt"):
    os.makedirs("data", exist_ok=True)
    
    if isinstance(input_text_or_file, str) and input_text_or_file.endswith(".txt"):
        with open(input_text_or_file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = input_text_or_file
    
    # Tách thành các đoạn (paragraph)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    
    with open(output_file, "w", encoding="utf-8") as f:
        for para in paragraphs:
            if not para.strip():
                continue
                
            # Word segmentation
            words = word_tokenize(para)
            
            for word in words:
                if not word.strip():
                    continue
                label = assign_label(word, para)  # gán dựa trên context
                f.write(f"{word} {label}\n")
            
            f.write("\n")  # separator giữa các đoạn
    
    print(f"✅ Đã chuyển đổi thành công → {output_file}")
    print(f"Số đoạn văn: {len(paragraphs)}")

# ==================== SỬ DỤNG ====================

if __name__ == "__main__":
    # Paste trực tiếp văn bản của bạn hoặc đọc từ file
    sample_text = """1. Bệnh Kawasaki là gì?
Bệnh Kawasaki là tình trạng sốt cấp kéo dài..."""  # (dán toàn bộ văn bản vào đây)

    convert_free_text_to_train(sample_text, "data/train.txt")