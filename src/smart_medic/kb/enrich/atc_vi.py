"""E6 — tên hoạt chất TIẾNG VIỆT cho concept RxNorm, bắc cầu qua mã ATC.

Trước nguồn này, vocab `rxnorm` trong KB có **0 term tiếng Việt**: mọi tên thuốc
đều là tiếng Anh của RxNorm ("acetazolamide", "amoxicillin"). Nhưng bệnh án
tiếng Việt viết "Acetazolamid", "Amoxicilin" — mất `-e` cuối, `ph`→`f`, bỏ dấu
nháy. BM25 trên token nguyên vẹn không bắc được khoảng cách đó.

Nguồn: bảng DDD của Bộ Y tế (`data/knowledge_base/atc/ddd.csv`, theo ATC/DDD
Index 2016). Đây là văn bản hành chính VN nên **chính tả trong đó là chính tả
mà bác sĩ VN thực sự gõ** — đúng thứ ta cần khớp.

★ ÁNH XẠ TẤT ĐỊNH, KHÔNG FUZZY, KHÔNG LLM
──────────────────────────────────────────
    tên tiếng Việt  →  mã ATC cấp 5  →  RxCUI

Cả hai chặng đều là tra bảng. Bảng DDD tự khai mã ATC cho từng dòng; RxNorm
có sẵn atom `SAB='ATC'` mang chính mã đó. Không có bước đoán nào, nên sai sót
duy nhất có thể xảy ra là sai ở nguồn — và nó truy vết được qua `evidence`.

★ BA BỘ LỌC, MỖI BỘ CHẶN MỘT KIỂU SAI KHÁC NHAU
────────────────────────────────────────────────
1. **Tên chứa `+`** → thuốc phối hợp nhiều hoạt chất ("Amoxicilin + Acid
   clavulanic"). Bảng DDD vẫn gán cho nó MỘT mã ATC, nhưng gắn tên phối hợp vào
   concept đơn chất là sai về bản chất: mention "amoxicilin + acid clavulanic"
   phải ra RxCUI của thuốc phối hợp, không phải của amoxicilin. 398 dòng.
2. **Tên chứa `*` hoặc `(`** → ký hiệu danh mục BHYT và chú thích đường dùng,
   không phải một phần của tên thuốc. 62 + 98 dòng.
3. **Mã ATC phải dài ĐÚNG 7 ký tự** (cấp 5, `A10BF01`). Đây là bộ lọc quan
   trọng nhất và dễ bỏ sót nhất: mã ngắn hơn là tên NHÓM giải phẫu/trị liệu
   (`A10B` = "thuốc hạ đường huyết uống"), không phải một hoạt chất. RxNorm
   cũng có atom ATC cho các mã nhóm này, nên bỏ qua bước lọc là gắn thẳng tên
   thuốc cụ thể vào concept nhóm — sai âm thầm, không có exception nào nổ.

── Số đo trên bản dữ liệu trong repo ────────────────────────────────────
    Dòng có mã ATC                              2.019
      └─ tên đơn chất (sau 3 bộ lọc trên)         716 cặp (tên, mã)
           └─ tên duy nhất                        669
    Mã ATC cấp 5 duy nhất                         681
      ├─ tra được trong RxNorm                    661   (mỗi mã đúng 1 RxCUI)
      └─ không có atom ATC nào                     20
    Tên nối được vào concept CÓ TRONG KB           609
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from smart_medic.kb import config
from smart_medic.kb.enrich.base import EnrichBatch
from smart_medic.kb.extract.base import sha256_file

NAME = "atc_ddd_byt"
TIER = "derived"
VOCAB = "rxnorm"
RELEASE = "ATC/DDD Index 2016 — bảng DDD Bộ Y tế"

# RXNCONSO.RRF: 0 RXCUI, 11 SAB, 13 CODE, 16 SUPPRESS.
K_RXCUI, K_SAB, K_CODE, K_SUPPRESS = 0, 11, 13, 16
ATC_SAB = "ATC"

# Hai dòng đầu file là tiêu đề trình bày ("BẢNG DDD MẪU…" và một dòng trống có
# dấu phẩy), header thật nằm ở dòng thứ 3. Đọc thẳng bằng `DictReader` sẽ lấy
# nhầm "BẢNG DDD MẪU…" làm tên cột và mọi lần tra cột đều trả None.
HEADER_ROW = 2
COL_ATC, COL_NAME = "Mã ATC", "Thuốc"

# Mã ATC cấp 5 = hoạt chất. Ngắn hơn là mã NHÓM — xem docstring, bộ lọc 3.
ATC_LEVEL5_LEN = 7

# Ký tự tố cáo dòng KHÔNG phải tên một hoạt chất đơn lẻ — xem docstring, bộ lọc 1-2.
NOT_A_SINGLE_INGREDIENT = ("+", "*", "(")


def is_single_ingredient(name: str) -> bool:
    """Tên có phải MỘT hoạt chất không, hay là phối hợp / ký hiệu danh mục."""
    return bool(name) and not any(ch in name for ch in NOT_A_SINGLE_INGREDIENT)


def is_level5(code: str) -> bool:
    """Mã ATC cấp 5 (hoạt chất) — phân biệt với mã nhóm ngắn hơn."""
    return len(code) == ATC_LEVEL5_LEN


class AtcVietnameseNames:
    name = NAME
    release = RELEASE

    def __init__(self, path: Path | None = None, conso: Path | None = None) -> None:
        self.path = path or config.ATC_DDD_CSV
        self.conso = conso or config.RXNORM_RRF / "RXNCONSO.RRF"
        self.stats: dict[str, int] = {}
        # Mã ATC cấp 5 có trong bảng DDD nhưng không nối được tới concept trong
        # KB. Báo cáo chứ không nuốt: đây là tín hiệu bản RxNorm đã lệch.
        self.skipped: list[tuple[str, str]] = []

    def available(self) -> bool:
        return self.path.is_file() and self.conso.is_file()

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for p in (self.path, self.conso):
            h.update(sha256_file(p).encode())
        return h.hexdigest()

    # ── nội bộ ───────────────────────────────────────────────────────────

    def _vietnamese_names(self) -> dict[str, list[str]]:
        """{mã ATC cấp 5: [tên tiếng Việt]} — đã qua cả ba bộ lọc.

        Một mã có thể nhận nhiều tên (biến thể chính tả giữa các dòng), và một
        tên có thể xuất hiện ở nhiều dòng với cùng mã — nên gom về list đã khử
        trùng, giữ thứ tự gặp để kết quả tất định.
        """
        text = self.path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(text.splitlines()[HEADER_ROW:]))
        out: dict[str, list[str]] = {}
        n_coded = n_combo = 0
        for row in rows:
            code = (row.get(COL_ATC) or "").strip()
            name = (row.get(COL_NAME) or "").strip()
            if not code or not name:
                continue
            n_coded += 1
            if not is_single_ingredient(name):
                n_combo += 1
                continue
            if not is_level5(code):
                continue
            names = out.setdefault(code, [])
            if name not in names:
                names.append(name)
        self.stats["ddd_rows_with_atc"] = n_coded
        self.stats["dropped_not_single_ingredient"] = n_combo
        self.stats["atc_level5_codes"] = len(out)
        return out

    def _atc_to_rxcui(self, wanted: set[str]) -> dict[str, str]:
        """{mã ATC: RxCUI} từ RXNCONSO, chỉ atom ATC còn hiệu lực.

        Đọc theo dòng vì file 131 MB — nạp cả vào RAM là vô ích khi ta chỉ cần
        đúng ~700 mã. `SUPPRESS != 'N'` là atom đã bị RxNorm rút; dùng nó sẽ
        gắn tên vào concept mà chính RxNorm không còn công nhận.
        """
        out: dict[str, str] = {}
        with self.conso.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                col = line.split("|")
                if len(col) <= K_SUPPRESS:
                    continue
                if col[K_SAB] != ATC_SAB or col[K_SUPPRESS] != "N":
                    continue
                code = col[K_CODE]
                # Lọc lại cấp 5 ở ĐÂY nữa, không chỉ ở phía bảng DDD: RxNorm có
                # atom ATC cho cả mã nhóm, và `wanted` đã sạch nhưng bộ lọc này
                # giữ hàm đúng kể cả khi ai đó gọi nó với tập khác.
                if not is_level5(code) or code not in wanted:
                    continue
                out.setdefault(code, col[K_RXCUI])
        self.stats["atc_resolved_in_rxnorm"] = len(out)
        return out

    # ── điểm vào ─────────────────────────────────────────────────────────

    def enrich(self, known: dict[str, set[str]]) -> EnrichBatch:
        batch = EnrichBatch()
        rxnorm_codes = known.get(VOCAB, set())
        if not rxnorm_codes:
            return batch

        by_code = self._vietnamese_names()
        if not by_code:
            return batch
        atc_to_rxcui = self._atc_to_rxcui(set(by_code))

        n_terms = 0
        linked_names: set[str] = set()
        for atc in sorted(by_code):
            rxcui = atc_to_rxcui.get(atc)
            if rxcui is None or rxcui not in rxnorm_codes:
                self.skipped.append((VOCAB, atc))
                continue
            for name in by_code[atc]:
                batch.add_term(
                    vocab=VOCAB,
                    code=rxcui,
                    source=NAME,
                    term=name,
                    lang="vi",
                    term_type="atc_vi_name",
                    tier=TIER,
                    # Bắt buộc với tier `derived` (§P3.3 quy tắc 3). Giữ mã ATC
                    # để truy ngược được từ một term bất kỳ về đúng dòng nguồn.
                    evidence={"via": "atc", "atc": atc},
                )
                linked_names.add(name)
                n_terms += 1
        self.stats["names_linked"] = len(linked_names)
        self.stats["terms_added"] = n_terms
        return batch
