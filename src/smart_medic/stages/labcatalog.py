"""Danh mục xét nghiệm đóng băng — nạp `data/curated/lab_panels.v1.yaml`.

Tách khỏi `labtest.py` để phần **dữ liệu** và phần **luật cấu trúc** sửa được
độc lập: thêm một tên xét nghiệm là sửa YAML, không đụng regex.

★ VÌ SAO CÓ DANH MỤC, TRONG KHI `labtest.py` NÓI "KHÔNG DÙNG TỪ ĐIỂN"
─────────────────────────────────────────────────────────────────────
Docstring của `labtest.py` phản đối việc **chép tên xét nghiệm từ chính bộ gold
đang dùng để chấm** — làm vậy thì phép đo thành tự khen. Phản đối đó vẫn đúng và
vẫn được tôn trọng: danh mục này **cấm** lấy từ `gold_real`.

Nhưng có một việc mà chỉ danh mục làm được, và cấu trúc câu không bao giờ làm
được — phân biệt hai khối hoàn toàn giống nhau về hình thức:

    Điện tâm đồ (ECG)          Men tim
     • ST chênh lên             • Troponin I/T ↑
     • Sóng T đảo               • CK-MB ↑
       ↑ KẾT QUẢ                  ↑ TÊN XÉT NGHIỆM

Cùng là "tiêu đề rồi gạch đầu dòng". Thứ duy nhất phân biệt được là **nội dung
gạch đầu dòng có phải tên một xét nghiệm hay không**. Đó đúng là câu hỏi tra
bảng, không phải câu hỏi cú pháp.

★ VIẾT TẮT PHẢI CÓ NGỮ CẢNH
────────────────────────────
`N` (bạch cầu trung tính), `K` (kali), `HA` (huyết áp), `SA` (siêu âm), `TC`
(tiểu cầu) — nếu khớp trần thì chúng bắn vào khắp nơi. Nên viết tắt chỉ được
tính khi **ngay sau có dấu hiệu xét nghiệm**: dấu hai chấm, một con số, hoặc một
từ định tính. Đo trên gold: `"N 51,4%"`, `"BC 5,38 G/l"`, `"HBsAg (+)"` —
cả ba đều thoả.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from smart_medic.kb.config import CURATED_DIR

CATALOG_FILE = "lab_panels.v1.yaml"

# Ngữ cảnh bắt buộc ngay sau một VIẾT TẮT để nó được tính là tên xét nghiệm.
#
# ★ CHỈ NHỮNG DẤU HIỆU KHÔNG THỂ NHẦM. Bản đầu có thêm nhánh "từ định tính"
#   (`dương|âm|tăng|giảm|không|chưa…`) và nó bắt ngay `"Bệnh nhân K không sốt"`
#   thành xét nghiệm kali — `không` mở đầu vô số câu tiếng Việt bình thường.
#   Nhánh từ vựng chuyển sang khớp bằng `Catalog.result_re` (cụm ĐẦY ĐỦ), xem
#   `labtest._iter_catalog_hits`.
_ABBR_CONTEXT = re.compile(
    r"""\s{0,3}(?:
        :                       # HBsAg: dương tính
      | [(\[]?[+\-±][)\]]       # HBsAg (+)
      | \d                      # BC 5,38 G/l
    )""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Catalog:
    """Danh mục đã biên dịch. Bất biến — nạp một lần, dùng chung."""

    names: frozenset[str]  # đã hạ chữ thường
    abbrs: frozenset[str]  # PHÂN BIỆT hoa thường
    name_re: re.Pattern[str]
    abbr_re: re.Pattern[str]
    result_re: re.Pattern[str]
    prose_separators: tuple[str, ...]
    result_stop_phrases: tuple[str, ...]
    extra_units: tuple[str, ...]

    def is_test_name(self, s: str) -> bool:
        """Chuỗi có phải một tên xét nghiệm đã biết không (khớp TRỌN VẸN)."""
        s = s.strip().strip(".,;:")
        return s.lower() in self.names or s in self.abbrs

    def leading_test_name(self, s: str) -> str | None:
        """Tên xét nghiệm ở ĐẦU chuỗi, dài nhất. Trả phần khớp, không phải cả `s`.

        Dùng cho gạch đầu dòng kiểu `"Troponin I/T ↑ (chẩn đoán nhồi máu)"` —
        gold chỉ khoanh `"Troponin I/T"`.
        """
        m = self.name_re.match(s)
        if m:
            return m.group(0)
        m = self.abbr_re.match(s)
        return m.group(0) if m else None


def _escape_alt(items: list[str]) -> str:
    """Alternation regex, DÀI TRƯỚC để khớp tham lam đúng chỗ.

    Không có bước sắp này thì `Troponin` nuốt mất `Troponin I/T`.
    """
    return "|".join(re.escape(s) for s in sorted(set(items), key=len, reverse=True))


def _compile(raw: dict) -> Catalog:
    names: list[str] = []
    abbrs: list[str] = []
    for panel in raw.get("panels") or []:
        for test in panel.get("tests") or []:
            names.extend(test.get("names") or [])
            abbrs.extend(test.get("abbr") or [])

    vocab = raw.get("result_vocab") or {}
    fixed = [
        *(vocab.get("qualitative") or []),
        *(vocab.get("normal") or []),
        *(vocab.get("pending") or []),
    ]
    trends = vocab.get("trend_heads") or []

    # Kết quả: cụm cố định, HOẶC một đầu-cụm xu hướng rồi chạy tới ranh giới câu.
    # `(?!\w)` thay cho `\b` vì cụm có thể kết thúc bằng `)` hoặc `-`.
    result_re = re.compile(
        r"(?:"
        + _escape_alt([s for s in fixed if s.strip()])
        + r")(?!\w)"
        + r"|\b(?:"
        + _escape_alt(trends)
        + r")\b[^,;.:\n]{0,60}",
        re.IGNORECASE,
    )

    return Catalog(
        names=frozenset(n.lower() for n in names if n.strip()),
        abbrs=frozenset(a for a in abbrs if a.strip()),
        name_re=re.compile(r"(?:" + _escape_alt(names) + r")(?!\w)", re.IGNORECASE),
        abbr_re=re.compile(r"(?:" + _escape_alt(abbrs) + r")(?!\w)"),
        result_re=result_re,
        prose_separators=tuple(raw.get("prose_separators") or []),
        result_stop_phrases=tuple(raw.get("result_stop_phrases") or []),
        extra_units=tuple(raw.get("extra_units") or []),
    )


@functools.lru_cache(maxsize=2)
def load_catalog(path: Path | None = None) -> Catalog:
    """Nạp và biên dịch danh mục. Có cache — regex chỉ compile một lần."""
    p = path or CURATED_DIR / CATALOG_FILE
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return _compile(raw)


def abbr_has_context(text: str, end: int) -> bool:
    """Ngay sau vị trí `end` có dấu hiệu xét nghiệm không (xem docstring module)."""
    return _ABBR_CONTEXT.match(text, end) is not None
