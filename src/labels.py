"""Shared NER label definitions for training and inference."""

LABELS = [
    "O",
    "B-THUOC", "I-THUOC",
    "B-TRIEU_CHUNG", "I-TRIEU_CHUNG",
    "B-BENH", "I-BENH",
    "B-XET_NGHIEM", "I-XET_NGHIEM",
    "B-BENH_NHAN", "I-BENH_NHAN",
    "B-TAC_NHAN_NGOAI_SINH", "I-TAC_NHAN_NGOAI_SINH"
]

LABEL2ID = {label: i for i, label in enumerate(LABELS)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}

# Display / API type names for B- labels
ENTITY_TYPE_MAP = {
    "B-THUOC": "THUỐC",
    "B-TRIEU_CHUNG": "TRIỆU_CHỨNG",
    "B-BENH": "BENH",
    "B-XET_NGHIEM": "XET_NGHIEM",
    "B-BENH_NHAN": "BENH_NHAN",
    "B-TAC_NHAN_NGOAI_SINH": "TAC_NHAN_NGOAI_SINH",
}
