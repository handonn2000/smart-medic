# syntax=docker/dockerfile:1
#
# Multi-stage. Hai image cho hai nhu cầu khác nhau:
#
#   builder  — người CÓ nguồn thô, muốn dựng lại KB từ đầu (dành cho BTC)
#   runtime  — người chỉ cần TRUY VẤN, không cần 9 GB nguồn thô (đồng đội)
#
# ★ Nguồn thô KHÔNG vào image. 9 GB được mount lúc `docker run`, không phải
#   `docker build` — xem docker/compose.yaml. `.dockerignore` chặn cả
#   data/knowledge_base lẫn data/artifacts khỏi build context.

# ═══════════════════════════ base ═══════════════════════════
FROM python:3.13-slim AS base

# Tất định: khoá hash seed để không nguồn ngẫu nhiên nào lọt vào artifact (§6.3)
ENV PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ═══════════════════════ builder ═══════════════════════════
# Dựng KB từ nguồn thô. Cần pymupdf (trích PDF) và pyarrow (staging parquet).
FROM base AS builder

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[build]"

# Nơi mount nguồn thô (read-only) và nơi ghi artifact.
VOLUME ["/app/data/knowledge_base", "/app/data/artifacts"]

# Ghi lại danh tính image vào manifest.json để truy vết build.
ARG BUILDER_IMAGE=smart-medic-kb:builder
ENV SMK_BUILDER_IMAGE=${BUILDER_IMAGE}

ENTRYPOINT ["smk", "kb"]
CMD ["build"]

# ═══════════════════════ runtime ═══════════════════════════
# Chỉ TRUY VẤN. Không có pymupdf, không cần nguồn thô.
#
# Yêu cầu: artifact phải tồn tại trong build context, tức chạy `smk kb build`
# (hoặc stage `builder`) TRƯỚC khi build stage này.
FROM base AS runtime

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY data/probe/ ./data/probe/
# KHÔNG có [build]: image này chỉ đọc SQLite, không cần pymupdf/pyarrow.
RUN pip install --no-cache-dir .

COPY data/artifacts/kb.sqlite data/artifacts/manifest.json ./data/artifacts/

# Xác minh ngay lúc build: artifact có khớp schema của code không.
# Thà fail ở build còn hơn để người nhận phát hiện lúc chạy.
RUN python -c "\
from smart_medic.kb.query import KBStore, lookup; \
s = KBStore(); \
c = lookup(s, 'icd10', 'K21.0'); \
assert c is not None, 'artifact thiếu mã K21.0'; \
print('artifact OK:', c.pref_vi)"

ENTRYPOINT ["smk", "kb"]
CMD ["eval"]

# ═══════════════════════ dense (tuỳ chọn) ═══════════════════════
# Thêm nhánh truy hồi ngữ nghĩa. Tách riêng vì torch nặng ~1 GB — người chỉ cần
# tra mã không nên phải tải.
#
# ★ Model được BAKE VÀO IMAGE lúc build, không tải lúc chạy: PRD §8 cấm phụ
#   thuộc mạng khi BTC dựng lại. Revision được ghim trong kb/dense.py.
FROM runtime AS dense

RUN pip install --no-cache-dir ".[dense]"

ENV HF_HOME=/opt/hf
RUN python -c "\
from smart_medic.kb.dense import MODEL_NAME, MODEL_REVISION; \
from sentence_transformers import SentenceTransformer; \
SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION); \
print('model đã bake vào image')"

COPY data/artifacts/kb.faiss data/artifacts/kb.faiss.meta.json ./data/artifacts/
