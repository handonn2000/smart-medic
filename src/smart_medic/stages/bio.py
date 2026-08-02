"""Mã hoá BIO và giải mã CÓ RÀNG BUỘC — **không phụ thuộc torch**.

★ VÌ SAO TÁCH RA MỘT MODULE RIÊNG, KHÔNG NHÉT VÀO `tagger.py`
─────────────────────────────────────────────────────────────
Toàn bộ phần dễ sai nhất của Phase 3 nằm ở đây, và không có phần nào của nó cần
mạng nơ-ron: ánh xạ subword → ký tự, và ràng buộc chuyển trạng thái BIO. Tách ra
thì chúng **test được đầy đủ mà không cần torch**, kể cả trên máy chưa cài.

Đó cũng là điều kiện của Phase 6: `stages/tagger.py` phải chạy được (suy biến an
toàn) khi thiếu torch, mà muốn vậy thì phần lõi không được nằm sau `import torch`.

★ ƯU TIÊN SỐ MỘT LÀ OFFSET, KHÔNG PHẢI F1
──────────────────────────────────────────
Một span lệch offset **không chỉ mất điểm span đó** — nó ăn cả `text_score`
(WER trên đoạn cắt sai) lẫn tính hợp lệ của `position`, và `check_invariants` sẽ
làm hỏng cả bài nộp. Dự án đã có hai sự cố offset đo được:

    `sample_output.json` của BTC lệch 19/19 mục vì CRLF
    `100.txt` trộn NFC với NFD NGAY BÊN TRONG một cụm — cùng chuỗi
    `"tiền sản giật"` mà chỗ dài 16 ký tự, chỗ khác 13

Nên `offset_mapping` phải tính trên **chuỗi gốc chưa chuẩn hoá**, và mọi span trả
ra đều cắt lại từ chính `text` chứ không ghép lại từ token.

★ RÀNG BUỘC CHUYỂN TRẠNG THÁI — VÌ SAO KHÔNG DÙNG ARGMAX TRẦN
──────────────────────────────────────────────────────────────
Argmax từng token sinh ra chuỗi nhãn **không hợp lệ về mặt cú pháp**:

    O  I-THUỐC  I-THUỐC        ← `I-` mở đầu, không có `B-`
    B-THUỐC  I-CHẨN_ĐOÁN       ← `I-` của nhãn KHÁC nối vào

Sửa sau bằng heuristic thì mỗi người sửa một kiểu. Viterbi với ma trận chuyển
trạng thái chặn cứng hai lỗi trên cho ra chuỗi hợp lệ **có điểm cao nhất**, tất
định, O(n · |L|²) với |L| = 11 — rẻ hơn hẳn chi phí gọi model.

Tham chiếu: Lafferty, McCallum & Pereira, *Conditional Random Fields* (ICML
2001); Lample et al., *Neural Architectures for NER* (NAACL 2016).
"""

from __future__ import annotations

from smart_medic.stages.scoring import Entity

# Thứ tự CỐ ĐỊNH. Checkpoint lưu chỉ số nhãn, nên đổi thứ tự là hỏng âm thầm
# mọi weights đã huấn luyện — cùng loại bẫy với `concept_id` của KB.
ENTITY_TYPES: tuple[str, ...] = (
    "TRIỆU_CHỨNG",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
    "CHẨN_ĐOÁN",
    "THUỐC",
)

LABELS: tuple[str, ...] = ("O",) + tuple(f"{p}-{t}" for t in ENTITY_TYPES for p in ("B", "I"))
LABEL_TO_ID: dict[str, int] = {lab: i for i, lab in enumerate(LABELS)}
O_ID = 0

# Token đặc biệt / khoảng trắng: `offset_mapping` cho `(0, 0)`.
NULL_SPAN = (0, 0)
IGNORE_ID = -100  # quy ước của HuggingFace cho token không tính loss


def is_legal(prev: str, cur: str) -> bool:
    """`I-X` chỉ hợp lệ ngay sau `B-X` hoặc `I-X`. Mọi trường hợp khác đều được."""
    if not cur.startswith("I-"):
        return True
    return prev.endswith(cur[2:]) and prev != "O"


def transition_mask() -> list[list[bool]]:
    """`mask[i][j]` — từ nhãn `i` có được sang nhãn `j` không."""
    return [[is_legal(a, b) for b in LABELS] for a in LABELS]


# ── Mã hoá: span ký tự → nhãn token ───────────────────────────────────────


def spans_to_tags(offsets: list[tuple[int, int]], spans: list[Entity]) -> list[int]:
    """Nhãn BIO cho từng token, từ span mức KÝ TỰ.

    Token đặc biệt (`offset == (0, 0)`) nhận `IGNORE_ID` để không tính loss —
    quy ước của HuggingFace.

    Token được gán vào span nếu **chồng lấn** với nó. Chồng lấn chứ không phải
    chứa trọn: subword thường cắt giữa từ, và một span bắt đầu giữa subword vẫn
    phải được học.
    """
    tags = [IGNORE_ID] * len(offsets)
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    for i, (s, e) in enumerate(offsets):
        if (s, e) == NULL_SPAN:
            continue
        tags[i] = O_ID
        for sp in ordered:
            if s < sp.end and e > sp.start:
                prefix = "B" if s <= sp.start else "I"
                tags[i] = LABEL_TO_ID[f"{prefix}-{sp.type}"]
                break
    return tags


# ── Giải mã: điểm số token → span ký tự ───────────────────────────────────


def viterbi(scores: list[list[float]], mask: list[list[bool]] | None = None) -> list[int]:
    """Chuỗi nhãn HỢP LỆ có tổng điểm lớn nhất.

    `scores[t][l]` là điểm (log-prob hoặc logit) của nhãn `l` tại token `t`.
    Không có mô hình chuyển trạng thái học được — chỉ chặn cứng đường bất hợp lệ.
    Vậy là đủ: ta cần *tính hợp lệ*, không cần *xác suất chuyển*.
    """
    if not scores:
        return []
    m = mask or transition_mask()
    n_lab = len(scores[0])
    best = list(scores[0])
    back: list[list[int]] = []
    for t in range(1, len(scores)):
        prev_best = best
        cur = [float("-inf")] * n_lab
        ptr = [0] * n_lab
        for j in range(n_lab):
            for i in range(n_lab):
                if not m[i][j] or prev_best[i] == float("-inf"):
                    continue
                v = prev_best[i] + scores[t][j]
                if v > cur[j]:
                    cur[j], ptr[j] = v, i
        best = cur
        back.append(ptr)
    last = max(range(n_lab), key=lambda i: best[i])
    path = [last]
    for ptr in reversed(back):
        last = ptr[last]
        path.append(last)
    return list(reversed(path))


def tags_to_spans(text: str, offsets: list[tuple[int, int]], tag_ids: list[int]) -> list[Entity]:
    """Gom nhãn token thành span ký tự, **cắt lại từ chính `text`**.

    ★ Không bao giờ ghép chuỗi từ token. Tokenizer có thể chuẩn hoá, bỏ khoảng
    trắng, hoặc gộp ký tự — ghép lại từ token là cách chắc chắn nhất để `text`
    trả ra khác với `text[start:end]`, tức phá bất biến 1 của bài nộp.
    """
    out: list[Entity] = []
    cur_type: str | None = None
    cur_start = cur_end = 0
    for (s, e), tid in zip(offsets, tag_ids, strict=False):
        lab = LABELS[tid] if 0 <= tid < len(LABELS) else "O"
        if (s, e) == NULL_SPAN or lab == "O":
            if cur_type:
                out.append(_make(text, cur_type, cur_start, cur_end))
                cur_type = None
            continue
        prefix, typ = lab.split("-", 1)
        if prefix == "B" or cur_type != typ:
            if cur_type:
                out.append(_make(text, cur_type, cur_start, cur_end))
            cur_type, cur_start, cur_end = typ, s, e
        else:
            cur_end = e
    if cur_type:
        out.append(_make(text, cur_type, cur_start, cur_end))
    return [e for e in out if e.text.strip()]


# ★ Dấu câu cuối câu bị TOKENIZER DÁN vào token cuối của span.
#
#   Đo được trên corpus: gold là `"64.5"` [1205,1209] nhưng token cuối là `".5."`
#   [1207,1210], nên span khôi phục thành `"64.5."`. Tương tự `"(+)"` → `"(+)."`.
#   BIO ở mức token **không diễn tả được** ranh giới nằm giữa một token, nên đây
#   là giới hạn của biểu diễn chứ không phải bug.
#
#   Đo trên 60 tài liệu, vòng tròn mã hoá→giải mã:
#       không tỉa   mất 178/4584 = 3,88%   thừa 420
#       tỉa `.,;`   mất  85/4584 = 1,85%   thừa 327
#   Giảm hơn nửa lượng span sai, và không có phương án nào tốt hơn ở mức token.
#
#   ⚠️ Đánh đổi đã biết: viết tắt kết thúc bằng dấu chấm (`"q.d."` trong
#   `gold_batch1`) sẽ bị tỉa thành `"q.d"`. Chấp nhận — nó hiếm hơn hẳn dấu chấm
#   cuối câu, và `gold_batch1` không phải cổng.
_TRAILING_PUNCT = ".,;"


def _make(text: str, typ: str, start: int, end: int) -> Entity:
    """Cắt span, tỉa hai đầu **bằng cách dịch chỉ số**, không `strip()`.

    `strip()` trả về chuỗi mới mà không cho biết đã bỏ bao nhiêu ký tự ở đầu, nên
    dùng nó là mất luôn `start` đúng — và `text[start:end] == text` là bất biến 1
    của bài nộp.
    """
    while start < end and text[start].isspace():
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in _TRAILING_PUNCT):
        end -= 1
    return Entity(text=text[start:end], type=typ, start=start, end=end)
