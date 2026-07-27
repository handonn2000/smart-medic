"""Model bundle — artifact build-time, bất biến lúc chạy, verify lúc khởi động.

Cùng kỷ luật với :mod:`smart_medic.kb.store`, và vì cùng một lý do: một model
thiếu hoặc sai phiên bản phải **fail loud ngay lúc start**, không phải âm thầm
cho ra output tệ hơn ở file thứ 73. Không có nhãn vàng thì lỗi im lặng là loại
lỗi đắt nhất — đó là bài học đã trả giá bằng 471 record hỏng và 20 file lệch
offset.

Ba luật:

1. **Không tải gì lúc runtime.** Weights nằm trong ``models/`` và được commit.
   Tải lúc chạy đã có tiền lệ vỡ (PRD tab 04 §6: SapBERT cần SOCKS proxy, ba
   domain, sai tokenizer). NFR1 nói không cài lại được = bị loại.
2. **Không import onnxruntime ở module level.** Nhánh v0–v3 phải chạy được trên
   máy chỉ có thư viện chuẩn; ``import smart_medic.modelstore`` không được kéo
   theo ba wheel. Runtime nặng nạp lười trong :mod:`smart_medic.stages.neural`.
3. **normalizer_version phải khớp**, giống KB. Model được train trên chuỗi đã
   chuẩn hóa; đổi normalizer mà không train lại là đổi phân phối đầu vào — và
   sai kiểu đó không ném exception, nó chỉ làm điểm thấp.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .normalize import NORMALIZER_VERSION
from .schema import ConceptType

#: Tên file trong bundle. Cố định — bundle không phải nơi để linh hoạt.
MANIFEST_NAME = "MANIFEST.json"
REQUIRED_ARTIFACTS = frozenset({"ner.onnx", "tokenizer.json"})

#: Thư mục mặc định, cạnh repo root.
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


class ModelError(RuntimeError):
    """Bundle thiếu, sai checksum, hoặc lệch phiên bản."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_artifacts(mdir: Path, manifest: dict) -> None:
    """Fail trước khi nạp nếu artifact thiếu hoặc bị sửa."""
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ModelError(f"{MANIFEST_NAME} thiếu bảng artifacts có checksum")

    names = frozenset(artifacts)
    if not REQUIRED_ARTIFACTS <= names:
        missing = ", ".join(sorted(REQUIRED_ARTIFACTS - names))
        raise ModelError(f"manifest thiếu artifact bắt buộc: {missing}")
    unsupported = names - REQUIRED_ARTIFACTS
    if unsupported:
        raise ModelError(
            "manifest khai báo artifact không được hỗ trợ: "
            + ", ".join(sorted(unsupported))
        )

    for name, metadata in sorted(artifacts.items()):
        if Path(name).name != name:
            raise ModelError(f"tên artifact không an toàn trong manifest: {name!r}")
        if not isinstance(metadata, dict):
            raise ModelError(f"metadata artifact không hợp lệ: {name}")
        path = mdir / name
        if path.is_symlink():
            raise ModelError(f"artifact model không được là symlink: {path}")
        if not path.is_file():
            raise ModelError(
                f"thiếu artifact model: {path}\n"
                "Dựng lại bằng: python3 scripts/train_ner.py --export"
            )
        expected_size = metadata.get("bytes")
        expected_hash = metadata.get("sha256")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ModelError(f"bytes không hợp lệ trong manifest: {name}")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(char not in "0123456789abcdef" for char in expected_hash)
        ):
            raise ModelError(f"sha256 không hợp lệ trong manifest: {name}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise ModelError(
                f"artifact model sai kích thước: {name} "
                f"(manifest={expected_size}, thực tế={actual_size})"
            )
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ModelError(
                f"artifact model sai checksum: {name} "
                f"(manifest={expected_hash}, thực tế={actual_hash})"
            )


def _verify_labels(labels: list[str]) -> tuple[str, ...]:
    """Nhãn phải là BIO trên đúng 5 ConceptType, viết đầy đủ có dấu.

    Nhãn viết tắt (``TÊN_XN``) từng làm hỏng toàn bộ 471 record. Ở đây nó còn
    nguy hiểm hơn: nhãn nằm trong artifact nhị phân, sai thì không ai thấy cho
    tới lúc chấm.
    """
    if not isinstance(labels, list) or not labels:
        raise ModelError("manifest thiếu danh sách labels")
    if labels[0] != "O":
        raise ModelError(f"labels[0] phải là 'O', nhận {labels[0]!r}")
    expected = ["O"]
    for ctype in ConceptType:
        expected.extend((f"B-{ctype.value}", f"I-{ctype.value}"))
    if sorted(labels) != sorted(expected):
        missing = sorted(set(expected) - set(labels))
        extra = sorted(set(labels) - set(expected))
        raise ModelError(
            "labels không khớp lược đồ BIO của 5 ConceptType"
            + (f"; thiếu: {missing}" if missing else "")
            + (f"; thừa: {extra}" if extra else "")
            + "\nNhãn phải viết ĐẦY ĐỦ CÓ DẤU, không viết tắt."
        )
    return tuple(labels)


@dataclass(frozen=True)
class ModelBundle:
    """Mọi thứ cần để chạy inference, đã verify."""

    dir: Path
    model_version: str
    labels: tuple[str, ...]
    max_length: int
    stride: int
    manifest: dict

    @property
    def onnx_path(self) -> Path:
        return self.dir / "ner.onnx"

    @property
    def tokenizer_path(self) -> Path:
        return self.dir / "tokenizer.json"


def bundle_exists(mdir: Path | None = None) -> bool:
    """Kiểm tra rẻ, KHÔNG verify — để CLI báo lỗi tử tế thay vì stack trace."""
    mdir = Path(mdir) if mdir is not None else DEFAULT_MODEL_DIR
    return (mdir / MANIFEST_NAME).is_file()


def load_bundle(mdir: Path | None = None) -> ModelBundle:
    """Nạp và verify bundle. Ném :class:`ModelError` với thông điệp hành động được."""
    mdir = Path(mdir) if mdir is not None else DEFAULT_MODEL_DIR
    manifest_path = mdir / MANIFEST_NAME

    if not manifest_path.is_file():
        raise ModelError(
            f"không có model bundle ở {mdir}\n"
            "Nhánh v0–v3 vẫn chạy được: --extractor v3\n"
            "Dựng bundle v4: python3 scripts/train_ner.py --export"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError(f"không parse được {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ModelError(f"{MANIFEST_NAME} phải là object JSON")

    got = manifest.get("normalizer_version")
    if got != NORMALIZER_VERSION:
        raise ModelError(
            f"model train bằng normalizer_version={got} nhưng code đang dùng "
            f"{NORMALIZER_VERSION}.\nModel học trên chuỗi đã chuẩn hóa — đổi "
            "normalizer mà không train lại là đổi phân phối đầu vào, và sai "
            "kiểu đó KHÔNG ném exception, nó chỉ làm điểm thấp."
        )

    task = manifest.get("task")
    if task != "token_classification":
        raise ModelError(f"task không được hỗ trợ: {task!r}")

    _verify_artifacts(mdir, manifest)
    labels = _verify_labels(manifest.get("labels"))

    max_length = manifest.get("max_length", 512)
    stride = manifest.get("stride", 128)
    if not isinstance(max_length, int) or not 16 <= max_length <= 4096:
        raise ModelError(f"max_length không hợp lệ: {max_length!r}")
    if not isinstance(stride, int) or not 0 <= stride < max_length:
        raise ModelError(f"stride không hợp lệ: {stride!r} (phải < max_length)")

    model_version = manifest.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ModelError("manifest thiếu model_version")

    return ModelBundle(
        dir=mdir,
        model_version=model_version,
        labels=labels,
        max_length=max_length,
        stride=stride,
        manifest=manifest,
    )


def write_manifest(
    mdir: Path,
    *,
    model_version: str,
    labels: list[str],
    base_model: str,
    max_length: int = 512,
    stride: int = 128,
    extra: dict | None = None,
) -> dict:
    """Ghi MANIFEST.json cho bundle đã có sẵn file.

    Dùng bởi :mod:`scripts.train_ner` sau khi export. Checksum tính tại đây nên
    manifest không bao giờ lệch với file trên đĩa.
    """
    _verify_labels(labels)
    artifacts: dict[str, dict] = {}
    for name in sorted(REQUIRED_ARTIFACTS):
        path = mdir / name
        if not path.is_file():
            raise ModelError(f"thiếu artifact khi ghi manifest: {path}")
        artifacts[name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}

    manifest = {
        "manifest_version": 1,
        "model_version": model_version,
        "task": "token_classification",
        "base_model": base_model,
        "normalizer_version": NORMALIZER_VERSION,
        "max_length": max_length,
        "stride": stride,
        "labels": list(labels),
        "artifacts": artifacts,
        **(extra or {}),
    }
    (mdir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
