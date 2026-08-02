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
# ★ BUG CONTAINER SỐ 4 (Phase 6). Thiếu dòng này thì `stages/flags.py` rơi về
#   DEFAULTS trong container — `labtest_extended=False` — và pipeline giải bài
#   âm thầm tụt về cấu hình C0, mất đúng 0,053 điểm mà Phase 1 kiếm được.
#   Không lỗi, không cảnh báo. Máy dev không bao giờ thấy vì file luôn ở đó.
COPY data/curated/ ./data/curated/
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

# ═══════════════════════ solve ═══════════════════════════
# Thứ THỰC SỰ ĐƯỢC CHẤM: 100 file .txt → 100 file .json.
#
# ★ Không có `torch`. Phase 5 chọn cấu hình C1 (luật + nhánh xét nghiệm mở rộng),
#   nên đường chạy bài nộp KHÔNG chạm tới model. Đó vừa là 1,1 GB không phải
#   tải, vừa là một lớp rủi ro PRD §5 không phải gánh: "BTC không cài đặt lại
#   được source code → nhóm thi bị loại".
FROM runtime AS solve

# Chốt cấu hình NGAY LÚC BUILD. Cổng này tồn tại vì bug container số 4 là loại
# hỏng-im-lặng: không có nó, một image thiếu `data/curated/` vẫn chạy trơn tru
# và chỉ tệ hơn ở điểm số.
RUN python -c "\
from smart_medic.stages.flags import active_config; \
c = active_config(); \
assert 'DEFAULTS' not in c['_source'], 'image THIẾU data/curated/pipeline.v1.yaml'; \
assert c['labtest_extended'] is True, 'cấu hình không khớp C1 đã chọn ở Phase 5'; \
assert c['arbiter_model_weight'] == 0.0, 'C1 không dùng model'; \
print('cấu hình OK:', {k: v for k, v in c.items() if not k.startswith('_')})"

# Xác minh KHÔNG có torch trên đường chạy — `stages/tagger.py` phải suy biến an
# toàn chứ không được ném.
RUN python -c "\
import importlib.util; \
assert importlib.util.find_spec('torch') is None, 'torch KHÔNG được có trong image solve'; \
from smart_medic.stages import tagger; \
assert tagger.detect('viêm phổi', enabled=True) == [], 'tagger phải trả rỗng khi thiếu torch'; \
print('không có torch, tagger suy biến an toàn')"

VOLUME ["/app/data/test", "/app/data/output", "/app/data/submission"]

ENTRYPOINT ["smk", "solve"]
CMD ["--input", "data/test", "--out", "data/output", "--zip", "data/submission/output.zip"]
