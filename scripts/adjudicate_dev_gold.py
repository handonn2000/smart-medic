#!/usr/bin/env python3
"""Phân xử 314 xung đột trong ``data/dev_adjudication.json`` → gold dev chốt.

Vì sao script này tồn tại thay vì sửa tay 20 file JSON: quyết định phải **truy
vết được**. Mỗi mục trong ``DECISIONS`` ghi rõ chọn gì và VÌ SAO, nên khi số đo
đổi ta biết đổi vì lý do nào; sửa tay thì mất hết dấu vết đó.

Đầu vào
    data/dev_gold_consensus/  689 mention hai model đã đồng thuận (không đụng)
    data/dev_adjudication.json  314 mục xung đột
    data/test/{n}.txt         văn bản gốc — nguồn duy nhất để tính lại offset

Đầu ra
    data/dev_gold/            gold chốt, đã validate schema + verify position

LUẬT CỨNG giữ nguyên từ ``preannotate_dev.py``: **không tự chế offset**. Khi một
quyết định đổi chuỗi span (chọn ranh giới của model kia), vị trí được dò lại
trên ``TextRef`` rồi kiểm bằng ``Span.verify``; không verify được thì báo lỗi và
KHÔNG ghi file — gold sai còn tệ hơn không có gold.

Dùng:
    PYTHONPATH=src python3 scripts/adjudicate_dev_gold.py --out data/dev_gold
    PYTHONPATH=src python3 scripts/adjudicate_dev_gold.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.schema import Span, validate_file  # noqa: E402
from smart_medic.textref import read_textref  # noqa: E402

# ── quyết định ────────────────────────────────────────────────────────────────
#
# Khóa = chỉ số mục trong data/dev_adjudication.json.
# Giá trị:
#   "O" / "S"                    theo nguyên bản model đó
#   "X"                          bỏ span khỏi gold
#   dict(...)                    ghi đè: span/type/assertions/candidates
#     span:        "O" | "S" (mặc định "O") — chọn chuỗi của model nào
#     type/assertions/candidates: ghi đè giá trị tương ứng
#
# Bốn quy ước xuyên suốt, mỗi cái đều tựa vào bằng chứng đo được, không phải
# khẩu vị (chi tiết trong docs/reports/2026-07-27-dev-gold-adjudication-ket-qua.md):
#
#   A. MÃ ICD — chuộng con ".9" hơn mã cha 3 ký tự. v4.2 đo trên tập consensus
#      RỜI với tập này: 22/37 lỗi gazetteer là do trả mã cha trong khi gold trả
#      con ".9"; đề bài cũng dùng mã con (K21.0/K21.9).
#   B. MÃ RxNorm THEO MỨC BẰNG CHỨNG (v4.1). Có hàm lượng + đường dùng → SCD
#      (ví dụ chính thức: "amlodipine 10 mg po daily" → 308135 = SCD). Tên trơ
#      → RXCUI của anchor: IN cho hoạt chất, **BN cho biệt dược**.
#   C. RANH GIỚI SPAN = cụm khái niệm tối thiểu. Bỏ bổ ngữ mức độ/thời lượng/vị
#      trí/người chứng kiến và danh từ dẫn ("tình trạng", "kết quả", "cảm giác").
#      GIỮ phần trong ngoặc khi nó GỌI TÊN khái niệm (biệt dược ↔ hoạt chất);
#      BỎ khi chỉ là viết tắt ("(AH)", "(RLL PNA)").
#   D. NHẤT QUÁN TRONG FILE thắng sở thích cá nhân: nếu consensus đã gán mã/
#      assertion cho cùng một chuỗi ở chỗ khác trong file, mục xung đột theo đó.

DECISIONS: dict[int, Any] = {
    # ── lệch mã (84) ──────────────────────────────────────────────────────────
    # f1 · thiếu máu tan huyết trong bệnh cảnh thiếu men G6PD. D59.9 là tan máu
    # MẮC PHẢI — sai hẳn cơ chế: G6PD là bệnh men di truyền. Mã đúng D55.0,
    # trùng mã consensus đã gán cho "Thiếu men G6PD" trong chính file này.
    0: {"candidates": ["D55.0"]},
    1: {"candidates": ["D55.0"]},
    2: {"candidates": ["D55.0"]},
    # f1 · RXCUI 8163 = phenylephrine, KHÔNG phải vitamin K. Tra KB: "vitamin K"
    # là chuỗi duy nhất của RXCUI 11258 (IN).
    3: {"candidates": ["11258"]},
    4: "S",   # nhiễm trùng răng miệng → K12.2 (viêm mô tế bào/áp xe miệng)
    5: "S",
    6: "O",   # vô sinh nữ (2 năm chưa có thai, buồng trứng đa nang) → N97.9
    7: "O",
    # f6 · "Đái tháo đường" không nêu type. Cả hai model đều nghiêng họ E11 ở
    # f26; theo quy ước A lấy con ".9".
    8: {"candidates": ["E11.9"]},
    # f6 · bệnh nhân NGÃ, CT có bầm dập nhu mô + tụ dịch dưới màng cứng ⇒ xuất
    # huyết dưới nhện do CHẤN THƯƠNG. I60.9 là loại tự phát — sai cơ chế.
    9: "S",
    10: "O",  # ổ loét dạ dày → K25.9 (quy ước A)
    11: "O",  # nhôm hydroxid → 612 (727 đã hết hiệu lực từ 2005)
    12: "O",  # magie hydroxid → 6581
    13: "O",  # Simethicon 100mg — có hàm lượng, KHÔNG có dạng bào chế → IN 9796
    14: "O",  # metoclopramide 10mg — như trên → IN 6915
    15: "O",
    16: "O",
    # f8 · seroquel là BIỆT DƯỢC. 51272 là quetiapine (hoạt chất); chuỗi
    # "Seroquel" thuộc duy nhất BN 83553.
    17: {"candidates": ["83553"]},
    18: "O",  # sốt siêu vi → B34.9
    19: "O",  # hẹp/tắc động mạch vành → I25.1
    # f10 · "metoprolol 25mg po bid" trùng khuôn ví dụ chính thức của đề bài
    # ("amlodipine 10 mg po daily" → 308135 = SCD) ⇒ dùng SCD, không phải IN.
    20: {"candidates": ["866924"]},
    21: "S",  # doxycycline trơ → IN 3640
    22: "S",  # atenolol trơ → IN 1202
    23: {"candidates": ["866924"]},
    24: {"candidates": ["212033"]},   # aspirin 325mg → SCD aspirin 325 MG Oral Tablet
    25: "O",  # hội chứng kháng synthetase → M35.8
    26: "O",  # thủy đậu/Zona → hai mã B01.9 + B02.9 (đề bài cho phép 2 mã)
    # f14/f54 · gleevec là biệt dược; 282388 là imatinib (hoạt chất).
    27: {"candidates": ["282386"]},
    28: {"candidates": ["282386"]},
    **{i: "O" for i in range(29, 43)},   # bệnh dại → A82.9 (quy ước A) ×14
    43: "O",  # bumetanide 2mg iv — không SCD nào khớp 2mg ⇒ anchor IN 1808
    44: "O",  # viêm quanh răng → K05.3, khớp mã consensus gán "Viêm nha chu" ×3
    45: {"candidates": ["K05.3"]},   # "nhiễm trùng lợi nặng" chú giải cho viêm nha chu
    46: {"candidates": ["E11.9"]},
    47: {"candidates": ["E11.9"]},
    **{i: "S" for i in (48, 49, 50, 51, 52, 53, 57, 58)},   # amyloidosis → E85.9
    54: "O",  # amyloidosis chuỗi nhẹ = thể xác định → E85.8, không phải ".9"
    # f21 · "amyloidosis tự miễn dịch" là cách gọi thể AA (phản ứng/thứ phát)
    # trong bộ ba AL–AA–di truyền ⇒ E85.3, không phải "không đặc hiệu".
    55: {"candidates": ["E85.3"]},
    56: "O",  # di truyền/gia đình, không nói có bệnh lý thần kinh → E85.2
    59: "O",  # teo niêm mạc tử cung → N85.8
    60: "O",  # vô sinh → N97.9 (quy ước A)
    61: "O",  # chửa ngoài tử cung → O00.9 (quy ước A)
    62: "O",  # đột tử trong bệnh cảnh mạch vành → I46.1
    # f26 · "huyết khối" ở đây là một MẮT XÍCH cơ chế (nứt mảng xơ vữa → huyết
    # khối → tắc mạch), lại là mạch vành; I74 loại trừ mạch vành ⇒ để trống.
    63: "O",
    64: "S",  # E11.9
    65: "O",  # đau thắt ngực ổn định → I20.8 "dạng khác"; file đã dùng I20.0
    66: "S",
    67: "S",  # rung nhĩ → I48.9 (quy ước A)
    68: {"candidates": ["1364436"]},   # eliquis là biệt dược → BN
    69: "S",
    70: "O",  # viêm phổi hoại tử → J85.0
    71: "O",  # VP = viêm phổi → J18.9, khớp mã consensus gán "viêm phổi" ×3
    72: "O",
    # f27 · "Viêm phổi là tình trạng viêm phế quản, phế nang" — câu định nghĩa,
    # không nói cấp hay mạn ⇒ J40; J20.9 khẳng định "cấp" mà văn bản không nói.
    73: "S",
    74: "O",  # suy giảm miễn dịch → D84.9
    75: "O",
    76: "O",
    77: "O",  # áp-xe nhỏ → J85.2
    78: "O",  # vô sinh thứ phát ở nam (giãn thừng tinh) → N46
    79: "O",  # tylenol → BN 202433
    80: "O",
    81: {"candidates": ["282386"]},
    82: {"candidates": ["282386"]},
    83: "O",  # dị tật bẩm sinh → Q89.9

    # ── lệch nhãn type (20) ───────────────────────────────────────────────────
    # Luật: CHẨN_ĐOÁN đòi một TÊN BỆNH. Cụm mô tả một trạng thái cơ thể mà
    # không phải tên bệnh thì là TRIỆU_CHỨNG.
    84: "S",   # "tổn thương thần kinh" — mô tả, không phải tên bệnh
    85: "O",   # béo phì là bệnh (E66.9)
    # f6 · "co giật" thuộc chương R. Đo được: 0/40 span chương R được gold gọi
    # là mappable ⇒ theo tiên nghiệm đó, để TRIỆU_CHỨNG, không gán mã.
    86: "O",
    # f6 · #87–#92 là các tổn thương CÓ TÊN trên phim CT (xuất huyết dưới nhện
    # chấn thương, bầm dập nhu mô, tụ máu ngoài màng cứng). Hai lý do chọn
    # CHẨN_ĐOÁN: (1) chính chuỗi "xuất huyết dưới nhện" đã được HAI model thống
    # nhất gọi CHẨN_ĐOÁN ở lần nhắc đầu — gọi khác ở lần sau thì gold tự mâu
    # thuẫn; (2) consensus chỉ dùng KẾT_QUẢ_XÉT_NGHIỆM cho giá trị/kết luận
    # dạng số hoặc chung chung ("14.99 G/L", "ổn định"), không cho tổn thương
    # có tên.
    **{i: "S" for i in range(87, 93)},
    93: "S",   # "Tăng men gan" — chương R, để TRIỆU_CHỨNG không mã
    94: "O",   # rối loạn tiêu hóa, liệt kê như một biến chứng → CHẨN_ĐOÁN
    95: "O",   # mề đay là bệnh da (L50)
    96: "O",
    97: "S",   # "suy yếu hệ miễn dịch" — mô tả trạng thái, không phải tên bệnh
    98: "S",   # "không rụng trứng" — hiện tượng sinh lý; N97.0 là mã VÔ SINH
    99: "O",   # mụn trứng cá L70.0
    100: "O",  # nám L81.1
    101: "O",  # tàn nhang L81.2
    102: "S",  # "tổn thương màng phổi" — mô tả, không phải tên bệnh
    103: "O",  # tăng nhãn áp (glaucoma) là bệnh → H40.9

    # ── lệch ranh giới (92) ───────────────────────────────────────────────────
    104: "O",  # "Vastarel (trimetazidin)" — ngoặc gọi tên hoạt chất → giữ
    105: "O",  # bỏ bổ ngữ mức độ "nặng"
    106: "O",
    107: "O",
    108: "O",  # bỏ mô tả kích thước/điểm sắc tố
    109: {"assertions": ["isHistorical"], "candidates": ["K26.9"]},
    110: {"assertions": ["isHistorical"]},   # nội soi trong tiền sử; khớp consensus
    111: {"assertions": ["isHistorical"]},
    112: "S",  # THUỐC giữ hàm lượng liền kề (quy ước C + hướng dẫn prompt)
    113: {"assertions": ["isHistorical"]},
    114: {"assertions": ["isHistorical"]},   # span sonnet lặp chữ "Loét loét"
    115: {"assertions": ["isHistorical"]},   # span sonnet lặp chữ "loét ... loét"
    116: "O",  # khái niệm là "ung thư biểu mô tuyến", phần đầu là dẫn dắt
    117: "O",
    118: "O",
    119: "O",
    120: "O",
    121: "O",  # bỏ mệnh đề dẫn "một lớp dịch ... nghĩ nhiều đến"
    122: "O",
    123: "O",
    124: "S",  # bỏ danh từ dẫn "Tình trạng"
    125: "O",
    126: "O",  # bỏ danh từ dẫn "kết quả"
    127: "O",
    128: "O",
    129: "O",
    130: "O",
    # f8 · giữ span ngắn "Rối loạn cảm xúc" để "(trầm cảm)" đứng riêng được
    # (#238); span dài của sonnet sẽ NUỐT mention đó — nhãn BIO không biểu diễn
    # được span lồng nhau.
    131: "O",
    132: "O",
    133: "O",  # bỏ "cảm giác"
    134: "O",  # span sonnet gộp hai triệu chứng làm một
    135: "O",  # "(AH)" chỉ là viết tắt → bỏ
    136: "O",
    137: "S",  # bỏ lượng từ "các"
    138: "O",  # "tự tử chủ động" là khái niệm đầy đủ hơn
    139: "S",
    140: "S",  # "bệnh Kawasaki" — giữ "bệnh" như một phần tên bệnh
    141: "S",
    142: "O",  # bỏ thời lượng "≥5 ngày"
    143: "O",
    144: "O",
    145: "O",
    146: "O",  # span sonnet lặp "Khó thở nhẹ khó thở"
    147: "O",
    148: "O",
    149: "O",
    150: "O",
    151: "O",  # span sonnet gộp hai dị tật; mention còn lại đứng riêng ở #254
    152: "O",
    153: "O",
    154: "O",  # TÊN_XÉT_NGHIỆM là "mô bệnh học", không phải "Tổn thương ..."
    155: "O",  # bỏ danh từ dẫn "tình trạng"
    156: "S",  # tên phương pháp tối thiểu
    157: "O",
    158: "O",
    159: "O",
    160: "O",  # bỏ mệnh đề giảm liều
    161: "O",  # "viêm và sưng" là hai triệu chứng
    162: "O",  # span sonnet dính chữ "dương vậtbiệt hóa kém"
    163: {"span": "S", "candidates": ["E85.9"]},
    164: "O",  # "thuốc" là danh từ chung, không thuộc tên
    165: "O",
    166: "O",
    167: "S",  # "đối với tình dục" đổi hẳn nghĩa của "suy giảm hưng phấn"
    168: "O",
    169: "O",
    170: "O",
    171: "O",
    172: "O",
    173: "O",
    174: "O",
    175: "O",  # giá trị 38.3°C tách thành mention riêng (#278)
    176: "O",
    177: "O",
    178: "O",
    179: "O",
    180: "O",
    181: "O",
    182: "O",
    183: "S",  # span opus dính chữ rác "tụi mật"; khớp consensus của chính file
    184: "O",
    185: "O",
    186: "S",  # bỏ "cảm giác"
    187: "O",  # "(RLL PNA)" chỉ là viết tắt
    188: "O",  # span sonnet nuốt cả cụm trước đó
    189: "O",
    190: "O",
    191: "O",
    192: "O",
    193: "O",  # bỏ "được vợ nhận thấy"
    194: "O",
    195: "O",

    # ── lệch assertion (22) ───────────────────────────────────────────────────
    196: "O",  # "nghi ngờ thiếu men G6PD" là NGHI NGỜ, không phải phủ định
    # f4 · theo đúng quy ước consensus của chính file: buồn nôn/tiêu chảy gắn
    # với các đợt bệnh trước → isHistorical (6/6 lần consensus đồng thuận);
    # nôn ra máu là lý do nhập viện, đang diễn ra → [] (7/7 lần).
    197: "S", 198: "S", 199: "S", 200: "O",
    201: "S", 202: "S", 203: "S", 204: "O",
    205: "S", 206: "S", 207: "S", 208: "O",
    209: "S",  # nằm dưới "Tiền sử phẫu thuật / thủ thuật"
    210: "S",  # "từng quay lại khoa Cấp cứu vì đau đầu kéo dài"
    211: "O",  # chỉ định của thuốc trước nhập viện; thuốc đó cũng isHistorical
    212: "O",  # consensus gán [] cho chính token bị che này ở câu ngay trước
    # f26 · consensus không bao giờ ghép isFamily với isHistorical (8/8 lần
    # isFamily đứng một mình).
    213: "S",
    214: "O",  # nằm trong khối "Bệnh lý mãn tính" của mục tiền sử
    215: "O",  # omeprazole được BẮT ĐẦU điều trị, khác NSAIDs "đã ngừng"
    216: "O",  # "lần cuối sốt là vào ngày"; consensus gán tiêu chảy kề bên isHistorical
    217: "O",  # "trước đó khoảng 2 tuần e có uống"

    # ── chỉ một model bắt được (96) ───────────────────────────────────────────
    # Bỏ khi: (a) không thuộc 5 type — thủ thuật ĐIỀU TRỊ không phải "thủ thuật
    # chẩn đoán", thực phẩm không phải thuốc, hành vi không phải tên bệnh;
    # (b) chồng lấn một mention đã chọn.
    218: "O",  # lấy máu khô ở gót chân — thủ thuật lấy mẫu xét nghiệm
    219: "O",
    220: "O",
    221: "X",  # phẫu thuật cắt ống mật chủ — điều trị, không phải chẩn đoán
    222: "X",  # cắt thùy gan — điều trị
    223: "X",  # nối mật tụy — điều trị
    224: "O",
    225: "X",  # đặt stent — điều trị
    226: "X",
    227: "O",
    228: "X",
    229: "O",  # văn bản gốc lặp "tế bào bất thườngtế bào bất thường" → 2 mention
    230: "O",
    231: "X",
    232: "O",
    233: "O",
    234: "O",  # ghi điện tim — thăm dò chẩn đoán
    235: "O",
    236: "O",
    237: "O",
    238: "O",  # "(trầm cảm)" đứng riêng vì #131 giữ span ngắn
    239: "O",
    240: "O",
    241: "O",
    242: "O",  # chọc dò dịch não tủy — thủ thuật chẩn đoán
    243: "O",
    244: "X",  # "Biến chứng tim mạch" là tiêu đề nhóm, không phải một chẩn đoán
    245: "O",
    246: "O",
    247: "O",
    248: "O",
    249: "O",
    250: {"candidates": ["1202"]},   # atenolol — cùng mã với #22 trong cùng file
    251: "O",
    252: "O",
    253: "O",
    254: "O",
    255: "O",
    256: "O",
    257: "X",  # "Vệ sinh răng miệng kém" là hành vi, không phải tên bệnh
    258: {"candidates": ["A49.9"]},   # cùng mã với "nhiễm vi khuẩn" ở f27 (#176)
    259: "O",
    260: "O",
    261: "O",
    # f17 · "nồng độ đường trong máu cao" thuộc chương R; theo tiên nghiệm
    # chương R (0/40) thì đây là TRIỆU_CHỨNG không mã, không phải CHẨN_ĐOÁN.
    262: {"type": "TRIỆU_CHỨNG", "candidates": []},
    263: "X",  # hút thuốc lá là hành vi; Z72.0 là "yếu tố ảnh hưởng sức khỏe"
    264: "O",
    265: "X",  # cắt bao quy đầu — điều trị
    266: "X",  # trà gừng — thực phẩm
    267: "X",  # mật ong — thực phẩm
    268: "X",  # trà đinh hương — thực phẩm
    269: "X",  # bào láng gốc răng — điều trị
    270: "X",  # ghép mô mềm — điều trị
    271: "O",  # khám răng miệng — thăm khám chẩn đoán
    272: "O",
    273: "O",
    274: "O",
    275: "O",
    276: "X",  # cắt tuyến tiền liệt — điều trị
    277: "X",
    278: "O",
    279: "O",
    280: "O",
    281: "O",
    282: "O",
    283: "O",
    284: "O",
    285: "O",
    286: "O",
    287: "O",
    288: "O",
    # f1 · "trong đó có xét nghiệm thiếu men G6PD": consensus đọc "thiếu men
    # G6PD" là BỆNH (CHẨN_ĐOÁN, D55.0) và bỏ chữ "xét nghiệm". Giữ cách đọc của
    # hai model; span của sonnet sẽ nuốt trọn mention consensus đó.
    289: "X",
    290: "X",  # chồng lấn "thiếu máu do tan huyết" (#0)
    291: "S",
    292: "S",
    293: "S",
    294: "S",
    # f1 · consensus đã có "xét nghiệm sàng lọc" đúng chỗ này; "trước sinh và
    # sau sinh" là bổ ngữ (quy ước C), thêm vào chỉ làm span nuốt mention kia.
    295: "X",
    296: "X",  # chồng lấn "Vastarel (trimetazidin)" (#104)
    297: "S",
    298: "S",
    299: "S",
    300: "S",
    301: "S",
    302: "S",
    303: "S",
    304: "S",
    305: "X",  # chồng lấn "atenolol" (#22); "(uống hôm nay)" là chi tiết thời điểm
    306: "S",
    307: "S",
    308: "X",  # chồng lấn "bệnh tiểu đường" (#47)
    309: "S",
    310: "S",
    311: "S",
    312: "S",
    313: "S",
}


# ── dựng bản ghi ──────────────────────────────────────────────────────────────


def _locate(tref, text: str, near: int) -> Span | None:
    """Dò ``text`` trong văn bản gốc, ưu tiên lần xuất hiện gần ``near`` nhất.

    Chỉ dùng khi một quyết định đổi chuỗi span; mọi số học offset vẫn đi qua
    ``TextRef.to_raw`` và bất biến vẫn là ``Span.verify``.
    """
    needle = norm_text(text)
    if not needle:
        return None
    hay = tref.norm
    hits: list[int] = []
    i = hay.find(needle)
    while i >= 0:
        hits.append(i)
        i = hay.find(needle, i + 1)
    if not hits:
        return None
    # So sánh khoảng cách trên RAW, không trên norm: 20/100 file lưu ở NFD nên
    # hai hệ offset lệch nhau, và ``near`` là offset raw.
    spans = []
    for ns in hits:
        rs, re_ = tref.to_raw(ns, ns + len(needle))
        span = Span(rs, re_, tref.raw[rs:re_])
        if span.verify(tref.raw):
            spans.append(span)
    if not spans:
        return None
    return min(spans, key=lambda s: abs(s.start - near))


def build(adj: list[dict], trefs: dict[int, Any]) -> tuple[dict[int, list[dict]], list[str]]:
    """Áp quyết định lên 314 mục → bản ghi theo file, kèm danh sách vấn đề."""
    out: dict[int, list[dict]] = {}
    problems: list[str] = []

    for idx, item in enumerate(adj):
        decision = DECISIONS.get(idx)
        if decision is None:
            problems.append(f"#{idx}: CHƯA phân xử")
            continue
        if decision == "X":
            continue

        override = decision if isinstance(decision, dict) else {}
        which = override.get("span", decision if isinstance(decision, str) else "O")
        if which not in ("O", "S"):
            which = "O"
        # Mục chỉ một model bắt được: chỉ có một phía có dữ liệu.
        side = item["opus"] if which == "O" else item["sonnet"]
        text = item["opus_text"] if which == "O" else item["sonnet_text"]
        if side is None or text is None:
            side = item["opus"] or item["sonnet"]
            text = item["opus_text"] or item["sonnet_text"]

        fno = item["file"]
        tref = trefs[fno]
        start, end = item["position"]
        if norm_text(tref.raw[start:end]) == norm_text(text):
            span = Span(start, end, tref.raw[start:end])
        else:
            located = _locate(tref, text, start)
            if located is None:
                problems.append(f"#{idx} f{fno}: không định vị được {text!r}")
                continue
            span = located

        record = {
            "text": span.text,
            "type": override.get("type", side["type"]),
            "candidates": list(override.get("candidates", side["candidates"])),
            "assertions": sorted(override.get("assertions", side["assertions"])),
            "position": [span.start, span.end],
        }
        out.setdefault(fno, []).append(record)

    return out, problems


def overlaps(records: list[dict]) -> list[str]:
    """Span chồng lấn — nhãn BIO không biểu diễn được, phải phát hiện sớm."""
    bad = []
    ordered = sorted(records, key=lambda r: (r["position"][0], r["position"][1]))
    for a, b in zip(ordered, ordered[1:]):
        if b["position"][0] < a["position"][1]:
            bad.append(f"{a['text']!r}{a['position']} ⨯ {b['text']!r}{b['position']}")
    return bad


def _all_occurrences(tref, text: str) -> list[Span]:
    needle = norm_text(text)
    out: list[Span] = []
    if not needle:
        return out
    i = tref.norm.find(needle)
    while i >= 0:
        rs, re_ = tref.to_raw(i, i + len(needle))
        span = Span(rs, re_, tref.raw[rs:re_])
        if span.verify(tref.raw):
            out.append(span)
        i = tref.norm.find(needle, i + 1)
    return out


def resolve_overlaps(records: list[dict], tref) -> tuple[list[dict], list[str]]:
    """Gỡ span chồng lấn bằng cách DỜI, không bằng cách bịa.

    Chồng lấn ở đây gần như luôn là lỗi GÁN VỊ TRÍ chứ không phải lỗi nhãn: khi
    annotation liệt kê cả ``buồn nôn`` lẫn ``nôn`` cho câu "buồn nôn, nôn", bộ
    định vị đã ăn ``nôn`` vào trong ``buồn nôn`` thay vì lấy lần đứng riêng ở
    ngay sau. Nên cách sửa đúng là dời mention bị lồng sang một lần xuất hiện
    KHÁC CÓ THẬT của đúng chuỗi đó; không có chỗ nào trống thì BỎ và báo cáo —
    không bao giờ tự chế offset.

    Thứ tự ưu tiên: span DÀI HƠN giữ chỗ trước — span ngắn dùng chung điểm bắt
    đầu chính là cái bị lồng, và nó mới là cái còn lần xuất hiện khác để dời
    tới. Bằng nhau thì mention consensus (hai model đã đồng thuận) thắng.

    Các trường hợp mà luật cơ học này cho kết quả SAI đã được chốt tay trong
    ``DECISIONS`` (xem #289, #295) chứ không vá bằng cách bẻ luật ở đây.
    """
    notes: list[str] = []
    ordered = sorted(
        records,
        key=lambda r: (-(r["position"][1] - r["position"][0]), r.get("_src", 0), r["position"][0]),
    )
    kept: list[dict] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return all(e <= ts or s >= te for ts, te in taken)

    for rec in ordered:
        s, e = rec["position"]
        if free(s, e):
            kept.append(rec)
            taken.append((s, e))
            continue
        moved = None
        for span in sorted(_all_occurrences(tref, rec["text"]),
                           key=lambda sp: abs(sp.start - s)):
            if free(span.start, span.end):
                moved = span
                break
        if moved is None:
            notes.append(f"BỎ (chồng lấn, không còn lần xuất hiện trống): "
                         f"{rec['text']!r}{rec['position']}")
            continue
        notes.append(f"DỜI {rec['text']!r} {rec['position']} → [{moved.start}, {moved.end}]")
        rec = dict(rec, text=moved.text, position=[moved.start, moved.end])
        kept.append(rec)
        taken.append((moved.start, moved.end))

    return kept, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phân xử 314 xung đột → gold dev chốt")
    ap.add_argument("--adjudication", type=Path, default=ROOT / "data/dev_adjudication.json")
    ap.add_argument("--consensus", type=Path, default=ROOT / "data/dev_gold_consensus")
    ap.add_argument("--input", type=Path, default=ROOT / "data/test")
    ap.add_argument("--out", type=Path, default=ROOT / "data/dev_gold")
    ap.add_argument("--dry-run", action="store_true", help="không ghi, chỉ báo cáo")
    args = ap.parse_args(argv)

    adj = json.loads(args.adjudication.read_text(encoding="utf-8"))
    files = sorted({a["file"] for a in adj} | {int(p.stem) for p in args.consensus.glob("*.json")})
    trefs = {n: read_textref(args.input / f"{n}.txt") for n in files}

    resolved, problems = build(adj, trefs)

    n_written = n_mentions = 0
    per_file: list[tuple[int, int, int, int]] = []
    repairs: list[str] = []
    for n in files:
        base = json.loads((args.consensus / f"{n}.json").read_text(encoding="utf-8"))
        added = resolved.get(n, [])
        records = [dict(r, _src=0) for r in base] + [dict(r, _src=1) for r in added]
        records, notes = resolve_overlaps(records, trefs[n])
        repairs.extend(f"f{n}: {x}" for x in notes)
        records = [{k: v for k, v in r.items() if k != "_src"} for r in records]
        records.sort(key=lambda r: (r["position"][0], r["position"][1]))

        for line in overlaps(records):
            problems.append(f"f{n}: CHỒNG LẤN {line}")
        errors = validate_file(records, trefs[n].raw)
        for e in errors:
            problems.append(f"f{n}: schema {e}")

        per_file.append((n, len(base), len(added), len(records)))
        n_mentions += len(records)
        if not args.dry_run and not errors:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"{n}.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            n_written += 1

    print(f"\n  {'file':>5} {'consensus':>10} {'phân xử':>9} {'tổng':>6}")
    print(f"  {'─' * 34}")
    for n, b, a, t in per_file:
        print(f"  {n:>5} {b:>10} {a:>9} {t:>6}")
    print(f"  {'─' * 34}")
    print(f"  {'TỔNG':>5} {sum(x[1] for x in per_file):>10} "
          f"{sum(x[2] for x in per_file):>9} {n_mentions:>6}")

    kept = sum(1 for v in DECISIONS.values() if v != "X")
    print(f"\n  quyết định: {len(DECISIONS)}/314 · giữ {kept} · bỏ {len(DECISIONS) - kept}")

    if repairs:
        print(f"\n  gỡ chồng lấn ({len(repairs)}):")
        for r in repairs:
            print(f"      {r}")

    if problems:
        print(f"\n  ✗ {len(problems)} vấn đề:", file=sys.stderr)
        for p in problems[:40]:
            print(f"      {p}", file=sys.stderr)
        if len(problems) > 40:
            print(f"      … còn {len(problems) - 40}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n  (dry-run — không ghi file)")
    else:
        print(f"\n  ✓ ghi {n_written}/{len(files)} file → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
