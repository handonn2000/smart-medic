"""Xuất corpus + **kiểm bốn bất biến bằng chính bộ kiểm của bài nộp**.

★ VÌ SAO DÙNG LẠI `solve.check_invariants` THAY VÌ VIẾT BỘ KIỂM RIÊNG
─────────────────────────────────────────────────────────────────────
Viết bộ kiểm riêng cho corpus thì hai bộ kiểm sẽ trôi khỏi nhau, và ngày chúng
khác nhau là ngày ta huấn luyện model trên một định dạng mà bài nộp không chấp
nhận. Gọi lại đúng hàm đang gác cổng bài nộp thì khoảng cách đó bằng 0 theo kiến
tạo.

Bốn bất biến (1–3 đã có sẵn trong `check_invariants`):
    1. `text[start:end] == span.text` với MỌI span
    2. span không chồng lấn
    3. `candidates` rỗng với TRIỆU_CHỨNG / TÊN_XN / KẾT_QUẢ_XN
    4. corpus chấm được bằng `stages.scoring` mà không sửa gì

★ ĐỊNH DẠNG GIỐNG HỆT `gold_real`
`text/NNN.txt` + `annotations/NNN.json`, để dùng chung `smk eval solve` mà không
cần một nhánh code nào riêng.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from smart_medic.stages.scoring import Entity, score_document
from smart_medic.stages.solve import check_invariants
from smart_medic.synth.schema import SynthDoc


class CorpusInvariantError(AssertionError):
    """Corpus hỏng. Huấn luyện trên nó là học cái sai — thà nổ."""


def verify(doc: SynthDoc) -> None:
    """Bốn bất biến cho MỘT tài liệu."""
    ents = [
        Entity(s.text, s.type, s.start, s.end, s.candidates, s.assertions)
        for s in sorted(doc.spans, key=lambda s: (s.start, s.end))
    ]
    try:
        check_invariants(doc.text, ents)  # 1–3, đúng hàm gác cổng bài nộp
    except AssertionError as exc:
        raise CorpusInvariantError(f"{doc.name}: {exc}") from exc

    # 4. Chấm được, và chấm CHÍNH NÓ phải ra điểm tuyệt đối — nếu không thì
    #    corpus và bộ chấm đang hiểu khác nhau về cùng một file.
    s = score_document(ents, ents, name=doc.name)
    if round(s.final, 9) != 1.0:
        raise CorpusInvariantError(f"{doc.name}: tự chấm chính nó ra {s.final}, phải là 1.0")

    # Cụm gây nhiễu phải KHÔNG có span nào phủ — đó là lý do chúng tồn tại.
    for ds, de in doc.distractors:
        for e in ents:
            if e.start < de and e.end > ds:
                raise CorpusInvariantError(
                    f"{doc.name}: span {e.text!r} phủ lên cụm gây nhiễu [{ds},{de}]"
                )


def write(docs: list[SynthDoc], out_dir: Path, *, seed: int, meta: dict | None = None) -> dict:
    """Ghi corpus. Kiểm bất biến TRƯỚC khi ghi — không để lại file hỏng trên đĩa."""
    for d in docs:
        verify(d)

    text_dir, ann_dir = out_dir / "text", out_dir / "annotations"
    text_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    for d in docs:
        (text_dir / f"{d.name}.txt").write_text(d.text, encoding="utf-8")
        (ann_dir / f"{d.name}.json").write_text(d.to_json(), encoding="utf-8")
        h.update(d.text.encode())
        h.update(d.to_json().encode())

    manifest = {
        "seed": seed,
        "n_docs": len(docs),
        "n_spans": sum(len(d.spans) for d in docs),
        "n_distractors": sum(len(d.distractors) for d in docs),
        "corpus_sha256": h.hexdigest(),
        **(meta or {}),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_splits(docs: list[SynthDoc], out_dir: Path, *, seed: int, dev_frac: float = 0.15) -> dict:
    """Chia train/dev **TỔNG HỢP**.

    ★ Dev phải là tài liệu tổng hợp, không bao giờ là `gold_real`. Chọn epoch hay
    dò ngưỡng trên `gold_real` là làm hỏng chính cái cổng đang dùng để quyết định
    (quy tắc §5.7).
    """
    import random

    rng = random.Random(seed)
    names = [d.name for d in docs]
    rng.shuffle(names)
    n_dev = max(1, int(len(names) * dev_frac))
    splits = {"dev": sorted(names[:n_dev], key=int), "train": sorted(names[n_dev:], key=int)}
    (out_dir / "splits.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"n_train": len(splits["train"]), "n_dev": len(splits["dev"])}
