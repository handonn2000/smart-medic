"""Đường dẫn, hằng số và ngưỡng dùng chung.

Mọi đường dẫn suy ra từ `PROJECT_ROOT` để chạy được từ bất kỳ cwd nào, và
đều override được bằng biến môi trường để container mount chỗ khác.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ROOT_MARKER = "pyproject.toml"


def find_project_root(start: Path | None = None) -> Path:
    """Gốc dự án: thư mục tổ tiên gần nhất có `pyproject.toml`, hoặc CWD.

    ★ KHÔNG đếm cứng số cấp thư mục. Bản đầu dùng
    `Path(__file__).resolve().parents[3]` — đúng khi cài `pip install -e`
    (`src/smart_medic/kb/config.py` → gốc repo), nhưng SAI khi cài bình thường:

        /usr/local/lib/python3.13/site-packages/smart_medic/kb/config.py
        parents[3] → /usr/local/lib/python3.13          ← không phải gốc dự án

    Hệ quả trong container: `DATA_DIR` trỏ vào `/usr/local/lib/python3.13/data`
    thay vì `/app/data` nơi compose mount, nên build chạy trên dữ liệu RỖNG rồi
    ghi artifact vào chỗ bị vứt đi cùng container. Lỗi này **không lộ ở máy dev**
    vì ở đó luôn cài `-e`, và nó cũng là chính thứ BTC sẽ gặp khi cài lại.

    Trong image, site-packages không có tổ tiên nào chứa `pyproject.toml` nên
    hàm rơi về `Path.cwd()` — Dockerfile đặt `WORKDIR /app`, đúng nơi mount.
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / ROOT_MARKER).is_file():
            return parent
    return Path.cwd()


PROJECT_ROOT: Final = find_project_root()


def _env_path(var: str, default: Path) -> Path:
    return Path(os.environ[var]).resolve() if os.environ.get(var) else default


DATA_DIR: Final = _env_path("SMK_DATA_DIR", PROJECT_ROOT / "data")
RAW_DIR: Final = _env_path("SMK_RAW_DIR", DATA_DIR / "knowledge_base")
STAGING_DIR: Final = _env_path("SMK_STAGING_DIR", DATA_DIR / "staging")
ARTIFACT_DIR: Final = _env_path("SMK_ARTIFACT_DIR", DATA_DIR / "artifacts")
CURATED_DIR: Final = _env_path("SMK_CURATED_DIR", DATA_DIR / "curated")

KB_SQLITE: Final = ARTIFACT_DIR / "kb.sqlite"
KB_MANIFEST: Final = ARTIFACT_DIR / "manifest.json"
KB_FAISS: Final = ARTIFACT_DIR / "kb.faiss"

# ── Nguồn thô ────────────────────────────────────────────────────────────
ICD_PDF: Final = RAW_DIR / "icd" / "icd-10-vn.pdf"
ICD_CSV: Final = RAW_DIR / "icd" / "ICD10.csv"
ICD10CM_CODES: Final = RAW_DIR / "icd" / "icd10cm-codes-2027.txt"
RXNORM_RRF: Final = RAW_DIR / "rxnorm" / "rrf"
SNOMED_SNAPSHOT: Final = RAW_DIR / "snomed" / "CT_InternationalRF2" / "Snapshot"

# ── Ngưỡng ───────────────────────────────────────────────────────────────
# Fan-in tối đa khi mượn term từ SNOMED qua ExtendedMap (Phase 3 / E1).
# Nạp rộng ở build-time, lọc chặt ở query-time để chỉnh ngưỡng không phải build lại.
SNOMED_FANIN_INGEST_MAX: Final = 50
SNOMED_FANIN_QUERY_DEFAULT: Final = 10

# Thứ tự ưu tiên TTY khi chọn tên hiển thị cho concept RxNorm.
RXNORM_TTY_PRIORITY: Final = ("SCD", "SBD", "SCDC", "IN", "PIN", "BN", "PSN", "SY")

# Refset ánh xạ SNOMED → ICD-10, và mapCategory "properly classified".
SNOMED_ICD10_REFSET: Final = "447562003"
SNOMED_MAPCAT_PROPER: Final = "447637006"
SNOMED_TYPE_ISA: Final = "116680003"
SNOMED_TYPE_FSN: Final = "900000000000003001"
SNOMED_TYPE_SYNONYM: Final = "900000000000013009"
