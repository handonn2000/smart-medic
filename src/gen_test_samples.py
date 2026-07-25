import random
import os
import re
from underthesea import word_tokenize

def load_keywords():
    return {
        "BENH_NHAN": ["bệnh nhân", "trẻ", "nam", "nữ", "tuổi"],
        "TRIỆU_CHỨNG": ["sốt", "đau", "ho", "ban đỏ", "mắt đỏ", "môi đỏ", "lưỡi đỏ", "sưng", "bong da", "khớp"],
        "BENH": ["Kawasaki", "viêm mạch", "viêm tim", "phình động mạch", "viêm khớp"],
        "XET_NGHIEM": ["siêu âm tim", "ECG", "CRP", "men gan", "cấy máu", "Axit Uric", "Đường huyết"],
        "THUOC": ["IVIG", "aspirin", "ASA", "Celecoxib", "Paracetamol", "Metformin", "Esomeprazol"],
        "PHAU_THUAT": ["phẫu thuật", "can thiệp"]
    }

def assign_label(word, context):
    """Gán nhãn heuristic"""
    word_lower = word.lower()
    for entity_type, kws in load_keywords().items():
        if any(kw.lower() in word_lower or kw.lower() in context.lower() for kw in kws):
            # Ưu tiên B- cho từ đầu cụm
            return f"B-{entity_type}" if " " not in word else f"I-{entity_type}"
    return "O"

def generate_synthetic_samples(n=50):
    """Sinh data tổng hợp"""
    samples = []
    gioi = ["nam", "nữ"]
    trieu = ["đau khớp gối phải", "sưng khớp", "ho khan", "sốt cao", "đau bụng"]
    benh = ["viêm khớp", "tăng huyết áp", "Kawasaki"]
    thuoc = ["Celecoxib 400mg", "Paracetamol 500mg", "Esomeprazol 20mg"]
    xet = ["Axit Uric máu", "Đường huyết", "Chức năng gan"]
    
    for _ in range(n):
        sentence = f"Bệnh nhân {random.choice(gioi)} {random.randint(20,70)} tuổi, bị {random.choice(trieu)}, chẩn đoán {random.choice(benh)}. Xét nghiệm {random.choice(xet)} kết quả bình thường. Kê đơn {random.choice(thuoc)}."
        samples.append(sentence)
    return samples

def convert_to_train_format(text_list, output_file="data/train.txt"):
    os.makedirs("data", exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        for text in text_list:
            # Word segmentation
            words = word_tokenize(text)
            
            for word in words:
                if not word.strip():
                    continue
                label = assign_label(word, text)
                f.write(f"{word} {label}\n")
            
            f.write("\n")  # separator giữa các mẫu

    print(f"✅ Đã tạo file train.txt với {len(text_list)} mẫu tại {output_file}")

# ====================== MAIN ======================
if __name__ == "__main__":
    # ================== PHẦN FREE-TEXT CỦA BẠN ==================
    free_text = """
1. Bệnh Kawasaki là gì?

Bệnh Kawasaki là tình trạng sốt cấp kéo dài, thường đi kèm phát ban toàn thân, với đặc điểm chính là viêm lan tỏa hệ mạch máu nhỏ và vừa, bao gồm động mạch vành – mạch máu quan trọng cung cấp máu cho tim. Bệnh được mô tả lần đầu bởi bác sĩ Tomisaku Kawasaki (Nhật Bản) vào năm 1967.
 • Độ tuổi thường gặp: Chủ yếu ở trẻ dưới 5 tuổi, đặc biệt là nhóm bú mẹ.
 • Giới tính: Trẻ trai mắc bệnh nhiều hơn trẻ gái.
 • Đặc điểm nguy hiểm: Giai đoạn đầu có thể chưa quá nghiêm trọng, nhưng nếu không điều trị kịp thời, bệnh có thể dẫn đến viêm tim, phình giãn động mạch vành, đột tử, nhồi máu cơ tim, hoặc hẹp tắc mạch vành gây suy tim về sau.

Tóm lại: Kawasaki là bệnh viêm mạch máu nguy hiểm, cần phát hiện sớm để tránh biến chứng nặng.
... (dán toàn bộ nội dung free-text của bạn vào đây)
"""

    # ================== TẠO DATA TỔNG HỢP + FREE-TEXT ==================
    synthetic = generate_synthetic_samples(60)          # 60 mẫu synthetic
    free_samples = [p for p in re.split(r'\n\s*\n', free_text) if p.strip()]  # tách đoạn

    all_samples = synthetic + free_samples
    
    convert_to_train_format(all_samples, "data/train.txt")
    
    print(f"Hoàn thành! Tổng số mẫu: {len(all_samples)}")