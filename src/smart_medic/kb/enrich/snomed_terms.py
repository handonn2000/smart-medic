"""E1 — mượn term lâm sàng của SNOMED cho mã ICD, qua ExtendedMap.
Kèm H2 — thẻ ngữ nghĩa của concept cho, ghi vào `attributes`.

SNOMED ở đây là **nguồn CHO**, không phải bộ mã thứ ba: ta không tạo concept
SNOMED nào cả, chỉ lấy cách diễn đạt của nó gắn vào mã ICD đã có. KB vẫn tập
trung vào hai bộ mã được chấm điểm.

── Số đo trên bản release trong repo ────────────────────────────────────
    Map active                                   154.960
      ├─ mapRule = TRUE (vô điều kiện)           154.752   (99,9%)
      └─ có điều kiện (giới tính, tuổi)              208
    Lọc thêm mapCategory = "properly classified" 129.741
    Mã ICD đích duy nhất                          10.702
      └─ có trong KB                              10.666   (99,7%)

★ CÁI BẪY: phân bố fan-in cực lệch. Các **mã gom** nhận hàng nghìn concept:

    T88.7  Tác dụng phụ của thuốc, không đặc hiệu   ← 1.600 concept SNOMED
    X44    Ngộ độc do thuốc khác/không đặc hiệu     ← 1.372
    Z88.8  Tiền sử dị ứng thuốc khác                ←   865

Kéo cả 1.600 term vào `T88.7` thì mã đó khớp gần như mọi đoạn văn nhắc tới
thuốc — hỏng precision, mà Jaccard phạt nặng mã thừa.

Cách chặn: **giới hạn fan-in**. Phân bố cho điểm cắt rất rõ —

    ngưỡng    mã ICD được làm giàu    term nạp vào
      ≤ 5           53,1%                10,7%
      ≤ 10          71,5%                22,4%     ← điểm ngọt
      ≤ 20          85,9%                39,8%
      ≤ 50          96,1%                65,9%

14% mã còn lại nuốt 60% số term — đúng phần đuôi rác. Ta nạp với ngưỡng RỘNG
(`SNOMED_FANIN_INGEST_MAX`) và **ghi `fan_in` vào `evidence`**, rồi lọc chặt ở
query time. Nhờ vậy chỉnh ngưỡng không phải build lại, và ngưỡng trở thành
tham số đo được trên probe set thay vì con số phỏng đoán.
"""

from __future__ import annotations

import collections
import hashlib
import re
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.enrich.base import EnrichBatch
from smart_medic.kb.extract.base import sha256_file

NAME = "snomed_int"
TIER = "derived"
VOCAB = "icd10"

# der2_iisssccRefset_ExtendedMap: 0 id, 2 active, 4 refsetId, 5 referencedComponentId,
#                                 6 mapGroup, 7 mapPriority, 8 mapRule, 10 mapTarget,
#                                 12 mapCategoryId
M_ACTIVE, M_REFSET, M_SOURCE = 2, 4, 5
M_GROUP, M_PRIORITY, M_RULE, M_TARGET, M_CATEGORY = 6, 7, 8, 10, 12

# sct2_Description: 0 id, 2 active, 4 conceptId, 6 typeId, 7 term
D_ACTIVE, D_CONCEPT, D_TYPE, D_TERM = 2, 4, 6, 7

# sct2_Concept: 0 id, 2 active
C_ID, C_ACTIVE = 0, 2

# FSN kết thúc bằng thẻ ngữ nghĩa: "Pneumonia (disorder)"
_SEMANTIC_TAG = re.compile(r"\(([^()]+)\)\s*$")


def semantic_tag(fsn: str) -> str:
    """Thẻ ngữ nghĩa cuối FSN, hoặc 'unknown' — không im lặng bỏ qua (H2)."""
    m = _SEMANTIC_TAG.search(fsn)
    return m.group(1).strip().lower() if m else "unknown"


class SnomedTermDonor:
    name = NAME

    def __init__(self, snapshot: Path | None = None) -> None:
        root = snapshot or config.SNOMED_SNAPSHOT
        self.concept = next(root.glob("Terminology/sct2_Concept_Snapshot_*.txt"), None)
        self.description = next(root.glob("Terminology/sct2_Description_Snapshot-en_*.txt"), None)
        self.extmap = next(root.glob("Refset/Map/der2_iisssccRefset_ExtendedMap*.txt"), None)
        self.stats: dict[str, int] = {}

    def available(self) -> bool:
        return all(
            p is not None and p.is_file() for p in (self.concept, self.description, self.extmap)
        )

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for p in (self.concept, self.description, self.extmap):
            h.update(sha256_file(p).encode())
        return h.hexdigest()

    # ── nội bộ ───────────────────────────────────────────────────────────

    def _active_concepts(self) -> set[str]:
        out = set()
        with self.concept.open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.split("\t", 3)
                if len(c) > C_ACTIVE and c[C_ACTIVE] == "1":
                    out.add(c[C_ID])
        return out

    def _usable_maps(self, icd_codes: set[str]) -> dict[str, str]:
        """{snomed_id: icd_code} — chỉ map vô điều kiện và phân loại đúng."""
        out: dict[str, str] = {}
        n_active = 0
        with self.extmap.open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) <= M_CATEGORY or c[M_ACTIVE] != "1":
                    continue
                n_active += 1
                if c[M_REFSET] != config.SNOMED_ICD10_REFSET:
                    continue
                if c[M_RULE] != "TRUE" or c[M_CATEGORY] != config.SNOMED_MAPCAT_PROPER:
                    continue
                target = c[M_TARGET].strip()
                if target and target in icd_codes:
                    out.setdefault(c[M_SOURCE], target)
        self.stats["map_active"] = n_active
        self.stats["map_usable"] = len(out)
        return out

    # ── điểm vào ─────────────────────────────────────────────────────────

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        batch = EnrichBatch()
        icd_codes = known.get(VOCAB, set())
        if not icd_codes:
            return batch

        maps = self._usable_maps(icd_codes)
        active = self._active_concepts()
        # Description.active=1 là CHƯA ĐỦ: 535.233 FSN active nhưng chỉ 383.853
        # concept active — description sống vẫn có thể thuộc concept đã chết.
        maps = {sid: code for sid, code in maps.items() if sid in active}
        self.stats["donor_concepts"] = len(maps)

        fan_in = collections.Counter(maps.values())
        self.stats["icd_covered"] = len(fan_in)

        cap = config.SNOMED_FANIN_INGEST_MAX
        donors = {sid: code for sid, code in maps.items() if fan_in[code] <= cap}
        self.stats["donor_after_fanin_cap"] = len(donors)

        tags: dict[str, set[str]] = collections.defaultdict(set)
        seen: set[tuple[str, str]] = set()

        with self.description.open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) <= D_TERM or c[D_ACTIVE] != "1":
                    continue
                sid = c[D_CONCEPT]
                code = donors.get(sid)
                if code is None:
                    continue
                text = c[D_TERM].strip()
                if not text:
                    continue
                if c[D_TYPE] == config.SNOMED_TYPE_FSN:
                    tags[code].add(semantic_tag(text))
                    text = _SEMANTIC_TAG.sub("", text).strip()
                key = (code, text)
                if key in seen:
                    continue
                seen.add(key)
                batch.add_term(
                    vocab=VOCAB,
                    code=code,
                    source=NAME,
                    term=text,
                    lang="en",
                    term_type="snomed_synonym",
                    tier=TIER,
                    evidence={"via": "snomed_map", "src": sid, "fan_in": fan_in[code]},
                )

        # H2 — thẻ ngữ nghĩa của concept cho, ghi vào `attributes`.
        # KHÔNG ghi đè `concepts.entity_kind`: theo Bona & Ceusters (JBI 2018,
        # 10.1016/j.jbi.2018.02.009) thẻ này không phải lúc nào cũng khớp vị trí
        # thật trong phân cấp, nên nó là FEATURE chứ không phải nhãn vàng.
        for code, tagset in sorted(tags.items()):
            for tag in sorted(tagset):
                batch.add_attribute(vocab=VOCAB, code=code, attr="snomed_semantic_tag", value=tag)
        self.stats["semantic_tags"] = sum(len(v) for v in tags.values())
        return batch
