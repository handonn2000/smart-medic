"""Trích RxNorm từ bộ file RRF.

Đây chủ yếu là **bài toán lọc**: dữ liệu thô rất nhiều rác so với nhu cầu.
Số đo thật trên bản release trong repo:

    RXNCONSO.RRF   1.202.603 dòng
      └─ suppress='N'                807.980   (bỏ 387.468 'O' + 7.155 'E')
           └─ rxcui có ≥1 atom SAB=RXNORM  →  124.708 concept

    RXNREL.RRF     7.423.180 dòng
      └─ mức concept (rxcui1 & rxcui2 khác rỗng)   1.676.592   (−77%)
           └─ lọc theo `rela` cần dùng, bỏ chiều nghịch

    RXNSAT.RRF     KHÔNG NẠP — xem ghi chú ở cuối file.

★ Chiều quan hệ trong RXNREL NGƯỢC với trực giác. Dòng
      rxcui1=315431 | rela=consists_of | rxcui2=243670
  đọc là "**243670** consists_of **315431**" — tức quan hệ đi từ `rxcui2`
  tới `rxcui1`. Đọc ngược sẽ lật toàn bộ đồ thị thuốc mà không hề báo lỗi.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.extract.base import StagingBatch, sha256_file

SOURCE = "rxnorm_rrf"
VOCAB = "rxnorm"

# RXNCONSO.RRF
K_RXCUI, K_SAB, K_TTY, K_STR, K_SUPPRESS = 0, 11, 12, 14, 16
# RXNREL.RRF
R_RXCUI1, R_RELA, R_RXCUI2 = 0, 7, 4

# Nguồn "chủ" — rxcui chỉ trở thành concept nếu chính RxNorm khẳng định nó.
# Atom từ SAB khác (SNOMEDCT_US, MTHSPL, GS…) gắn vào làm SYNONYM, đó chính là
# nguồn làm giàu E3 mà kế hoạch ghi là "đã có sẵn, chi phí bằng không".
OWNER_SAB = "RXNORM"

# Chỉ giữ chiều thuận; chiều nghịch (inverse_isa, ingredient_of, constitutes…)
# là bản sao gương, nạp cả hai là nhân đôi vô ích — `neighbors(direction='in')`
# đã truy ngược được nhờ index idx_rel_dst.
ALLOWED_RELA = frozenset(
    {
        "isa",
        "has_ingredient",
        "has_precise_ingredient",
        "has_tradename",
        "has_dose_form",
        "has_doseformgroup",
        "consists_of",
        "has_form",
    }
)


class RxNormExtractor:
    name = SOURCE

    def __init__(self, rrf_dir: Path | None = None) -> None:
        self.dir = rrf_dir or config.RXNORM_RRF
        self.conso = self.dir / "RXNCONSO.RRF"
        self.rel = self.dir / "RXNREL.RRF"

    def available(self) -> bool:
        return self.conso.is_file() and self.rel.is_file()

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for p in (self.conso, self.rel):
            h.update(sha256_file(p).encode())
        return h.hexdigest()

    def extract(self) -> StagingBatch:
        batch = StagingBatch()
        atoms, owner_tty, n_conso = self._read_atoms()
        concepts = set(owner_tty)

        for rxcui in sorted(concepts):
            batch.concepts.append(
                {
                    "vocab": VOCAB,
                    "code": rxcui,
                    "source": SOURCE,
                    "entity_kind": "drug",
                    "pref_vi": None,
                    "pref_en": self._pref_name(owner_tty[rxcui]),
                    "is_active": True,
                }
            )

        seen: set[tuple[str, str]] = set()
        for rxcui, tty, text in atoms:
            if rxcui not in concepts:
                continue  # atom mồ côi: rxcui không được RxNorm khẳng định
            key = (rxcui, text)
            if key in seen:
                continue
            seen.add(key)
            batch.terms.append(
                {
                    "vocab": VOCAB,
                    "code": rxcui,
                    "source": SOURCE,
                    "term": text,
                    "lang": "en",  # RXNCONSO toàn bộ là ENG
                    "term_type": tty,
                    "is_preferred": False,
                    "tier": "authoritative",
                    "evidence": None,
                }
            )

        n_rel = self._read_relations(batch, concepts)

        batch.sources.append(
            {
                "source": SOURCE,
                "release": self._release(),
                "origin_file": "RXNCONSO.RRF + RXNREL.RRF",
                "sha256": self.fingerprint(),
                "n_rows": n_conso + n_rel,
            }
        )
        return batch

    # ── nội bộ ───────────────────────────────────────────────────────────

    def _release(self) -> str:
        readme = next(self.dir.parent.glob("Readme_Full_*.txt"), None)
        return readme.stem.replace("Readme_Full_", "") if readme else "unknown"

    def _read_atoms(self) -> tuple[list[tuple[str, str, str]], dict[str, dict[str, str]], int]:
        """Trả (atom, {rxcui: {tty: str}} của riêng SAB=RXNORM, số dòng đọc)."""
        atoms: list[tuple[str, str, str]] = []
        owner: dict[str, dict[str, str]] = defaultdict(dict)
        n = 0

        with self.conso.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                c = line.rstrip("\n").split("|")
                if len(c) <= K_SUPPRESS or c[K_SUPPRESS] != "N":
                    continue
                n += 1
                rxcui, tty, text = c[K_RXCUI], c[K_TTY], c[K_STR].strip()
                if not rxcui or not text:
                    continue
                atoms.append((rxcui, tty, text))
                if c[K_SAB] == OWNER_SAB:
                    owner[rxcui].setdefault(tty, text)
        return atoms, owner, n

    @staticmethod
    def _pref_name(by_tty: dict[str, str]) -> str | None:
        """Tên hiển thị theo thứ tự ưu tiên TTY.

        SCD đứng đầu vì mention thuốc trong bệnh án thường ở dạng
        "hoạt chất + hàm lượng + dạng bào chế" — đúng tầng SCD. Đáp án mẫu
        của PRD cho "amlodipine 10 mg po daily" là 308135, một mã SCD.
        """
        for tty in config.RXNORM_TTY_PRIORITY:
            if tty in by_tty:
                return by_tty[tty]
        return next(iter(by_tty.values()), None)

    def _read_relations(self, batch: StagingBatch, concepts: set[str]) -> int:
        seen: set[tuple[str, str, str]] = set()
        n = 0
        with self.rel.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                c = line.rstrip("\n").split("|")
                if len(c) <= R_RELA:
                    continue
                rxcui1, rxcui2, rela = c[R_RXCUI1], c[R_RXCUI2], c[R_RELA]
                if not rxcui1 or not rxcui2:
                    continue  # dòng mức atom (5,7M dòng) — bỏ
                n += 1
                if rela not in ALLOWED_RELA:
                    continue
                # ★ chiều: rxcui2 --rela--> rxcui1
                src, dst = rxcui2, rxcui1
                if src not in concepts or dst not in concepts or src == dst:
                    continue
                key = (src, rela, dst)
                if key in seen:
                    continue
                seen.add(key)
                batch.relations.append(
                    {
                        "src_vocab": VOCAB,
                        "src_code": src,
                        "rel": rela,
                        "dst_vocab": VOCAB,
                        "dst_code": dst,
                        "rel_group": None,
                        "priority": None,
                        "tier": "authoritative",
                        "meta": None,
                    }
                )
        return n


# ── Vì sao KHÔNG nạp RXNSAT.RRF ──────────────────────────────────────────
#
# File 531 MB, 7.687.120 dòng, nhưng phân bố thuộc tính gần như toàn bộ là
# metadata đóng gói/nhãn thuốc: SPL_SET_ID (1,9 triệu), NDC (1,2 triệu),
# LABELER, MARKETING_* … Không thứ nào phục vụ bốn hàm của API đọc (§4.2).
# Hai thuộc tính có thể hữu ích — ATC_LEVEL và FDA_UNII_CODE — chỉ có vài trăm
# dòng, không đáng để parse 531 MB ở mỗi lần build.
#
# Nếu sau này cần phân nhóm thuốc theo ATC, cách rẻ hơn là lấy thẳng từ nguồn
# ATC trong RXNCONSO (SAB='ATC', 7.660 dòng) thay vì qua RXNSAT.
