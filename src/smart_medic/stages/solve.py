"""Chạy đầu-cuối: thư mục `.txt` → thư mục `.json` đúng định dạng nộp bài.

Đây là thứ *thực sự được chấm*. Mọi module khác chỉ là thành phần.

    input/1.txt … 100.txt   →   output/1.json … 100.json

★ NĂM BẤT BIẾN, KIỂM NGAY LÚC GHI
──────────────────────────────────
PRD §8 liệt kê chúng trong checklist rủi ro. Checklist chỉ hữu ích nếu có ai đó
chạy — nên ở đây chúng là **assert lúc ghi file**, không phải ghi chú:

1. `position` cắt lại đúng `text` trên chuỗi GỐC — lỗi này im lặng và ăn điểm cả
   `text_score` lẫn tính hợp lệ của span.
2. `candidates` **rỗng** với TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM / KẾT_QUẢ_XÉT_NGHIỆM.
   Đề quy định vậy, và Jaccard cho rỗng-gặp-rỗng bằng 1,0 nên gán bừa là mất
   điểm chắc chắn.
3. `assertions` chỉ có ở CHẨN_ĐOÁN / THUỐC / TRIỆU_CHỨNG.
4. Span **không chồng lấn** — một ký tự thuộc nhiều nhất một khái niệm.
5. Đúng một `.json` cho mỗi `.txt`, cùng tên gốc.

Vi phạm thì **nổ ngay**, không ghi file hỏng ra rồi phát hiện lúc bị chấm.

★ `ensure_ascii=False` là bắt buộc
Không có nó, `"viêm phổi"` thành `"vi\\u00eam ph\\u1ed5i"`. Vẫn là JSON hợp lệ
nhưng khó đọc khi rà tay, và PRD §8 nêu đích danh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from smart_medic.kb.query import KBStore
from smart_medic.stages import labtest
from smart_medic.stages.assertion import TYPES_WITH_ASSERTIONS, assign
from smart_medic.stages.linking import VOCAB_OF_TYPE, link_all
from smart_medic.stages.ner import Gazetteer, annotate
from smart_medic.stages.scoring import Entity
from smart_medic.stages.textio import read_document

TYPES_WITH_CANDIDATES = frozenset(VOCAB_OF_TYPE)
ALL_TYPES = (
    TYPES_WITH_CANDIDATES
    | TYPES_WITH_ASSERTIONS
    | {
        labtest.TYPE_TEST,
        labtest.TYPE_RESULT,
    }
)


class OutputInvariantError(AssertionError):
    """Kết quả vi phạm định dạng đề bài. Thà nổ còn hơn nộp file hỏng."""


def solve_document(text: str, store: KBStore, gaz: Gazetteer) -> list[Entity]:
    """Toàn bộ pipeline cho một văn bản: proposer → arbiter → enricher.

    ★ HAI ĐƯỜNG, CHỌN BẰNG CỜ `arbiter_model_weight`
    ─────────────────────────────────────────────────
    `= 0` → chuỗi detector nối tiếp như trước Phase 4. Giữ lại để Phase 5 chấm
            được cấu hình C0/C1 mà không phải revert code.
    `> 0` → bốn proposer đề xuất song song (được phép chồng lấn), rồi arbiter
            chọn tập không chồng lấn có tổng trọng số lớn nhất.

    Đường thứ hai suy biến về đường thứ nhất khi trọng số model bằng 0, nên
    **phase này không thể làm hỏng thứ đang có** — an toàn theo kiến tạo.
    """
    from smart_medic.stages import arbiter, proposers
    from smart_medic.stages.flags import weight as flag_weight

    if flag_weight("arbiter_model_weight") <= 0:
        ents = annotate(text, gaz)  # NER + phân loại + luật xét nghiệm
    else:
        ents = arbiter.select(proposers.propose(text, store, gaz))
    link_all(store, ents)  # gắn mã (Track 0, rerank BẬT)
    assign(text, ents)  # assertion ConText/NegEx
    return ents


def check_invariants(text: str, ents: list[Entity]) -> None:
    """Năm bất biến ở docstring module. Ném `OutputInvariantError` nếu hỏng."""
    for e in ents:
        if text[e.start : e.end] != e.text:
            raise OutputInvariantError(
                f"span [{e.start},{e.end}] cắt ra {text[e.start : e.end]!r} "
                f"nhưng text ghi {e.text!r}"
            )
        if e.type not in ALL_TYPES:
            raise OutputInvariantError(f"nhãn lạ: {e.type!r}")
        if e.candidates and e.type not in TYPES_WITH_CANDIDATES:
            raise OutputInvariantError(f"{e.type} không được có candidates: {e.candidates}")
        if e.assertions and e.type not in TYPES_WITH_ASSERTIONS:
            raise OutputInvariantError(f"{e.type} không được có assertions: {e.assertions}")

    ordered = sorted(ents, key=lambda x: (x.start, x.end))
    for a, b in zip(ordered, ordered[1:], strict=False):
        if a.end > b.start:
            raise OutputInvariantError(f"span chồng lấn: {a.text!r} và {b.text!r}")


@dataclass(slots=True)
class RunStats:
    n_docs: int = 0
    n_entities: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    # File `.json` trong thư mục đích KHÔNG ứng với input nào — sót lại từ lần
    # chạy trước. Chúng sẽ lọt vào bài nộp và có thể làm hỏng bộ chấm của BTC.
    stale: list[str] = field(default_factory=list)

    def add(self, ents: list[Entity]) -> None:
        self.n_docs += 1
        self.n_entities += len(ents)
        for e in ents:
            self.by_type[e.type] = self.by_type.get(e.type, 0) + 1


def run(
    *,
    input_dir: Path,
    out_dir: Path,
    db: Path | None = None,
) -> RunStats:
    """Chạy toàn bộ thư mục. Ghi mỗi `.txt` thành một `.json` cùng tên gốc."""
    files = sorted(input_dir.glob("*.txt"), key=lambda p: (len(p.stem), p.stem))
    if not files:
        raise FileNotFoundError(f"không có .txt nào trong {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stats = RunStats()

    with KBStore(db) as store:
        gaz = Gazetteer.from_kb(store)
        for f in files:
            text = read_document(f)
            ents = solve_document(text, store, gaz)
            ents.sort(key=lambda e: (e.start, e.end))
            check_invariants(text, ents)
            payload = [e.to_dict() for e in ents]
            (out_dir / f"{f.stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            stats.add(ents)

    expected = {f.stem for f in files}
    stats.stale = sorted(p.name for p in out_dir.glob("*.json") if p.stem not in expected)
    return stats


def write_zip(out_dir: Path, zip_path: Path, *, input_dir: Path) -> int:
    """Đóng gói ĐÚNG các `.json` ứng với input, bỏ qua file sót lại.

    Cấu trúc theo PRD §5: `output/1.json … 100.json` bên trong zip.
    """
    import zipfile

    names = sorted((f.stem for f in input_dir.glob("*.txt")), key=lambda s: (len(s), s))
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for stem in names:
            src = out_dir / f"{stem}.json"
            if not src.is_file():
                raise FileNotFoundError(f"thiếu kết quả cho {stem}.txt")
            z.write(src, arcname=f"output/{stem}.json")
    return len(names)
