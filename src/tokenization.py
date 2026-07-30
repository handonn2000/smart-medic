"""Word segmentation that keeps character offsets into the original text.

Every predicted concept has to report `position` as `[start, end]` into the raw input,
and the scorer pairs a prediction with a gold concept only when their spans overlap. An
offset that is off by a few characters therefore does not lose a little credit, it loses
the concept twice — once as a prediction that matches nothing, once as a gold concept
left unmatched. So offsets are computed here, once, and every span's text is taken as a
literal slice of the input, which makes `text == raw[start:end]` true by construction
rather than by luck.

The tricky part is that the segmenter neither preserves whitespace nor reports offsets:
`word_tokenize` returns `["đau nhức"]` for text that may have held `"đau\nnhức"`. Rather
than searching for token strings in the input — which silently matches the wrong
occurrence when a word repeats, and fails outright when whitespace differs — the input
is first split into atoms (runs of word characters and single punctuation marks) whose
offsets are known, and the segmenter's tokens are then matched against that atom stream.
Whitespace never enters the comparison, and a token that the segmenter altered costs at
most one word instead of desynchronising everything after it.

Segmentation runs per line for the same reason: a desync cannot escape its line, and
line structure is what `assertions.py` reads to find section headings.
"""

import re
import unicodedata as ud

#: Dấu thanh/dấu phụ tổ hợp. `\w` KHÔNG bao gồm chúng, nên nếu không kể ra thì một âm
#: tiết NFD như "mất" bị xé thành 'ma', '◌̂', '◌́', 't' — không thể so với token NFC.
MARKS = "\u0300-\u036f"

#: Một "nguyên tử": cụm ký tự chữ/số liền nhau, hoặc một dấu đơn lẻ. Mọi ký tự trắng
#: bị bỏ ra ngoài — đó chính là thứ segmenter không giữ nguyên.
ATOM = re.compile(rf"[\w{MARKS}]+|[^\w\s{MARKS}]", re.UNICODE)

LINE = re.compile(r"[^\n]+")

#: Dấu kết câu, dùng để cắt lô cho vừa giới hạn 256 token của PhoBERT ở chỗ ít gây hại.
SENTENCE_END = frozenset(".;!?:…")


def atoms_with_offsets(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in ATOM.finditer(text)]


def align_words(text: str, tokens: list[str]) -> list[tuple[str, int, int]]:
    """Gán offset cho từng token của segmenter: [(nguyên văn, start, end)].

    `nguyên văn` là mẩu CẮT TỪ `text`, không phải chuỗi do segmenter trả về, nên nếu
    segmenter đã bỏ dấu xuống dòng bên trong một từ ghép thì cái ta giữ vẫn là bản gốc.

    So khớp theo dạng NFC: một phần dữ liệu test ở dạng NFD, mà nếu segmenter trả token
    đã chuẩn hóa sang NFC thì so sánh thô sẽ không khớp ATOM nào và cả tài liệu ra rỗng.
    Offset vẫn tính trên `text` gốc, nên chuẩn hóa chỉ dùng để so, không dùng để cắt.
    """
    atoms = atoms_with_offsets(text)
    keys = [ud.normalize("NFC", atom) for atom, _, _ in atoms]
    out: list[tuple[str, int, int]] = []
    i = 0

    for token in tokens:
        need = [ud.normalize("NFC", atom) for atom in ATOM.findall(token)]
        if not need:
            continue

        # Segmenter có thể sửa chữ (underthesea mặc định chuẩn hóa "òa" -> "oà"), khi đó
        # token không khớp atom nào. Bỏ qua tới atom khớp được để một token lệch chỉ mất
        # một từ, thay vì kéo lệch toàn bộ phần còn lại.
        skip = i
        while skip < len(atoms) and keys[skip] != need[0]:
            skip += 1
        if skip >= len(atoms):
            continue
        i = skip

        j = i
        while j - i < len(need) and j < len(atoms) and keys[j] == need[j - i]:
            j += 1

        start, end = atoms[i][1], atoms[j - 1][2]
        out.append((text[start:end], start, end))
        i = j

    return out


def segment_document(text: str, segment_line) -> list[tuple[str, int, int]]:
    """Tách cả văn bản thành từ có offset, gọi `segment_line` cho từng dòng."""
    words: list[tuple[str, int, int]] = []
    for match in LINE.finditer(text):
        line = match.group()
        if not line.strip():
            continue
        for surface, start, end in align_words(line, segment_line(line)):
            words.append((surface, match.start() + start, match.start() + end))
    return words


def chunk_words(words: list[tuple[str, int, int]], sizes: list[int], budget: int
                ) -> list[tuple[int, int]]:
    """Chia từ thành các lô liên tiếp có tổng subword <= budget: [(đầu, cuối)).

    PhoBERT chỉ nhận 256 token, còn bệnh án trong data/test dài trung bình 2.038 ký tự,
    nên cắt truncation như trước là bỏ trắng phần lớn mỗi tài liệu. Chỗ cắt lùi về ranh
    giới câu gần nhất (tối đa 25% lô) để không cắt ngang một khái niệm; không tìm được
    ranh giới thì cắt đúng ở budget.
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(words)

    while i < n:
        total, j = 0, i
        while j < n and (j == i or total + sizes[j] <= budget):
            total += sizes[j]
            j += 1

        if j < n:
            for back in range(j, max(i + 1, j - max(1, (j - i) // 4)) - 1, -1):
                if words[back - 1][0] in SENTENCE_END:
                    j = back
                    break

        spans.append((i, j))
        i = j

    return spans


def group_entities(words: list[tuple[str, int, int]], labels: list[str]
                   ) -> list[tuple[str, int, int]]:
    """Gộp nhãn BIO theo từ thành khái niệm: [(loại, start, end)].

    Một nhãn I- không có B- mở đầu vẫn được tính là mở khái niệm mới: bỏ nó là mất trắng
    span, còn giữ lại thì span chỉ hơi lệch đầu mà vẫn chồng lấn span đáp án.
    """
    out: list[tuple[str, int, int]] = []
    start = end = etype = None

    def flush():
        if etype is not None:
            out.append((etype, start, end))

    for (_, word_start, word_end), label in zip(words, labels):
        kind = label[2:] if label[:2] in ("B-", "I-") else None
        if kind is None:
            flush()
            start = end = etype = None
        elif label.startswith("I-") and etype == kind:
            end = word_end
        else:
            flush()
            start, end, etype = word_start, word_end, kind

    flush()
    return out


def _self_test() -> int:
    """`python src/tokenization.py` — chạy được không cần torch/underthesea."""
    fails = 0

    def check(ok, label):
        nonlocal fails
        fails += not ok
        print(f"  {'ok ' if ok else 'SAI'}  {label}")

    nfd = ud.normalize("NFD", "mất ngủ nhiều")
    for text, tokens, want in [
        ("đau nhức khớp", ["đau nhức", "khớp"], [(0, 8), (9, 13)]),
        ("đau\nnhức khớp", ["đau nhức", "khớp"], [(0, 8), (9, 13)]),
        ("liều 325-650 mg", ["liều", "325-650", "mg"], [(0, 4), (5, 12), (13, 15)]),
        ("thuốc **** rồi", ["thuốc", "****", "rồi"], [(0, 5), (6, 10), (11, 14)]),
        (nfd, [ud.normalize("NFD", "mất ngủ"), "nhiều"], [(0, 10), (11, 18)]),
        (nfd, ["mất ngủ", "nhiều"], [(0, 10), (11, 18)]),
        ("bệnh nhân bị hoà tan", ["bệnh nhân", "bị", "hòa", "tan"],
         [(0, 9), (10, 12), (17, 20)]),
    ]:
        spans = align_words(text, tokens)
        got = [(s, e) for _, s, e in spans]
        check(got == want and all(text[s:e] == surf for surf, s, e in spans),
              f"align_words({text!r:24}) -> {got}")

    words = [(("." if i % 10 == 9 else f"w{i}"), i, i + 1) for i in range(40)]
    spans = chunk_words(words, [1] * 40, 12)
    check(spans == [(0, 10), (10, 20), (20, 30), (30, 40)],
          f"chunk_words cắt ở hết câu -> {spans}")
    check(chunk_words([("w", 0, 1)] * 3, [99, 1, 1], 10)[0] == (0, 1),
          "chunk_words: từ dài hơn budget vẫn đứng riêng một lô")

    text = "ho khan và đau nhức và ho khan"
    words = align_words(text, ["ho", "khan", "và", "đau nhức", "và", "ho", "khan"])
    labels = ["B-TRIEU_CHUNG", "I-TRIEU_CHUNG", "O", "I-TRIEU_CHUNG", "O",
              "B-TRIEU_CHUNG", "I-BENH"]
    got = group_entities(words, labels)
    check(got == [("TRIEU_CHUNG", 0, 7), ("TRIEU_CHUNG", 11, 19),
                  ("TRIEU_CHUNG", 23, 25), ("BENH", 26, 30)],
          f"group_entities (kể cả I- lẻ, I- khác loại) -> {got}")
    check([text[s:e] for _, s, e in got] == ["ho khan", "đau nhức", "ho", "khan"],
          "mẩu cắt của từng khái niệm đúng nguyên văn")
    check(got[0][1] != got[2][1], "cùng chữ nhắc lại -> offset khác nhau")

    print("ĐẠT" if not fails else f"{fails} ca SAI")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    sys.exit(_self_test())
