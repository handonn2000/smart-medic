"""Truy hồi từ vựng bằng BM25 của FTS5.

Truy vấn được nở thành **hai dạng**: giữ dấu (`norm_term`) và bỏ dấu
(`ascii_term`). Bỏ dấu tăng recall — "thieu men g6pd" khớp được cả khi người
dùng gõ không dấu — còn BM25 lo phần xếp hạng để không mất precision.

Ghi chú: `bm25()` của SQLite trả **số âm**, càng âm càng khớp. Ở biên API ta
đổi dấu để `Candidate.score` theo quy ước "càng lớn càng tốt".
"""

from __future__ import annotations

import re

from smart_medic.kb.normalize.text import normalize_term, to_ascii

# FTS5 tokenizer `unicode61` cắt theo ký tự không phải chữ/số. Ta cắt giống vậy
# để token truy vấn khớp với token trong index.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

MAX_TOKENS = 24


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text)


def build_match_expr(text: str, *, vocab: str | None = None) -> str:
    """Dựng biểu thức MATCH của FTS5 từ văn bản tự do.

    Dùng OR chứ không AND: mention lâm sàng thường thiếu/thừa từ so với tên
    chuẩn ("Thiếu men G6PD" vs "Thiếu máu do thiếu men glucose-6-phosphate
    dehydrogenase [G6PD]"), AND sẽ trả rỗng còn OR để BM25 xếp hạng.

    ★ `vocab` được nhét vào chính biểu thức MATCH chứ không đặt ở mệnh đề WHERE.
      Lọc ở WHERE khiến query planner chọn `concepts` làm vòng ngoài rồi
      SCAN terms_fts ở trong cùng — đo được 7,4 s cho một truy vấn. Đẩy vào
      MATCH thì FTS thành vòng ngoài và bộ lọc chạy ngay trong index.
    """
    norm = normalize_term(text)
    tokens = dict.fromkeys(tokenize(norm) + tokenize(to_ascii(norm)))
    picked = [t for t in tokens if t][:MAX_TOKENS]
    if not picked:
        return ""
    # Bọc nháy kép để ký tự lạ không bị hiểu thành cú pháp FTS5.
    body = " OR ".join(f'"{t}"' for t in picked)
    expr = f"{{norm_term ascii_term}}:({body})"
    return f'vocab:"{vocab}" AND {expr}' if vocab else expr
