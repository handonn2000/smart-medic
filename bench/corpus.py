"""So đặc trưng một tập nhãn với tập tham chiếu — dùng để thẩm định dữ liệu sinh.

Câu hỏi mà module này trả lời: *tập nhãn mới này dùng được vào việc gì?* Trả lời
bằng bốn phép đo, mỗi phép nhắm một cách hỏng khác nhau, vì một tập dữ liệu có
thể tốt cho việc này mà độc hại cho việc kia:

``offset``
    ``text[start:end] == text`` cho MỌI span. Đây là điều kiện cần tuyệt đối —
    một tập có lỗi offset thì không dùng được vào bất cứ việc gì. Kiểm trước.

``span_length``
    Độ dài span trung bình theo từ, so với tham chiếu. Đây là phép đo quan
    trọng nhất cho **dữ liệu huấn luyện**: model học đúng phân phối trong nhãn,
    nên một tập lệch −1 từ sẽ dạy model cắt cụt span, và WER phạt theo từ.

``completeness``
    Tỉ lệ lần xuất hiện của một cụm ĐÃ TỪNG được gán ở đâu đó, nhưng lần này
    không được gán. Xấp xỉ tỉ lệ **âm tính giả** của việc gán nhãn.

    Đọc số này phải so với chính tham chiếu, không so với 0: cùng một chuỗi bề
    mặt xuất hiện trong ngữ cảnh không phải thực thể là chuyện bình thường, nên
    gold thật cũng có một mức nền khác 0. Chỉ phần **vượt mức nền** mới là nhãn
    thiếu thật.

``policy``
    Phân phối ``|candidates|`` và tỉ lệ gold rỗng theo type. Quyết định tập này
    có dùng được để **hiệu chuẩn ngưỡng phát mã** hay không — và câu trả lời
    thường là không, vì bộ sinh gán mã cho mọi thực thể nó trồng xuống, trong
    khi gold thật để trống phần lớn.
"""

from __future__ import annotations

import collections
import re
import statistics as st
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CorpusProfile:
    name: str
    n_files: int = 0
    n_chars: int = 0
    n_spans: int = 0
    offset_errors: int = 0
    nfd_files: int = 0
    masked_files: int = 0
    header_files: int = 0
    by_type: dict[str, int] = field(default_factory=collections.Counter)
    assertions: dict[str, int] = field(default_factory=collections.Counter)
    span_words: dict[str, list[int]] = field(
        default_factory=lambda: collections.defaultdict(list)
    )
    cand_sizes: dict[int, int] = field(default_factory=collections.Counter)
    empty_by_type: dict[str, int] = field(default_factory=collections.Counter)
    missed: int = 0
    occurrences: int = 0

    @property
    def density(self) -> float:
        """Span trên 1.000 ký tự — bất biến với độ dài tài liệu, khác span/file."""
        return 1000 * self.n_spans / self.n_chars if self.n_chars else 0.0

    @property
    def mean_span_words(self) -> float:
        allw = [w for v in self.span_words.values() for w in v]
        return st.mean(allw) if allw else 0.0

    @property
    def miss_rate(self) -> float:
        return self.missed / self.occurrences if self.occurrences else 0.0


_HEADER = re.compile(r"(?m)^[^\n]{3,40}:\s*$")
_MASK = re.compile(r"\*{3,}")


def profile(name: str, docs: list[tuple[str, str, list[dict]]]) -> CorpusProfile:
    """``docs`` = list các bộ ba ``(tên, văn bản thô, danh sách mention)``."""
    import unicodedata as ud

    p = CorpusProfile(name=name, n_files=len(docs))
    for _, text, recs in docs:
        p.n_chars += len(text)
        p.nfd_files += int(text != ud.normalize("NFC", text))
        p.masked_files += bool(_MASK.search(text))
        p.header_files += bool(_HEADER.search(text))
        for r in recs:
            p.n_spans += 1
            start, end = r["position"]
            if text[start:end] != r["text"]:
                p.offset_errors += 1
                continue
            p.by_type[r["type"]] += 1
            p.span_words[r["type"]].append(len(r["text"].split()))
            for a in r.get("assertions") or []:
                p.assertions[a] += 1
            cands = r.get("candidates") or []
            p.cand_sizes[len(cands)] += 1
            if not cands:
                p.empty_by_type[r["type"]] += 1

    # ── độ đầy đủ: quét lại từ vựng của chính tập này trên chính văn bản của nó ──
    vocab = collections.Counter()
    for _, _, recs in docs:
        for r in recs:
            vocab[r["text"].lower()] += 1
    # ngưỡng: cụm ≥ 4 ký tự và xuất hiện ≥ 2 lần — dưới mức đó thì nhiễu khớp
    # chuỗi lấn át tín hiệu (chuỗi 2-3 ký tự khớp bên trong từ khác liên tục).
    terms = [k for k, v in vocab.items() if len(k) >= 4 and v >= 2]
    for _, text, recs in docs:
        low = text.lower()
        covered = bytearray(len(text))
        for r in recs:
            for i in range(*r["position"]):
                if i < len(covered):
                    covered[i] = 1
        for term in terms:
            for m in re.finditer(re.escape(term), low):
                p.occurrences += 1
                if not any(covered[i] for i in range(m.start(), min(m.end(), len(covered)))):
                    p.missed += 1
    return p


def load_pairs(ann_dir: Path, text_dir: Path, suffix: str = ".txt") -> list[tuple[str, str, list[dict]]]:
    """Ghép thư mục nhãn với thư mục văn bản theo tên file."""
    import json

    out = []
    for a in sorted(ann_dir.glob("*.json")):
        if a.name in {"run_manifest.json", "explain.json"}:
            continue
        t = text_dir / f"{a.stem}{suffix}"
        if not t.exists():
            continue
        out.append((a.stem, t.read_text(encoding="utf-8"), json.loads(a.read_text(encoding="utf-8"))))
    return out


def compare(ref: CorpusProfile, others: list[CorpusProfile]) -> str:
    """Bảng so sánh dạng text. ``ref`` là mức nền để đọc mọi cột lệch."""
    lines: list[str] = []
    add = lines.append

    add(f"\n── tổng quan (tham chiếu: {ref.name}) ──")
    head = (f"  {'tập':<20}{'file':>6}{'span':>7}{'span/1k':>9}"
            f"{'offset':>8}{'NFD':>6}{'mask':>6}{'tiêu đề':>9}")
    add(head)
    add("  " + "─" * (len(head) - 2))
    for p in [ref, *others]:
        add(f"  {p.name:<20}{p.n_files:>6}{p.n_spans:>7}{p.density:>9.2f}"
            f"{p.offset_errors:>8}{100 * p.nfd_files / max(p.n_files, 1):>5.0f}%"
            f"{100 * p.masked_files / max(p.n_files, 1):>5.0f}%"
            f"{100 * p.header_files / max(p.n_files, 1):>8.0f}%")

    add("\n── độ dài span (từ) — cột Δ là thứ quyết định dùng làm dữ liệu TRAIN hay không ──")
    types = sorted(ref.span_words)
    head = f"  {'tập':<20}{'TB':>7}{'Δ':>7}   " + "".join(f"{t.split('_')[0][:6]:>9}" for t in types)
    add(head)
    add("  " + "─" * (len(head) - 2))
    for p in [ref, *others]:
        row = f"  {p.name:<20}{p.mean_span_words:>7.2f}"
        row += "      —" if p is ref else f"{p.mean_span_words - ref.mean_span_words:>+7.2f}"
        row += "   "
        for t in types:
            v = st.mean(p.span_words[t]) if p.span_words.get(t) else 0.0
            row += f"{v:>9.2f}"
        add(row)

    add("\n── độ đầy đủ nhãn (âm tính giả xấp xỉ) ──")
    for p in [ref, *others]:
        excess = p.miss_rate - ref.miss_rate
        note = "  ← mức nền" if p is ref else (
            f"  vượt nền {excess:+.1%}" if abs(excess) > 0.02 else "  ≈ mức nền")
        add(f"  {p.name:<20}{p.missed:>6}/{p.occurrences:<7}"
            f"{p.miss_rate:>7.1%}{note}")

    add("\n── chính sách candidates (tỉ lệ gold RỖNG theo type) ──")
    types_all = sorted({t for p in [ref, *others] for t in p.by_type})
    head = f"  {'tập':<20}" + "".join(f"{t.split('_')[0][:7]:>10}" for t in types_all)
    add(head)
    add("  " + "─" * (len(head) - 2))
    for p in [ref, *others]:
        row = f"  {p.name:<20}"
        for t in types_all:
            n = p.by_type.get(t, 0)
            row += f"{100 * p.empty_by_type.get(t, 0) / n:>9.0f}%" if n else f"{'—':>10}"
        add(row)
    add("\n  |candidates|: " + " · ".join(
        f"{p.name}={dict(sorted(p.cand_sizes.items()))}" for p in [ref, *others]))
    return "\n".join(lines)
