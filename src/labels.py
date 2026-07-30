"""Shared NER label definitions for training and inference."""

LABELS = [
    "O",
    "B-THUOC", "I-THUOC",
    "B-TRIEU_CHUNG", "I-TRIEU_CHUNG",
    "B-BENH", "I-BENH",
    "B-XET_NGHIEM", "I-XET_NGHIEM",
    "B-KET_QUA_XET_NGHIEM", "I-KET_QUA_XET_NGHIEM",
    "B-BENH_NHAN", "I-BENH_NHAN",
    "B-TAC_NHAN_NGOAI_SINH", "I-TAC_NHAN_NGOAI_SINH",
    # "B-VITRI", "I-VITRI",
    # "B-TUOI", "I-TUOI",
    # "B-GIOI_TINH", "I-GIOI_TINH"
]

LABEL2ID = {label: i for i, label in enumerate(LABELS)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}

# The only five type names the competition scores. Emitting anything else is worse
# than emitting nothing: an unrecognised type never matches a gold concept, so it
# scores 0 on all three metrics AND leaves the gold concept unmatched, which scores 0
# again — one mislabelled span costs twice what skipping it does.
OUTPUT_TYPES = ("TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM",
                "CHẨN_ĐOÁN", "THUỐC")

# Only these carry assertions / standard codes; the rest must be emitted empty.
ASSERTION_TYPES = ("CHẨN_ĐOÁN", "THUỐC", "TRIỆU_CHỨNG")
CODEABLE_TYPES = ("CHẨN_ĐOÁN", "THUỐC")

# B- label -> scored output type. None means the label has no counterpart in the
# competition's type set, so spans carrying it are dropped from the output.
ENTITY_TYPE_MAP = {
    "B-THUOC": "THUỐC",
    "B-TRIEU_CHUNG": "TRIỆU_CHỨNG",
    "B-BENH": "CHẨN_ĐOÁN",
    "B-XET_NGHIEM": "TÊN_XÉT_NGHIỆM",
    "B-KET_QUA_XET_NGHIEM": "KẾT_QUẢ_XÉT_NGHIỆM",
    "B-BENH_NHAN": None,
    "B-TAC_NHAN_NGOAI_SINH": None,
    # "B-VITRI": None,
    # "B-TUOI": None,
    # "B-GIOI_TINH": None
}

# Inverse of ENTITY_TYPE_MAP, for turning annotation files into BIO training data.
# Every scored type needs an entry here or its concepts silently train as O — that is
# how KẾT_QUẢ_XÉT_NGHIỆM, a fifth of the annotated concepts, used to be thrown away.
TYPE_TO_BIO = {output: label[2:]
               for label, output in ENTITY_TYPE_MAP.items() if output}

assert set(TYPE_TO_BIO) == set(OUTPUT_TYPES), "thiếu nhãn BIO cho một type được chấm"
