"""E4 — tên nhóm 3 ký tự làm synonym YẾU cho các mã con.

Ví dụ: `K21` tên "Bệnh trào ngược dạ dày - thực quản" được gắn thêm vào
`K21.0` và `K21.9`. Cứu các ca mà mention chỉ đủ thông tin ở mức nhóm.

★ Rủi ro đã biết: **khớp quá rộng**. Mọi mã con của cùng một nhóm nhận đúng
một chuỗi giống nhau, nên mention ở mức nhóm sẽ khớp đều tất cả mã con và BM25
không phân biệt được. Vì vậy term này mang `term_type='group_rollup'` để lọc
riêng, và toàn bộ nguồn E4 bật/tắt độc lập — nếu đo thấy Recall@1 tụt thì tắt.
"""

from __future__ import annotations

from smart_medic.kb.enrich.base import EnrichBatch

NAME = "icd_group_rollup"
TIER = "derived"
VOCAB = "icd10"


class IcdGroupRollup:
    name = NAME

    def __init__(self, group_names: dict[str, str] | None = None) -> None:
        # {mã nhóm: tên tiếng Việt}. Được `enrich/__init__` nạp từ staging.
        self.group_names = group_names or {}

    def available(self) -> bool:
        return bool(self.group_names)

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        batch = EnrichBatch()
        codes = known.get(VOCAB, set())
        for code in sorted(codes):
            if "." not in code:
                continue  # bản thân mã nhóm, không cần rollup
            parent = code.split(".", 1)[0]
            name = self.group_names.get(parent)
            if not name:
                continue
            batch.add_term(
                vocab=VOCAB,
                code=code,
                source=NAME,
                term=name,
                lang="vi",
                term_type="group_rollup",
                tier=TIER,
                evidence={"via": "icd_parent", "parent": parent},
            )
        return batch
