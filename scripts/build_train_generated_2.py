#!/usr/bin/env python3
"""Sinh ~20 bệnh án tiếng Việt (BIO) dựa trên ICD10_VN.csv + RXNORM.csv.

Nội dung mô phỏng cấu trúc bệnh án công khai (viêm phổi, ĐTĐ, suy tim…),
bọc thực thể 〔TYPE|…〕 rồi chuyển sang format train qua prepare_training_data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from gen_sample_data import unwrap_typed  # noqa: E402
from prepare_training_data import (  # noqa: E402
    blocks_of,
    label_words,
    make_segmenter,
    usable_spans,
    write_bio,
)
from tokenization import segment_document  # noqa: E402

OUT_DIR = REPO / "data" / "generated_medical_records" / "batch2"
TEXT_DIR = OUT_DIR / "text"
ANN_DIR = OUT_DIR / "annotations_gold"
BIO_OUT = REPO / "data" / "train_generated_2.txt"

# Surface form in note -> ICD-10 candidate from ICD10_VN.csv
DX_CODES = {
    "viêm phổi": ["J18.9"],
    "tăng huyết áp": ["I10"],
    "đái tháo đường type 2": ["E11.9"],
    "đái tháo đường": ["E11"],
    "suy tim": ["I50.9"],
    "bệnh phổi tắc nghẽn mãn tính": ["J44.9"],
    "hen": ["J45.9"],
    "viêm dạ dày": ["K29.7"],
    "bệnh trào ngược dạ dày - thực quản": ["K21"],
    "loét dạ dày": ["K25"],
    "động kinh": ["G40"],
    "nhồi máu não": ["I63"],
    "viêm gan virus B mạn": ["B18.1"],
    "giai đoạn trầm cảm": ["F32"],
    "thoái hóa khớp gối": ["M17"],
    "nhiễm khuẩn hệ tiết niệu": ["N39.0"],
    "tăng lipid máu": ["E78.5"],
    "suy thận mãn tính": ["N18"],
    "rung nhĩ": ["I48"],
    "suy giáp": ["E03.9"],
    "loãng xương": ["M81"],
    "gút": ["M10"],
    "sỏi mật": ["K80"],
    "sỏi thận": ["N20"],
    "viêm khớp dạng thấp": ["M05"],
    "nhiễm trùng đường hô hấp trên cấp": ["J06.9"],
}

# Surface form in note -> RxCUI from RXNORM.csv (IN/BN)
DRUG_CODES = {
    "metformin": ["6809"],
    "amlodipine": ["17767"],
    "atorvastatin": ["83367"],
    "losartan": ["52175"],
    "aspirin": ["1191"],
    "omeprazole": ["7646"],
    "metoprolol": ["6918"],
    "furosemide": ["4603"],
    "amoxicillin": ["723"],
    "prednisone": ["8640"],
    "warfarin": ["11289"],
    "clopidogrel": ["32968"],
    "pantoprazole": ["40790"],
    "levothyroxine": ["10582"],
    "gabapentin": ["25480"],
    "sertraline": ["36437"],
    "ibuprofen": ["5640"],
    "ciprofloxacin": ["2551"],
    "azithromycin": ["18631"],
    "hydrochlorothiazide": ["5487"],
    "bisoprolol": ["19484"],
    "spironolactone": ["9997"],
    "digoxin": ["3407"],
    "montelukast": ["8824"],
    "cetirizine": ["20610"],
    "paracetamol": ["161"],
    "enoxaparin": ["67108"],
    "budesonide": ["19831"],
    "telmisartan": ["73494"],
    "perindopril": ["54552"],
    "carvedilol": ["20352"],
    "atenolol": ["1202"],
    "simvastatin": ["36567"],
    "esomeprazole": ["283742"],
    "domperidone": ["3626"],
    "cefuroxime": ["2180"],
    "levofloxacin": ["82122"],
    "dexamethasone": ["3264"],
    "tramadol": ["10689"],
    "heparin": ["5224"],
    "salbutamol": ["435"],
    "valsartan": ["69749"],
    "nifedipine": ["7417"],
    "allopurinol": ["519"],
    "colchicine": ["2683"],
    "alendronate": ["46041"],
    "rosuvastatin": ["301542"],
    "insulin": ["400008"],
}

# 20 records inspired by public Vietnamese case-note patterns
# (viêm phổi + ĐTĐ + THA, suy tim, COPD, GERD, …) and KB drug/disease names.
MARKED_RECORDS: list[tuple[str, str]] = [
    (
        "ba_01_viem_phoi_cong_dong",
        """Bệnh án nội trú

1. Lý do vào viện:
Bệnh nhân nữ, 64 tuổi, vào viện vì 〔SYM|khó thở〕 và 〔SYM|sốt cao〕 kèm 〔SYM|ho〕 đờm vàng.

2. Bệnh sử:
Khoảng 5 ngày nay xuất hiện 〔SYM|sốt〕 38.5-39°C, 〔SYM|ho〕 có đờm, 〔SYM|khó thở〕 tăng dần. Không 〔SYM|đau ngực〕, không 〔SYM|chóng mặt〕.

3. Tiền sử:
〔DX|tăng huyết áp〕 8 năm, 〔DX|đái tháo đường type 2〕 5 năm. Đang dùng 〔DRUG|amlodipine〕 5 mg và 〔DRUG|metformin〕 500 mg.

4. Cận lâm sàng:
〔TEST|công thức máu toàn phần〕: 〔RES|tăng bạch cầu chiếm ưu thế bạch cầu trung tính〕.
〔TEST|X-quang ngực〕: 〔RES|tổn thương dạng kính mờ hai đáy phổi〕.
〔TEST|đường huyết〕: 〔RES|11.2 mmol/L〕. 〔TEST|spo2〕: 〔RES|92%〕.

5. Chẩn đoán:
〔DX|viêm phổi〕 cộng đồng mức độ trung bình / 〔DX|tăng huyết áp〕 / 〔DX|đái tháo đường type 2〕.

6. Điều trị:
〔DRUG|azithromycin〕 500 mg uống, 〔DRUG|amoxicillin〕 1 g x 2 lần/ngày, 〔DRUG|paracetamol〕 khi sốt, tiếp tục 〔DRUG|amlodipine〕 và 〔DRUG|metformin〕.
""",
    ),
    (
        "ba_02_suy_tim_dot_cap",
        """Hội chẩn tim mạch

Bệnh nhân nam 72 tuổi nhập viện vì 〔SYM|khó thở khi nằm〕 và 〔SYM|phù hai chi dưới〕 tăng 3 ngày.
Tiền sử 〔DX|suy tim〕, 〔DX|tăng huyết áp〕, 〔DX|rung nhĩ〕.
Khám: mạch không đều, phổi ran ẩm hai đáy, phù chân mềm 2+.
〔TEST|điện tâm đồ〕: 〔RES|rung nhĩ đáp ứng thất nhanh〕.
〔TEST|siêu âm tim qua thành ngực〕: 〔RES|chức năng tâm thu thất trái giảm〕, EF khoảng 35%.
〔TEST|BUN〕 〔RES|28 mg/dL〕, 〔TEST|creatinine〕 〔RES|1.4 mg/dL〕.
Chẩn đoán: đợt cấp 〔DX|suy tim〕 trên nền 〔DX|rung nhĩ〕.
Điều trị: 〔DRUG|furosemide〕 tiêm tĩnh mạch, 〔DRUG|bisoprolol〕, 〔DRUG|spironolactone〕, 〔DRUG|warfarin〕 theo INR, 〔DRUG|digoxin〕 khi cần kiểm soát tần số.
""",
    ),
    (
        "ba_03_dai_thao_duong_theo_doi",
        """Phiếu tái khám nội tiết

Bệnh nhân nữ 58 tuổi theo dõi 〔DX|đái tháo đường type 2〕 và 〔DX|tăng lipid máu〕.
Triệu chứng gần đây: 〔SYM|khát nước nhiều〕, 〔SYM|tiểu nhiều lần về đêm〕, 〔SYM|mệt mỏi nhiều〕, 〔SYM|sụt cân〕 nhẹ.
〔TEST|HbA1c〕: 〔RES|8.4%〕. 〔TEST|định lượng đường huyết lúc đói〕: 〔RES|9.8 mmol/L〕.
〔TEST|định lượng mỡ máu〕: LDL 〔RES|158 mg/dL〕, triglyceride 〔RES|220 mg/dL〕.
Điều chỉnh thuốc: 〔DRUG|metformin〕 850 mg x 2, thêm 〔DRUG|atorvastatin〕 20 mg tối, tư vấn chế độ ăn và vận động.
Không dị ứng 〔DRUG|aspirin〕; dự phòng biến cố mạch vành bằng 〔DRUG|aspirin〕 81 mg nếu không chống chỉ định.
""",
    ),
    (
        "ba_04_copd_dot_cap",
        """Bệnh án hô hấp

Nam 67 tuổi, hút thuốc lâu năm, vào viện vì 〔SYM|khó thở〕, 〔SYM|ho〕 đờm nhiều, 〔SYM|thở khò khè〕 4 ngày.
Chẩn đoán nền: 〔DX|bệnh phổi tắc nghẽn mãn tính〕.
〔TEST|X-quang ngực〕: 〔RES|rối loạn thông khí tắc nghẽn mức độ vừa〕 nghi trên phim khí phế thũng.
〔TEST|đo chức năng thông khí phổi〕: 〔RES|rối loạn thông khí tắc nghẽn mức độ vừa〕.
〔TEST|khí máu〕: 〔RES|toan hô hấp còn bù một phần〕.
Điều trị đợt cấp: 〔DRUG|salbutamol〕 khí dung, 〔DRUG|budesonide〕, 〔DRUG|prednisone〕 ngắn ngày, 〔DRUG|azithromycin〕 nếu nghi bội nhiễm.
""",
    ),
    (
        "ba_05_hen_phe_quan",
        """Khám ngoại trú dị ứng - miễn dịch lâm sàng

Bệnh nhi nữ 14 tuổi tái khám 〔DX|hen〕. Đợt này có 〔SYM|khó thở〕, 〔SYM|thở khò khè〕 về đêm, 〔SYM|ho khan kéo dài〕.
Không 〔SYM|sốt〕, không 〔SYM|đau họng khi nuốt〕.
〔TEST|đo chức năng thông khí phổi〕: 〔RES|có đáp ứng với thuốc giãn phế quản〕.
〔TEST|spo2〕 〔RES|96%〕.
Thuốc đang dùng: 〔DRUG|salbutamol〕 khi cần, 〔DRUG|montelukast〕 5 mg tối, 〔DRUG|budesonide〕 hít duy trì.
Kèm 〔DRUG|cetirizine〕 nếu dị ứng mũi theo mùa.
""",
    ),
    (
        "ba_06_viem_da_day_gerd",
        """Bệnh án tiêu hóa

Nam 45 tuổi đau vùng thượng vị sau ăn, 〔SYM|ợ chua〕, 〔SYM|đầy hơi chướng bụng〕 2 tuần.
Tiền sử 〔DX|viêm dạ dày〕, nghi 〔DX|bệnh trào ngược dạ dày - thực quản〕.
〔TEST|nội soi dạ dày tá tràng〕: 〔RES|hình ảnh dày thành dạ dày vùng hang vị〕, không loét sâu.
〔TEST|xét nghiệm〕 H. pylori: 〔RES|dương tính〕.
Chẩn đoán: 〔DX|viêm dạ dày〕 / 〔DX|bệnh trào ngược dạ dày - thực quản〕.
Điều trị: 〔DRUG|omeprazole〕 20 mg x 2, 〔DRUG|domperidone〕 trước ăn, diệt H. pylori theo phác đồ có 〔DRUG|amoxicillin〕 và 〔DRUG|clarithromycin〕 nếu dung nạp.
""".replace("〔DRUG|clarithromycin〕", "〔DRUG|azithromycin〕"),
    ),
    (
        "ba_07_loet_da_day",
        """Ghi chú lâm sàng tiêu hóa

Nữ 52 tuổi 〔SYM|đau vùng thượng vị sau ăn〕, 〔SYM|buồn nôn〕, có lần 〔SYM|chảy máu〕 tiêu hóa đen phân.
〔TEST|nội soi dạ dày tá tràng〕: 〔RES|loét hang vị Forrest IIc〕.
Chẩn đoán: 〔DX|loét dạ dày〕.
Điều trị: 〔DRUG|pantoprazole〕 tiêm rồi chuyển uống, 〔DRUG|sucralfate〕 hỗ trợ nếu có; tránh 〔DRUG|ibuprofen〕 và NSAID.
Theo dõi 〔TEST|công thức máu toàn phần〕: HGB 〔RES|92 g/L〕.
""".replace("〔DRUG|sucralfate〕 hỗ trợ nếu có; ", ""),
    ),
    (
        "ba_08_dot_quy_nao",
        """Hồi sức thần kinh

Nam 70 tuổi đột ngột 〔SYM|yếu nửa người bên phải〕, 〔SYM|nói khó〕, 〔SYM|lú lẫn〕 2 giờ trước nhập viện.
Tiền sử 〔DX|tăng huyết áp〕, 〔DX|đái tháo đường〕, 〔DX|rung nhĩ〕 không đều trị.
〔TEST|chụp cắt lớp vi tính sọ não〕: 〔RES|không thấy xuất huyết nội sọ〕, nghi 〔DX|nhồi máu não〕 giai đoạn sớm.
〔TEST|điện tâm đồ〕: 〔RES|rung nhĩ〕.
〔TEST|đường huyết〕 〔RES|7.1 mmol/L〕.
Điều trị cấp: kiểm soát huyết áp, 〔DRUG|aspirin〕 nếu không tiêu sợi huyết, 〔DRUG|atorvastatin〕 liều cao, cân nhắc kháng đông 〔DRUG|warfarin〕 sau ổn định, 〔DRUG|amlodipine〕 duy trì.
""",
    ),
    (
        "ba_09_dong_kinh",
        """Bệnh án thần kinh

Nữ 28 tuổi vào viện sau cơn 〔SYM|co giật toàn thể〕 tại nhà, kèm 〔SYM|cắn lưỡi〕 và 〔SYM|mất ý thức〕 ngắn.
Chẩn đoán cũ: 〔DX|động kinh〕.
〔TEST|điện não đồ〕: 〔RES|hoạt động sóng đỉnh khu trú thái dương〕.
〔TEST|chụp MRI〕 sọ: 〔RES|không thấy khối choán chỗ nội sọ〕.
Thuốc: 〔DRUG|gabapentin〕 điều chỉnh liều; tránh bỏ thuốc đột ngột. Không dùng 〔DRUG|tramadol〕 vì có thể hạ ngưỡng co giật.
""".replace("〔SYM|cắn lưỡi〕 và 〔SYM|mất ý thức〕", "〔SYM|lú lẫn〕 sau cơn và"),
    ),
    (
        "ba_10_tram_cam",
        """Khám tâm thần ngoại trú

Nam 41 tuổi than 〔SYM|mất ngủ kéo dài〕, 〔SYM|chán ăn〕, 〔SYM|mệt mỏi nhiều〕, giảm thích thú công việc 2 tháng.
Chẩn đoán: 〔DX|giai đoạn trầm cảm〕 mức độ vừa.
Không 〔SYM|ý tưởng tự sát〕 hiện tại.
〔TEST|TSH〕 〔RES|trong giới hạn bình thường〕 để loại trừ 〔DX|suy giáp〕.
Điều trị: 〔DRUG|sertraline〕 50 mg sáng, tư vấn tâm lý, tái khám sau 2 tuần.
""",
    ),
    (
        "ba_11_suy_than_man",
        """Bệnh án thận học

Nữ 63 tuổi theo dõi 〔DX|suy thận mãn tính〕 trên nền 〔DX|đái tháo đường type 2〕 và 〔DX|tăng huyết áp〕.
Triệu chứng: 〔SYM|phù〕 mắt cá, 〔SYM|mệt〕, 〔SYM|ngứa〕.
〔TEST|xét nghiệm chức năng thận〕: creatinine 〔RES|2.8 mg/dL〕, eGFR giảm.
〔TEST|xét nghiệm máu〕: Hb 〔RES|9.3 g/dL〕.
Thuốc: 〔DRUG|losartan〕, 〔DRUG|furosemide〕, 〔DRUG|metformin〕 tạm ngưng khi eGFR thấp, bổ sung sắt; tránh 〔DRUG|ibuprofen〕.
""",
    ),
    (
        "ba_12_nhiem_khuan_tiet_nieu",
        """Cấp cứu tiết niệu

Nữ 35 tuổi 〔SYM|tiểu buốt tiểu rắt〕, 〔SYM|đau bụng〕 hạ vị, 〔SYM|sốt nhẹ về chiều〕 2 ngày.
〔TEST|phân tích nước tiểu〕: 〔RES|bạch cầu niệu dương tính〕, nitrite 〔RES|dương tính〕.
〔TEST|cấy nước tiểu định danh vi khuẩn〕 đang chờ.
Chẩn đoán: 〔DX|nhiễm khuẩn hệ tiết niệu〕.
Điều trị: 〔DRUG|ciprofloxacin〕 500 mg x 2 (sau chỉnh theo kháng sinh đồ), 〔DRUG|paracetamol〕 hạ sốt, uống nhiều nước.
""",
    ),
    (
        "ba_13_soi_than",
        """Ngoại tiết niệu

Nam 40 tuổi 〔SYM|đau lưng lan xuống chân〕 bên phải dữ dội, 〔SYM|buồn nôn〕, tiểu máu vi thể.
〔TEST|chụp cắt lớp vi tính〕 bụng: 〔RES|sỏi niệu quản phải 6 mm kèm ứ nước độ I〕.
Chẩn đoán: 〔DX|sỏi thận〕 / sỏi niệu quản.
Điều trị giảm đau 〔DRUG|tramadol〕 thận trọng, 〔DRUG|ibuprofen〕 ngắn ngày nếu chức năng thận ổn, tăng dịch, cân nhắc tán sỏi nếu không xuống.
""",
    ),
    (
        "ba_14_soi_mat",
        """Ngoại tiêu hóa

Nữ 48 tuổi 〔SYM|đau bụng vùng hạ sườn phải〕 sau ăn dầu mỡ, 〔SYM|buồn nôn và nôn〕.
〔TEST|siêu âm ổ bụng〕: 〔RES|sỏi túi mật nhiều viên, thành túi mật dày〕.
〔TEST|xét nghiệm chức năng gan〕: AST 〔RES|56 U/L〕, ALT 〔RES|62 U/L〕.
Chẩn đoán: 〔DX|sỏi mật〕.
Điều trị triệu chứng 〔DRUG|omeprazole〕, 〔DRUG|domperidone〕; dự kiến phẫu thuật cắt túi mật nội soi khi hết đợt cấp.
""",
    ),
    (
        "ba_15_gout_cap",
        """Khám cơ xương khớp

Nam 55 tuổi 〔SYM|sưng đau khớp〕 ngón chân cái phải cấp, 〔SYM|đỏ〕 nóng.
Chẩn đoán đợt cấp 〔DX|gút〕; tiền sử 〔DX|tăng lipid máu〕.
〔TEST|acid uric〕 máu: 〔RES|9.1 mg/dL〕.
〔TEST|công thức máu toàn phần〕: 〔RES|bình thường〕.
Điều trị đợt cấp: 〔DRUG|colchicine〕, 〔DRUG|prednisone〕 ngắn nếu không dùng được NSAID; duy trì sau đó 〔DRUG|allopurinol〕 khi hết viêm. Tránh 〔DRUG|aspirin〕 liều thấp ảnh hưởng uric.
""",
    ),
    (
        "ba_16_thoai_hoa_khop_goi",
        """Phục hồi chức năng

Nữ 68 tuổi 〔SYM|đau khớp〕 gối phải khi đi bộ, 〔SYM|cứng khớp buổi sáng〕 < 30 phút.
〔TEST|chụp x-quang khớp gối hai bên〕: 〔RES|hep khe khớp, gai xương〕.
Chẩn đoán: 〔DX|thoái hóa khớp gối〕.
Điều trị: 〔DRUG|paracetamol〕, 〔DRUG|ibuprofen〕 ngắn ngày khi đau nhiều, vật lý trị liệu; không tiêm corticoid thường xuyên.
""",
    ),
    (
        "ba_17_viem_khop_dang_thap",
        """Bệnh án khớp

Nữ 42 tuổi 〔SYM|sưng đau khớp bàn tay〕 đối xứng, 〔SYM|cứng khớp buổi sáng〕 kéo dài, 〔SYM|mệt mỏi nhiều〕.
〔TEST|ESR〕 〔RES|tăng cao〕, RF 〔RES|dương tính〕.
Chẩn đoán: 〔DX|viêm khớp dạng thấp〕.
Điều trị khởi đầu: 〔DRUG|prednisone〕 liều thấp ngắn, 〔DRUG|methotrexate〕 nếu được chuyên khoa chỉ định; giảm đau 〔DRUG|paracetamol〕.
""".replace("〔DRUG|methotrexate〕 nếu được chuyên khoa chỉ định; ", "theo dõi chuyên khoa khớp; "),
    ),
    (
        "ba_18_suy_giap_loang_xuong",
        """Nội tiết - loãng xương

Nữ 61 tuổi 〔SYM|mệt〕, 〔SYM|tăng cân〕, 〔SYM|lạnh〕 chân tay. Chẩn đoán 〔DX|suy giáp〕.
〔TEST|TSH〕 〔RES|12.4 mIU/L〕, FT4 giảm nhẹ.
Đồng thời 〔TEST|đo mật độ xương〕: 〔RES|giảm mật độ xương mức loãng xương〕 -> 〔DX|loãng xương〕.
Điều trị: 〔DRUG|levothyroxine〕 chỉnh liều theo TSH; 〔DRUG|alendronate〕 tuần một lần, bổ sung vitamin D/calci.
""",
    ),
    (
        "ba_19_viem_gan_b_man",
        """Bệnh án truyền nhiễm / gan mật

Nam 39 tuổi 〔SYM|mệt mỏi nhiều〕, 〔SYM|chán ăn〕, thỉnh thoảng 〔SYM|đau bụng vùng hạ sườn phải〕.
〔TEST|HBsAg〕 〔RES|dương tính〕, HBV DNA tăng.
〔TEST|xét nghiệm chức năng gan〕: ALT 〔RES|110 U/L〕.
Chẩn đoán: 〔DX|viêm gan virus B mạn〕.
Tư vấn theo dõi và điều trị chuyên khoa; tránh rượu, thận trọng thuốc độc gan như 〔DRUG|paracetamol〕 quá liều. Không tự ý dùng 〔DRUG|prednisone〕.
""",
    ),
    (
        "ba_20_mach_vanh_ngoai_tru",
        """Tái khám tim mạch

Nam 60 tuổi tiền sử 〔DX|tăng huyết áp〕, 〔DX|đái tháo đường type 2〕, 〔DX|tăng lipid máu〕, đau ngực khi gắng sức.
Triệu chứng: 〔SYM|đau ngực khi gắng sức〕, 〔SYM|khó thở khi gắng sức nhẹ〕.
〔TEST|điện tâm đồ〕: 〔RES|điện tâm đồ có sóng T âm ở các chuyển đạo trước tim〕.
〔TEST|troponin〕 〔RES|âm tính〕.
〔TEST|HbA1c〕 〔RES|7.2%〕, LDL 〔RES|110 mg/dL〕.
Điều trị dự phòng thứ phát: 〔DRUG|aspirin〕, 〔DRUG|clopidogrel〕 (nếu stent), 〔DRUG|atorvastatin〕 hoặc 〔DRUG|rosuvastatin〕, 〔DRUG|bisoprolol〕, 〔DRUG|perindopril〕, 〔DRUG|metformin〕.
""",
    ),
]


def attach_codes(records: list[dict]) -> None:
    for rec in records:
        text = rec["text"].strip()
        key = text.lower()
        if rec["type"] == "CHẨN_ĐOÁN":
            for surface, codes in DX_CODES.items():
                if key == surface.lower() or surface.lower() in key:
                    rec["candidates"] = codes
                    break
        elif rec["type"] == "THUỐC":
            for surface, codes in DRUG_CODES.items():
                if key == surface.lower():
                    rec["candidates"] = codes
                    break


def main() -> int:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    ANN_DIR.mkdir(parents=True, exist_ok=True)

    pairs = []
    for stem, marked in MARKED_RECORDS:
        result = unwrap_typed(marked)
        if isinstance(result, str):
            sys.exit(f"{stem}: {result}")
        text, records = result
        attach_codes(records)
        (TEXT_DIR / f"{stem}.txt").write_text(text, encoding="utf-8")
        (ANN_DIR / f"{stem}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pairs.append((stem, text, records))
        print(f"  {stem}: {len(records)} spans, {len(text)} chars")

    import collections

    report = collections.Counter()
    segment_line = make_segmenter()
    blocks = []
    types = collections.Counter()
    for stem, raw, anns in pairs:
        words = segment_document(raw, segment_line)
        spans = usable_spans(raw, anns, report)
        labels = label_words(words, spans, report)
        blocks += blocks_of(words, labels, 80)
        for ann in spans:
            types[ann["type"]] += 1

    write_bio(blocks, BIO_OUT)
    tokens = sum(len(b) for b in blocks)
    tagged = sum(1 for b in blocks for _, lab in b if lab != "O")
    print(f"\n  wrote {BIO_OUT.relative_to(REPO)}")
    print(f"  {len(pairs)} records -> {len(blocks)} blocks, {tokens} tokens, "
          f"{tagged} tagged ({tagged / tokens:.1%})")
    print("  spans by type:")
    for name, count in types.most_common():
        print(f"    {name:22} {count}")
    if report:
        print("  notes:")
        for key, val in sorted(report.items()):
            if key not in ("file", "từ"):
                print(f"    {key}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
