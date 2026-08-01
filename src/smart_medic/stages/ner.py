"""NER + phân loại 5 nhãn — baseline dùng chính KB làm từ điển.

Ràng buộc của đề (PRD §8): **không có tập train có nhãn**, và **phải tái lập
được từ máy sạch**. Hai điều đó cùng lúc loại bỏ cả fine-tune lẫn gọi API lúc
chạy. Thứ ta có sẵn mà đối thủ phải tự dựng là **KB 633.000 term đã chuẩn hoá**.

Nên baseline này là khớp từ điển, và nó rẻ đến mức không có lý do gì không làm
trước: 0 tham số học, chạy mili-giây, tái lập tuyệt đối.

★ BA TÍN HIỆU LẤY THẲNG TỪ KB, KHÔNG CẦN MODEL
───────────────────────────────────────────────
1. **Chương R của ICD tách TRIỆU_CHỨNG khỏi CHẨN_ĐOÁN.** ICD-10 gom "triệu
   chứng, dấu hiệu và phát hiện bất thường" vào chương R00–R99. Đo trên KB:
   `ho`→R05, `sốt`→R50, `khó thở`→R06.0, `đau ngực`→R07.4, `chóng mặt`→R42.
   Một quy tắc một dòng thay cho cả một bộ phân loại.

2. **Bộ mã nguồn quyết định nhãn thuốc.** Term đến từ `rxnorm` thì là THUỐC.

3. **Mã dài hơn thì cụ thể hơn.** Khi hai term cùng khớp một đoạn, ưu tiên đoạn
   DÀI hơn — `"đái tháo đường type 2"` thắng `"đái tháo đường"`.

★ ĐIỀU BASELINE NÀY KHÔNG LÀM ĐƯỢC
Từ điển chỉ tìm được thứ có trong từ điển. TÊN_XÉT_NGHIỆM và phần lớn
KẾT_QUẢ_XÉT_NGHIỆM định tính không nằm trong ICD/RxNorm — chúng thuộc địa hạt
LOINC (PRD tab 04 §2). Phần đó dùng luật, và **cố ý để yếu** thay vì chép danh
sách từ chính bộ gold đang dùng để chấm — làm vậy là tự khen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from smart_medic.kb.query import KBStore
from smart_medic.kb.query.rerank import canonical_term
from smart_medic.stages.scoring import Entity

# Cắt token giống tokenizer `unicode61` của FTS5 để từ điển và văn bản khớp nhau.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Số cụm tối đa của một mention. Đo trên gold: dài nhất là 7 từ.
MAX_NGRAM = 8

# ★ Chặn khớp bừa. KB có những term dài 1–2 ký tự (`K`, `AF`, `RA`) — để nguyên
#   thì `K` khớp mọi chỗ. Ngưỡng áp cho CHUỖI, không cho số từ.
MIN_TERM_CHARS = 3

# Ngoại lệ cho ngưỡng trên: triệu chứng tiếng Việt rất hay chỉ một âm tiết.
# `"đau"` KHÔNG nằm đây: một mình nó quá chung, đo được 7 entity thừa.
SHORT_ALLOW: frozenset[str] = frozenset({"ho", "sốt", "phù", "nôn", "ói"})

# ICD chương R = "triệu chứng, dấu hiệu và phát hiện bất thường".
_CHAPTER_R = re.compile(r"^R\d")

# ★ Tiền tố loại chung. KB có `"Bệnh lý tăng huyết áp"` nhưng KHÔNG có
#   `"tăng huyết áp"` — mà bệnh án luôn viết dạng sau. Bóc tiền tố cho ra biến
#   thể mà văn bản thật dùng. Cùng bản chất với `canonical_term` ở
#   `kb.query.rerank`, chỉ khác là bóc ĐẦU thay vì bóc ĐUÔI.
_GENERIC_PREFIX = re.compile(r"^(bệnh lý|bệnh|hội chứng|chứng|tật|rối loạn)\s+", re.IGNORECASE)

# ★ Chặn từ đời thường lọt vào từ điển. Chúng là term ICD thật (tên mức độ, tên
#   nhóm) nhưng trong văn xuôi thì gần như luôn là từ thường — đo được: chúng
#   sinh ra `"trung bình"`, `"nhẹ"`, `"thuốc"` như CHẨN_ĐOÁN.
#   Đây là từ phổ thông tiếng Việt, KHÔNG phải danh sách chép từ bộ gold.
STOP_PHRASES: frozenset[str] = frozenset(
    {
        "nhẹ", "vừa", "nặng", "trung bình", "khác", "thuốc", "bệnh", "chứng",
        "cấp", "mạn", "mãn", "cấp tính", "mạn tính", "mãn tính",
        "không xác định", "không đặc hiệu", "biến chứng", "di chứng",
        "tiền sử", "gia đình", "toàn thân", "khu trú", "nguyên phát", "thứ phát",
    }
)  # fmt: skip

TYPE_SYMPTOM = "TRIỆU_CHỨNG"
TYPE_DIAGNOSIS = "CHẨN_ĐOÁN"
TYPE_DRUG = "THUỐC"
TYPE_TEST = "TÊN_XÉT_NGHIỆM"
TYPE_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"


# ── Kết quả xét nghiệm: luật ăn chắc hơn model (PRD §4) ──────────────────
#
# Giá trị số kèm đơn vị. Bắt cả `11.2 mmol/L`, `92%`, `14,43`, `38.5-39°C`.
_LAB_VALUE = re.compile(
    r"""
    \d+(?:[.,]\d+)?                      # số, thập phân bằng . hoặc ,
    (?:\s*[-–]\s*\d+(?:[.,]\d+)?)?       # khoảng: 325-650
    \s*
    (?:%|°C|mmol/L|mmol/l|mg/dL|mg/dl|g/L|g/l|U/L|u/l|mmHg|mEq/L
       |K/uL|k/ul|G/L|10\^\d+/L|bpm|ml|mL)?
    """,
    re.VERBOSE,
)


def tokens_with_offset(text: str) -> list[tuple[str, int, int]]:
    """Cắt token kèm vị trí gốc. **Không** chuẩn hoá chuỗi nguồn — offset là thiêng."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def norm_key(parts: list[str]) -> str:
    """Khoá tra từ điển: hạ chữ thường, nối bằng một khoảng trắng."""
    return " ".join(p.lower() for p in parts)


@dataclass(slots=True)
class Gazetteer:
    """Ánh xạ `cụm đã chuẩn hoá → nhãn`. Dựng một lần từ KB."""

    entries: dict[str, str]

    @property
    def max_ngram(self) -> int:
        return MAX_NGRAM

    @classmethod
    def from_kb(cls, store: KBStore) -> Gazetteer:
        """Dựng từ điển từ term tiếng Việt của ICD và tên hoạt chất của RxNorm.

        Chỉ lấy `tier='authoritative'` và term do người curate (E5) — **không**
        lấy 144.882 term tiếng Anh mượn từ SNOMED. Chúng phục vụ truy hồi khi đã
        biết mention, còn ở đây chúng chỉ làm nhiễu: văn bản tiếng Việt không
        chứa `"Acrodermatitis chronica atrophicans"`.
        """
        entries: dict[str, str] = {}

        rows = store.conn.execute(
            """
            SELECT c.code, t.term
            FROM concepts c JOIN terms t USING(concept_id)
            WHERE c.vocab = 'icd10' AND t.lang = 'vi' AND t.tier != 'derived'
            """
        )
        for code, term in rows:
            label = TYPE_SYMPTOM if _CHAPTER_R.match(code or "") else TYPE_DIAGNOSIS
            _add(entries, term, label)

        # Chỉ tầng hoạt chất: tên SCD dài kèm dạng bào chế gần như không bao giờ
        # xuất hiện nguyên văn trong bệnh án tiếng Việt.
        rows = store.conn.execute(
            """
            SELECT t.term
            FROM concepts c JOIN terms t USING(concept_id)
            WHERE c.vocab = 'rxnorm' AND t.term_type IN ('IN', 'PIN')
            """
        )
        for (term,) in rows:
            _add(entries, term, TYPE_DRUG)

        return cls(entries=entries)

    def lookup(self, key: str) -> str | None:
        return self.entries.get(key)


def surface_forms(term: str) -> list[str]:
    """Các biến thể mà văn bản lâm sàng thật có thể viết.

    Ba dạng, đều suy ra máy móc — không chép từ bộ gold:

    >>> surface_forms("Tăng lipid máu, không xác định")
    ['tăng lipid máu không xác định', 'tăng lipid máu']
    >>> surface_forms("Bệnh lý tăng huyết áp")
    ['bệnh lý tăng huyết áp', 'tăng huyết áp']
    >>> surface_forms("Viêm phổi")
    ['viêm phổi']

    ★ Biến thể bóc tiền tố chỉ được nhận khi còn **từ 3 token trở lên**. Ngắn
    hơn thì gần như luôn là bộ phận cơ thể hoặc tên hệ cơ quan, không phải tên
    bệnh — đo được, chúng sinh ra 30 entity thừa trên bộ gold:

        "Bệnh gan"          → gan        (1 token)
        "Bệnh tim mạch"     → tim mạch   (2 token)
        "Rối loạn nội tiết" → nội tiết   (2 token)

    Còn ca cần cứu thì vượt ngưỡng: `"Bệnh lý tăng huyết áp"` → `"tăng huyết
    áp"` (3 token).

    >>> surface_forms("Bệnh gan")
    ['bệnh gan']
    >>> surface_forms("Rối loạn nội tiết")
    ['rối loạn nội tiết']
    """
    out: list[str] = []
    for cand in (term, canonical_term(term)):
        key = norm_key(_TOKEN.findall(cand))
        if key and key not in out:
            out.append(key)
        stripped = norm_key(_TOKEN.findall(_GENERIC_PREFIX.sub("", cand)))
        if stripped and stripped not in out and len(stripped.split()) >= 3:
            out.append(stripped)
    return out


def _add(entries: dict[str, str], term: str, label: str) -> None:
    for key in surface_forms(term):
        if len(key.split()) > MAX_NGRAM:
            continue
        if len(key) < MIN_TERM_CHARS and key not in SHORT_ALLOW:
            continue
        if key in STOP_PHRASES:
            continue
        # CHẨN_ĐOÁN thắng khi trùng khoá: cùng một chuỗi vừa là tên bệnh vừa là
        # tên hoạt chất thì trong bệnh án nó gần như luôn là chẩn đoán.
        if entries.get(key) == TYPE_DIAGNOSIS:
            continue
        entries[key] = label


def detect(text: str, gaz: Gazetteer) -> list[Entity]:
    """Tìm khái niệm y tế trong văn bản. Khớp DÀI NHẤT, quét trái sang phải.

    Không chồng lấn: một ký tự thuộc nhiều nhất một entity — đúng như định dạng
    output của đề.
    """
    toks = tokens_with_offset(text)
    out: list[Entity] = []
    i = 0
    while i < len(toks):
        hit = None
        for n in range(min(gaz.max_ngram, len(toks) - i), 0, -1):
            window = toks[i : i + n]
            label = gaz.lookup(norm_key([w[0] for w in window]))
            if label:
                hit = (n, window[0][1], window[-1][2], label)
                break
        if hit is None:
            i += 1
            continue
        n, start, end, label = hit
        out.append(Entity(text=text[start:end], type=label, start=start, end=end))
        i += n
    return out


def detect_lab_values(text: str, taken: list[Entity]) -> list[Entity]:
    """Giá trị xét nghiệm bằng luật, chỉ ở vùng chưa có entity nào.

    Bỏ qua số đứng một mình không có đơn vị — số thứ tự mục ("1.", "2.") và tuổi
    sẽ lọt vào nếu không chặn.
    """
    busy = [(e.start, e.end) for e in taken]
    out: list[Entity] = []
    for m in _LAB_VALUE.finditer(text):
        s, e = m.start(), m.end()
        frag = text[s:e].strip()
        if not frag or frag[-1].isdigit():
            continue  # không có đơn vị → không phải kết quả xét nghiệm
        if any(s < be and e > bs for bs, be in busy):
            continue
        out.append(Entity(text=frag, type=TYPE_RESULT, start=s, end=s + len(frag)))
    return out


def annotate(text: str, gaz: Gazetteer) -> list[Entity]:
    """Toàn bộ bước phát hiện + phân loại cho một văn bản."""
    ents = detect(text, gaz)
    ents += detect_lab_values(text, ents)
    ents.sort(key=lambda e: (e.start, e.end))
    return ents
