"""Xếp hạng lại ứng viên sau truy hồi — nhánh THUỐC và nhánh CHẨN_ĐOÁN.

Nhánh thuốc: hai tín hiệu phải NHÂN với nhau.

BM25 chọn được đúng *vùng* thuốc nhưng chọn sai *tầng trừu tượng*. Đo trên gold
thật của BTC (11 mention): `R@1 = 0,182`. Cả 9 ca trượt đều là lỗi cấu trúc —
sai tầng TTY, sai dạng bào chế — không ca nào là lỗi hiểu nghĩa.

Hai tín hiệu sửa được việc đó:

**R2 — độ phủ token.** F1 giữa token truy vấn và token của term ứng viên. Vế
precision phạt ứng viên có **token thừa**: `aspirin 81 mg Delayed Release Oral
Tablet` bị phạt so với `aspirin 81 mg Oral Tablet` khi mention không nói gì về
"delayed release".

**R3 — TTY prior.** Đề bài chấm ở tầng **thuốc kê đơn** (SCD/SBD). Đáp án mẫu
cho `"aspirin 81 mg po daily"` là `243670` — một SCD, không phải `315431` (SCDC)
hay `1191` (IN).

★ VÌ SAO PHẢI NHÂN, KHÔNG PHẢI CỘNG
────────────────────────────────────
Lần cài đầu chỉ dùng R2 và **R@1 tụt về 0,000** — tệ hơn cả không làm gì. Nguyên
nhân: sau khi bóc sig, `"aspirin 81 mg po daily"` thành `"aspirin 81 mg"`, mà
chuỗi đó khớp **hoàn hảo** (F1 = 1,0) với SCDC `315431` có tên đúng là
`"aspirin 81 mg"`. Tầng SCDC bao giờ cũng khớp chuỗi tốt hơn tầng SCD, vì nó
chính là "hoạt chất + hàm lượng" mà không có dạng bào chế thừa ra.

Nên **độ phủ token một mình là tín hiệu phản tác dụng ở nhánh thuốc.** Nó chỉ
đúng khi bị TTY prior chặn lại. Cộng hai điểm không cứu được: một ứng viên F1
hoàn hảo vẫn thắng. Phải nhân, để prior thấp *triệt tiêu* được F1 cao.

Đây là lý do module này không tách thành hai bộ lọc độc lập.
"""

from __future__ import annotations

import re

from smart_medic.kb.normalize.sig import strip_sig
from smart_medic.kb.query.models import Candidate

# ★ Dấu tổ hợp Unicode phải nằm TRONG token.
#
# `[^\W_]+` không khớp ký tự tổ hợp (category Mn), nên trên văn bản NFD nó làm
# VỠ VỤN từ tiếng Việt: `"tiền"` → `["tie", "n"]`. Đo được: 20/100 file trong
# `data/test/` không ở dạng NFC, và `100.txt` còn trộn NFC với NFD ngay trong
# một cụm từ. Không có lớp này thì mọi mention trong các file đó vô hình.
_TOKEN = re.compile(r"(?:[^\W_]|[̀-ͯ])+", re.UNICODE)

# ── Prior phụ thuộc vào việc mention CÓ HÀM LƯỢNG hay không ──────────────
#
# PRD tab 04 §1.2: *"mention có hàm lượng + đường dùng → map về SCD/SBD"*. Hệ
# quả ngược cũng đúng và quan trọng ngang: mention **không** có hàm lượng thì
# đáp án là **hoạt chất**, không phải một thuốc kê đơn tuỳ chọn.
#
# Bằng chứng từ hai bộ gold, cùng một hoạt chất:
#     "docusate sodium"              → 71722   (PIN — hoạt chất)
#     "docusate sodium 100 mg po bid"→ 1099279 (SCD — thuốc kê đơn)
#
# Một prior cứng không thể đúng cả hai. Nên chọn bảng theo mention.

# Mention CÓ hàm lượng → tầng thuốc kê đơn.
TTY_PRIOR_DOSED: dict[str, float] = {
    "SCD": 1.00,
    "SBD": 1.00,
    "CD": 0.90,
    "BD": 0.90,
    "GPCK": 0.85,
    "BPCK": 0.85,
    "IN": 0.60,
    "PIN": 0.60,
    "PT": 0.60,
    "BN": 0.55,
    # Thành phần, KHÔNG kê được — dìm dù nó khớp chuỗi tốt nhất.
    "SCDC": 0.30,
    "SCDF": 0.30,
    "SBDC": 0.30,
    "SBDF": 0.30,
}

# Mention KHÔNG có hàm lượng → tầng hoạt chất.
TTY_PRIOR_BARE: dict[str, float] = {
    "IN": 1.00,
    "PIN": 1.00,
    "PT": 0.90,
    "BN": 0.80,
    "SCD": 0.55,
    "SBD": 0.55,
    "CD": 0.50,
    "BD": 0.50,
    "SCDC": 0.40,
    "SCDF": 0.40,
    "SBDC": 0.40,
    "SBDF": 0.40,
}
DEFAULT_PRIOR = 0.50

# Hàm lượng = lượng hoạt chất. `mg`, `mcg`, `g`, `%`, `unt`, `meq`…
#
# ★ `ml` CỐ Ý không nằm đây: nó là *thể tích liều*, không phải hàm lượng.
#   `"nystatin oral suspension 5 ml"` không nói hoạt chất bao nhiêu — và đúng
#   như vậy, gold của BTC cho mention đó là `7597`, tức hoạt chất.
# `%` tách riêng khỏi nhánh có `\b`: nó không phải ký tự chữ nên `\b` phía sau
# không bao giờ khớp ở cuối chuỗi ("cream 2 %").
_STRENGTH = re.compile(
    r"\d\s*(?:(?:mg|mcg|ug|µg|g|kg|unt|unit|units|iu|meq|mmol)\b|%)",
    re.IGNORECASE,
)


def has_strength(text: str) -> bool:
    """Mention có nêu hàm lượng hoạt chất không.

    >>> has_strength("aspirin 81 mg po daily")
    True
    >>> has_strength("docusate sodium")
    False
    >>> has_strength("nystatin oral suspension 5 ml po qid:prn")
    False
    """
    return bool(_STRENGTH.search(text))


def tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def coverage_f1(query: set[str], term: set[str]) -> float:
    """F1 giữa hai tập token.

    Recall  — truy vấn được phủ bao nhiêu (thiếu token ⇒ ứng viên chưa đủ).
    Precision — ứng viên có bao nhiêu token thừa (thừa ⇒ ứng viên quá đặc hiệu).

    >>> coverage_f1({"aspirin", "81", "mg"}, {"aspirin", "81", "mg"})
    1.0
    >>> round(coverage_f1({"aspirin", "81", "mg"}, {"aspirin", "81", "mg", "oral", "tablet"}), 3)
    0.75
    """
    if not query or not term:
        return 0.0
    hit = len(query & term)
    if not hit:
        return 0.0
    precision = hit / len(term)
    recall = hit / len(query)
    return 2 * precision * recall / (precision + recall)


def _terms_by_concept(store, concept_ids: list[int]) -> dict[int, list[tuple[str, str]]]:
    """Mọi (term, term_type) của các concept, lấy trong MỘT truy vấn."""
    if not concept_ids:
        return {}
    marks = ",".join("?" * len(concept_ids))
    rows = store.conn.execute(
        f"SELECT concept_id, term, term_type FROM terms WHERE concept_id IN ({marks})",
        concept_ids,
    )
    out: dict[int, list[tuple[str, str]]] = {}
    for row in rows:
        out.setdefault(row["concept_id"], []).append((row["term"], row["term_type"] or ""))
    return out


def score_candidate(
    query: set[str], terms: list[tuple[str, str]], prior: dict[str, float]
) -> float:
    """Điểm cao nhất trong các term của concept: `F1(term) × prior(TTY của term)`.

    Prior lấy theo **chính term khớp**, không phải theo concept. Một concept có
    cả SCD lẫn SCDC; nếu term khớp là SCDC thì đó mới là thứ đáng dìm.
    """
    best = 0.0
    for term, tty in terms:
        f1 = coverage_f1(query, tokens(term))
        if f1 <= 0.0:
            continue
        best = max(best, f1 * prior.get(tty, DEFAULT_PRIOR))
    return best


# ── Nhánh CHẨN_ĐOÁN ──────────────────────────────────────────────────────
#
# ★ ĐIỀU KHÔNG LÀM, VÀ VÌ SAO
# Ca trượt hay gặp nhất là gold `J18.9` còn truy hồi trả mã cha `J18`. Cám dỗ tự
# nhiên là thêm luật "ưu tiên mã con .9". Đo trên gold lâm sàng thì luật đó HOÀ:
#
#     19 lượt gold là mã con đặc hiệu
#     16 lượt gold là mã CHA 3 ký tự **dù mã .9 vẫn tồn tại**
#       "viêm phổi"                        → J18.9  (con)
#       "bệnh trào ngược dạ dày - thực quản" → K21  (cha, dù có K21.9)
#
# Hai mention cùng hình dạng, hai mức chi tiết khác nhau. Quy ước của người gán
# nhãn không suy ra được từ mention, nên bất kỳ luật cha/con nào cũng đổi ca này
# lấy ca kia. Ở đây CỐ Ý không cài luật đó.
#
# Đo lại trên bộ gold đã mở rộng (48 lượt) và đối chiếu chéo — luật này không
# "hoà" mà THUA rõ:
#
#     mô phỏng "nếu top-1 là cha của top-2 thì đảo chỗ"
#       gold lâm sàng (48)   THẮNG  9   THUA 14
#       probe        (84)    THẮNG  0   THUA 46   ← huỷ diệt
#
# Probe 122 dùng mention ở mức nhóm ("đái tháo đường", "suy thận") nên mã cha
# mới là đáp án; gold lâm sàng dùng chẩn đoán xác định nên nghiêng về mã `.9`.
# Một luật cứng không phục vụ được cả hai.
#
# Chỉ cài phần bất khả tranh cãi: mã KHOẢNG (`E10-E14`) không bao giờ là đáp án.
#
# ★ KẾT QUẢ ÂM — hai tín hiệu đã thử và BỊ BỎ
#   Thử thêm (a) phạt tên chứa "khác" và (b) phạt chương R/Z. Trên gold lâm sàng
#   chúng có vẻ tốt (R@5 0,857 → 0,881), nhưng đo tiếp trên probe 84 ca chẩn
#   đoán thì chúng **phá**:
#
#                          gold lâm sàng (42)   probe (84)
#       BM25 thuần            R@1 0,357         R@1 0,857
#       chỉ canonical+range   R@1 0,571         R@1 0,940   ← giữ
#       + "khác" + chương     R@1 0,571         R@1 0,833   ← BỎ
#
#   Tức chúng overfit vào 42 lượt và kéo probe xuống DƯỚI cả baseline. Bài học:
#   "vùng phẳng rộng" khi quét tham số trên MỘT bộ nhỏ vẫn có thể là overfit —
#   phải quét trên bộ thứ hai mới biết.
ICD_RANGE_PRIOR = 0.25
ICD_NORMAL_PRIOR = 1.00

_RANGE_CODE = re.compile(r"^[A-Z]\d{2}-[A-Z]\d{2}$")

# Đuôi định tính mà mention KHÔNG BAO GIỜ chứa. Giữ lại thì vế precision của F1
# phạt oan mã `.9`; bỏ đi thì nó được so công bằng với mã cha.
# `[^,]*?` cho phép có chữ chen giữa dấu phẩy và bổ ngữ:
# `"Nhiễm trùng đường tiết niệu, VỊ TRÍ không xác định"`. Đo được: nới như vậy
# nâng probe 84 ca chẩn đoán R@1 0,940 → 0,952, gold lâm sàng không đổi.
_RESIDUAL_TAIL = re.compile(
    r",\s*[^,]*?(không xác định|không phân loại|không đặc hiệu|không rõ|chưa xác định).*$",
    re.IGNORECASE,
)


def is_range_code(code: str) -> bool:
    """Mã khoảng/khối như `E10-E14` — nhóm gom, không phải chẩn đoán.

    >>> is_range_code("E10-E14")
    True
    >>> is_range_code("E11.9")
    False
    """
    return bool(_RANGE_CODE.match(code))


def canonical_term(term: str) -> str:
    """Bỏ đuôi định tính để so khớp công bằng giữa mã cha và mã `.9`.

    >>> canonical_term("Viêm phổi, không xác định")
    'Viêm phổi'
    >>> canonical_term("Bệnh tăng huyết áp vô căn (nguyên phát)")
    'Bệnh tăng huyết áp vô căn (nguyên phát)'
    """
    return _RESIDUAL_TAIL.sub("", term).strip()


def rerank_disease(store, mention: str, candidates: list[Candidate]) -> list[Candidate]:
    """Xếp lại ứng viên CHẨN_ĐOÁN bằng độ phủ token × prior mã khoảng.

    Vế precision của F1 tự xử được ca `"tăng huyết áp"` → `R03.0` (chỉ số HA cao
    *chưa* chẩn đoán): tên của `R03.0` chứa đủ token truy vấn nhưng kèm 7 token
    thừa, nên bị phạt so với `I10`.
    """
    if not candidates:
        return candidates
    query = tokens(mention)
    if not query:
        return candidates

    by_concept = _terms_by_concept(store, [c.concept.concept_id for c in candidates])
    scored = []
    for i, cand in enumerate(candidates):
        terms = by_concept.get(cand.concept.concept_id, [])
        best = max(
            (coverage_f1(query, tokens(canonical_term(t))) for t, _tty in terms),
            default=0.0,
        )
        prior = ICD_RANGE_PRIOR if is_range_code(cand.concept.code) else ICD_NORMAL_PRIOR
        scored.append((best * prior, cand.score, i, cand))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [c for _, _, _, c in scored]


def rerank_drug(store, mention: str, candidates: list[Candidate]) -> list[Candidate]:
    """Xếp lại ứng viên THUỐC. Không thêm, không bớt — chỉ đổi thứ tự.

    Chỉ đụng tới ứng viên đã có trong top-k, nên **không thể làm giảm Recall@k**
    ở chính k đó; nó chỉ có thể đẩy mã đúng lên hoặc xuống trong tập ấy.

    Tie-break bằng điểm BM25 gốc để kết quả tất định.
    """
    if not candidates:
        return candidates
    query = tokens(strip_sig(mention))
    if not query:
        return candidates

    prior = TTY_PRIOR_DOSED if has_strength(mention) else TTY_PRIOR_BARE
    by_concept = _terms_by_concept(store, [c.concept.concept_id for c in candidates])
    scored = [
        (score_candidate(query, by_concept.get(c.concept.concept_id, []), prior), c.score, i, c)
        for i, c in enumerate(candidates)
    ]
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [c for _, _, _, c in scored]
