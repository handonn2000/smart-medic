"""Nạp KB và tra cứu gazetteer.

KB chỉ đọc. Nạp một lần lúc khởi động, kiểm ``normalizer_version`` ngay — fail
loud lúc start chứ không phải lúc chạy giữa chừng.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..normalize import NORMALIZER_VERSION


class KBError(RuntimeError):
    pass


def _read(path: Path) -> list[dict]:
    if not path.exists():
        raise KBError(f"thiếu bảng KB: {path}\nChạy: python -m smart_medic.kb.build")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@dataclass(frozen=True)
class GazMatch:
    """Một lần khớp gazetteer trên chuỗi norm."""

    ns: int
    ne: int
    alias: str
    codes: tuple[str, ...]
    is_symptom_chapter: bool
    risk_short: bool


class IcdGazetteer:
    """Tra tên bệnh ICD nguyên văn bằng longest-match, không chồng lấn.

    Kỷ luật longest-match là bắt buộc: "suy tim" (I50) lồng trong "suy tim,
    không đặc hiệu" (I50.9) — khớp ngắn thì trả sai mã.

    Mặc định LOẠI alias ``risk_short`` (≤6 ký tự). Đo được: "thận"→D30.0 là tên
    bị cắt cụt trong bảng (mất chữ "U lành"), khớp 27 lần trong corpus và sai
    100% — ngữ cảnh thật là "sỏi thận", "bệnh thận mạn", "hội chứng thận hư".
    """

    def __init__(
        self,
        aliases: list[dict],
        concepts: dict[str, dict],
        *,
        drop_risk_short: bool = True,
    ) -> None:
        self.concepts = concepts
        by_alias: dict[str, list[str]] = {}
        self._risky: set[str] = set()
        for a in aliases:
            an = a["alias_norm"]
            if int(a["risk_short"]):
                self._risky.add(an)
                if drop_risk_short:
                    continue
            by_alias.setdefault(an, []).append(a["code"])

        # Chỉ mục theo token đầu → tránh quét 16k alias trên từng vị trí.
        self._by_first: dict[str, list[str]] = {}
        for an in by_alias:
            self._by_first.setdefault(an.split(" ", 1)[0], []).append(an)
        for lst in self._by_first.values():
            lst.sort(key=len, reverse=True)   # longest-match

        self._codes = {k: tuple(sorted(set(v))) for k, v in by_alias.items()}

    def __len__(self) -> int:
        return len(self._codes)

    @staticmethod
    def _boundary_ok(s: str, i: int, j: int) -> bool:
        if i > 0 and s[i - 1].isalnum():
            return False
        if j < len(s) and s[j].isalnum():
            return False
        return True

    def scan(self, norm: str) -> list[GazMatch]:
        """Quét toàn chuỗi norm, trả về các khớp không chồng lấn, dài nhất trước."""
        out: list[GazMatch] = []
        n = len(norm)
        i = 0
        while i < n:
            if not norm[i].isalnum() or (i > 0 and norm[i - 1].isalnum()):
                i += 1
                continue
            j = i
            while j < n and norm[j] != " ":
                j += 1
            first = norm[i:j]

            best: str | None = None
            for cand in self._by_first.get(first, ()):
                end = i + len(cand)
                if end <= n and norm.startswith(cand, i) and self._boundary_ok(norm, i, end):
                    best = cand
                    break                      # danh sách đã sắp dài→ngắn
            if best is None:
                i = j + 1                      # nhảy qua token, không phải +1
                continue

            end = i + len(best)
            codes = self._codes[best]
            sym = any(
                int(self.concepts[c]["is_symptom_chapter"])
                for c in codes if c in self.concepts
            )
            out.append(GazMatch(i, end, best, codes, sym, best in self._risky))
            i = end                            # con trỏ đẩy qua HẾT độ dài match
        return out


@dataclass
class KnowledgeBase:
    icd_concepts: dict[str, dict]
    icd_gaz: IcdGazetteer
    manifest: dict
    icd_aliases: tuple[dict, ...] = ()
    rx_concepts: dict[str, dict] = field(default_factory=dict)
    rx_aliases: tuple[dict, ...] = ()
    rx_remap: dict[str, str] = field(default_factory=dict)

    @property
    def remap_reverse(self) -> dict[str, list[str]]:
        rev: dict[str, list[str]] = {}
        for old, new in self.rx_remap.items():
            rev.setdefault(new, []).append(old)
        return rev


def load_kb(kbdir: Path, *, with_rxnorm: bool = True, drop_risk_short: bool = True) -> KnowledgeBase:
    mpath = kbdir / "MANIFEST.json"
    if not mpath.exists():
        raise KBError(
            f"thiếu {mpath}\nChạy: python -m smart_medic.kb.build"
        )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    got = manifest.get("normalizer_version")
    if got != NORMALIZER_VERSION:
        raise KBError(
            f"KB build bằng normalizer_version={got} nhưng code đang dùng "
            f"{NORMALIZER_VERSION}.\nAlias trong index và mention lúc chạy sẽ "
            f"chuẩn hóa khác nhau → không bao giờ khớp.\n"
            f"Chạy lại: python -m smart_medic.kb.build"
        )

    concepts = {c["code"]: c for c in _read(kbdir / "icd10_concepts.csv.gz")}
    icd_aliases = _read(kbdir / "icd10_aliases.csv.gz")
    gaz = IcdGazetteer(
        icd_aliases, concepts, drop_risk_short=drop_risk_short
    )

    rx_concepts: dict[str, dict] = {}
    rx_aliases: list[dict] = []
    remap: dict[str, str] = {}
    if with_rxnorm and (kbdir / "rxnorm_concepts.csv.gz").exists():
        rx_concepts = {c["rxcui"]: c for c in _read(kbdir / "rxnorm_concepts.csv.gz")}
        rx_aliases = _read(kbdir / "rxnorm_aliases.csv.gz")
        remap = {
            r["old_rxcui"]: r["new_rxcui"]
            for r in _read(kbdir / "rxnorm_remap.csv.gz")
        }

    return KnowledgeBase(
        icd_concepts=concepts,
        icd_gaz=gaz,
        manifest=manifest,
        icd_aliases=tuple(icd_aliases),
        rx_concepts=rx_concepts,
        rx_aliases=tuple(rx_aliases),
        rx_remap=remap,
    )
