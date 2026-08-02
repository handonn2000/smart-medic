"""Nguồn CÁCH NÓI bề mặt, tách theo mức độ tin cậy của nguồn.

    lab.py     TẤT ĐỊNH   danh mục panel + từ vựng kết quả (Phase 1)
    drug.py    TẤT ĐỊNH   ATC/DDD của Bộ Y tế + mask *** + biệt dược không mã
    frozen.py  LLM        CHỈ CHẨN_ĐOÁN + TRIỆU_CHỨNG, sinh MỘT lần rồi đóng băng

Tỉ lệ đầu tư theo trần đã đo (§0.2), không theo trực giác:
    XÉT NGHIỆM  +0,154   ← `lab.py` là nguồn chính
    TRIỆU_CHỨNG +0,134   ← `frozen.py`
    CHẨN_ĐOÁN   +0,096   ← `frozen.py`
    THUỐC       +0,057   ← `drug.py`, chỉ 10% tài liệu
"""
