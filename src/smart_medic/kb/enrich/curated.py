"""E5 — từ đồng nghĩa dân dã, viết tắt, biến thể chính tả tiếng Việt.

Đọc file TĨNH đã đóng băng ở `data/curated/vi_synonyms.yaml`. **Không gọi LLM
lúc build** — làm vậy sẽ phá mục tiêu G2 và vi phạm cảnh báo PRD §8.

Đây là nguồn có giá trị đo được cao nhất: baseline Phase 2 có 7 ca trượt khỏi
top-20 và **cả 7 đều do mention không có token nào chung với tên chuẩn**
("tiểu đường" vs "Đái tháo đường", "ung thư" vs "U ác tính", THA/ĐTĐ/COPD/GERD).
BM25 không cứu được lớp này dù chỉnh trọng số thế nào.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from smart_medic.kb import config
from smart_medic.kb.enrich.base import EnrichBatch

NAME = "curated_vi"
TIER = "generated"


class CuratedSynonyms:
    name = NAME

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CURATED_DIR / "vi_synonyms.yaml"
        self.skipped: list[tuple[str, str]] = []

    def available(self) -> bool:
        return self.path.is_file()

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        batch = EnrichBatch()
        rows = yaml.safe_load(self.path.read_text(encoding="utf-8")) or []
        for entry in rows:
            vocab, code = entry["vocab"], str(entry["code"])
            if code not in known.get(vocab, ()):
                # Mã không có trong KB — bỏ qua CÓ BÁO CÁO. Đây là tín hiệu file
                # curated đã lệch so với nguồn thô, cần soát lại.
                self.skipped.append((vocab, code))
                continue
            lang = "vi" if vocab == "icd10" else "en"
            for syn in entry["synonyms"]:
                batch.add_term(
                    vocab=vocab,
                    code=code,
                    source=NAME,
                    term=syn,
                    lang=lang,
                    term_type="curated_synonym",
                    tier=TIER,
                )
        return batch
