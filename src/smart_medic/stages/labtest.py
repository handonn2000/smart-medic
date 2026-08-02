"""Tên xét nghiệm và kết quả xét nghiệm — bằng CẤU TRÚC, không bằng từ điển.

★ VÌ SAO ĐÂY LÀ VIỆC ĐÁNG LÀM NHẤT
───────────────────────────────────
Hai nhãn này có `candidates` và `assertions` **rỗng** trong đáp án. Mà Jaccard
quy ước rỗng-gặp-rỗng bằng 1,0. Nên chỉ cần **phát hiện đúng span** là ăn trọn
điểm ở cả ba thành phần — không cần tra mã, không cần suy ngữ cảnh.

Đo bằng thí nghiệm oracle (thay dự đoán của hai nhãn này bằng đáp án):

    hiện tại           final 0,4857
    nếu XN hoàn hảo    final 0,6886     ⇒ +0,203

Lớn hơn mọi hướng khác đã khảo sát, kể cả toàn bộ S1.

★ VÌ SAO KHÔNG DÙNG TỪ ĐIỂN
ICD/RxNorm/SNOMED đều yếu ở xét nghiệm — đó là địa hạt LOINC, mà LOINC không có
trong KB (PRD tab 04 §2). Chép danh sách tên xét nghiệm từ chính bộ gold đang
dùng để chấm thì phép đo thành tự khen. Nên ở đây dùng **cấu trúc câu**, thứ
tổng quát hoá được sang văn bản chưa từng thấy.

★ HAI MẪU, ĐO ĐƯỢC TRÊN GOLD
    mẫu A  "TÊN: KẾT_QUẢ"        phủ 66% tên · 56% kết quả
           `đường huyết: 11.2 mmol/L`
           `X-quang ngực: tổn thương dạng kính mờ hai đáy phổi`   ← kết quả ĐỊNH TÍNH

    mẫu B  "TÊN <giá trị đo>"    phủ phần còn lại
           `BUN 28 mg/dL` · `spo2 96%` · `creatinine 1.4 mg/dL`

Mẫu A quan trọng hơn vì nó là cách DUY NHẤT bắt được kết quả định tính — thứ
regex số-và-đơn-vị không thể chạm tới.

★ PHASE 1 — BỐN MẪU NỮA, ĐO TRƯỚC KHI VIẾT
───────────────────────────────────────────
Chẩn đoán 43 span xét nghiệm bỏ sót trên `gold_real` (36 "không ai chạm",
7 "bị chiếm sai") cho ra đúng bốn khoảng trống, không phải một mớ lỗi lặt vặt:

  C. **Nhiều cặp trên MỘT dòng.** `_LABELLED` neo `^` nên chỉ lấy cặp đầu:
         `GOT: 542 U/l; GPT: 628 U/l; GGT: 234 U/l`
                        └─ mất ─┘   └─ mất ─┘
     Sửa: cắt dòng thành đoạn theo `;` và `,` trước khi khớp. Đây là khoảng
     trống RẺ NHẤT và nhiều lượt nhất.

  D. **Kết quả KHÔNG phải số.** `_MEASURE` là regex *số + đơn vị*, nên không thể
     chạm `dương tính` · `(+)` · `(-)` · `chưa phát hiện bất thường` ·
     `nguyên vẹn` · `đang chờ` · `tăng men gan nhẹ`. Đây là gốc của
     recall 0,424 — thấp nhất trong 5 nhãn.

  E. **Tiêu đề + gạch đầu dòng.** Hai khối giống hệt nhau về hình thức nhưng
     nhãn ngược nhau — chỉ danh mục phân biệt được, xem `labcatalog.py`.

  F. **Nối bằng văn xuôi.** `siêu âm vùng gan mật … cho thấy túi mật căng to…`
     `chụp ct bụng chậu là chưa phát hiện bất thường` · `cấy máu dương tính`.
     Không có nhánh này thì `_TEST_PHRASE` nuốt cả câu thành MỘT tên xét nghiệm
     dài ngoằng — vừa mất tên vừa mất kết quả.

Cả bốn nằm sau cờ `labtest_extended` (`stages/flags.py`). Tắt cờ thì module thu
về đúng hành vi trước Phase 1 — cần thiết để Phase 5 chấm được cấu hình C0.
"""

from __future__ import annotations

import re
from bisect import bisect_right, insort

from smart_medic.stages import labcatalog
from smart_medic.stages.flags import flag
from smart_medic.stages.scoring import Entity

TYPE_TEST = "TÊN_XÉT_NGHIỆM"
TYPE_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"

# ★ Tiêu đề mục của bệnh án cũng có dạng "X:" nên mẫu A sẽ bắt nhầm chúng.
#   Đây là từ vựng hành chính của bệnh án Việt — kiến thức chung về thể loại
#   văn bản, KHÔNG phải danh sách tên xét nghiệm chép từ gold.
SECTION_WORDS: frozenset[str] = frozenset(
    {
        "lý do vào viện", "bệnh sử", "tiền sử", "tiền sử gia đình", "chẩn đoán",
        "điều trị", "khám", "khám lâm sàng", "cận lâm sàng", "tóm tắt", "kết luận",
        "diễn biến", "xử trí", "thuốc", "thuốc đang dùng", "chẩn đoán cũ",
        "chẩn đoán sơ bộ", "chẩn đoán xác định", "dặn dò", "theo dõi", "tiên lượng",
        "hướng điều trị", "đánh giá", "nhận xét", "kế hoạch",
        "điều chỉnh", "triệu chứng", "diễn tiến", "tình trạng", "lời dặn",
        # Từ vựng DIỄN NGÔN — gặp ở blog/hỏi–đáp, không có trong bệnh án mẫu.
        "câu hỏi", "câu trả lời", "trả lời", "lý do", "thời điểm", "hỏi", "đáp",
        "ghi chú", "lưu ý", "giải thích", "tư vấn", "khuyến nghị", "mô tả",
    }
)  # fmt: skip

# Giá trị đo: số kèm đơn vị. `%` và `°C` không có ranh giới `\b` nên tách nhánh.
_MEASURE = re.compile(
    r"\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:(?:mmol/[lL]|mg/d[lL]|g/d[lL]|g/[lL]|mcg/[lL]|U/[lL]|IU/[lL]|mEq/[lL]|mmHg|bpm"
    r"|K/u[lL]|G/[lL]|ng/m[lL]|pg/m[lL]|micromol/[lL]|[µu]mol/[lL]|nmol/[lL]|T/[lL]|ml/24h|[lL]/phút|kg/m2|mg|kg|ml|mL|cm|mm|lần/phút)\b|%|°C)"
)

# Nhãn đứng trước dấu hai chấm. Giới hạn độ dài để không nuốt cả câu.
#
# ★ Dòng có GẠCH ĐẦU DÒNG bị loại. Bệnh án Việt dùng gạch đầu dòng cho **trường
#   của mẫu khai thác triệu chứng** — `- Vị trí:`, `- Mức độ nghiêm trọng:`,
#   `- Tính chất:` — chứ không cho tên xét nghiệm. Tên xét nghiệm thật
#   (`đường huyết:`, `X-quang ngực:`) luôn đứng đầu dòng trần.
#   Đo trên `gold_real`: mẫu này sinh 38 entity thừa nếu không loại.
_LABELLED = re.compile(
    r"(?m)^[ \t]*(?![-•+*\u2022]\s)(?P<name>[^:\n]{2,45}?)[ \t]*:[ \t]*(?P<value>[^\n]+)$"
)

# ★ Đầu cụm chỉ TÊN XÉT NGHIỆM — cùng ý tưởng với `SYMPTOM_HEADS` ở `ner.py`.
#
# 44/118 ca bỏ sót trên `gold_real` là tên xét nghiệm KHÔNG có dấu hai chấm và
# KHÔNG kèm giá trị đo: `"xét nghiệm máu"`, `"Điện tâm đồ"`, `"Men tim"`. Hai
# mẫu cấu trúc không với tới được, nhưng chúng đều mở đầu bằng một tập từ đóng
# của tiếng Việt lâm sàng.
TEST_HEADS: tuple[str, ...] = (
    "xét nghiệm", "nghiệm pháp", "chụp", "siêu âm", "nội soi", "sinh thiết",
    "điện tâm đồ", "điện não đồ", "điện cơ", "đo", "test", "cấy", "soi",
    "công thức máu", "tổng phân tích", "định lượng", "chỉ số",
)  # fmt: skip

# Cụm tên xét nghiệm chạy tới ranh giới câu, tối đa vài từ.
_TEST_PHRASE = re.compile(r"(?i)\b(?:" + "|".join(TEST_HEADS) + r")\b[^,;.:\n()]{0,40}")

# Hết câu: dấu chấm/chấm phẩy KHÔNG nằm giữa hai chữ số.
_SENT_END = re.compile(r"(?<!\d)[.;]|[.;](?!\d)")

# Ranh giới lùi khi tìm tên cho mẫu B.
_BACK_STOP = re.compile(r"[.:;,\n]")


def _is_section(name: str) -> bool:
    """Nhãn có phải tiêu đề hành chính không.

    Khớp theo **đầu cụm**, không khớp chính xác: bệnh án dùng vô số biến thể
    (`"Chẩn đoán nền"`, `"Điều chỉnh thuốc"`, `"Triệu chứng gần đây"`). Khớp
    chính xác để lọt cả ba — đo được 11 tên xét nghiệm giả.
    """
    cleaned = re.sub(r"^\s*\d+\.\s*", "", name).strip().lower()
    return any(cleaned == w or cleaned.startswith(w + " ") for w in SECTION_WORDS)


class Occupancy:
    """Vùng đã bị chiếm — tra chồng lấn bằng `bisect`, không quét tuyến tính.

    `_free()` cũ là O(n) mỗi lần hỏi, và mỗi mẫu hỏi một lần cho mỗi lần khớp,
    nên tổng là O(n²) trên tài liệu dày entity. Phase 1 thêm bốn mẫu nữa nên bậc
    hai đó bắt đầu thấy được.

    **Bất biến dựa vào:** các khoảng bên trong KHÔNG chồng lấn nhau. Đúng theo
    kiến tạo — mọi khoảng đều đi qua `free()` trước khi `add()`, và
    `solve.check_invariants` chốt lại điều đó ở đầu ra.
    """

    __slots__ = ("_iv",)

    def __init__(self, taken: list[Entity] | None = None) -> None:
        self._iv: list[tuple[int, int]] = sorted((e.start, e.end) for e in taken or [])

    def free(self, start: int, end: int) -> bool:
        i = bisect_right(self._iv, (start, end))
        if i and self._iv[i - 1][1] > start:
            return False
        return not (i < len(self._iv) and self._iv[i][0] < end)

    def add(self, start: int, end: int) -> None:
        insort(self._iv, (start, end))

    def take(self, ent: Entity) -> None:
        self.add(ent.start, ent.end)


def _free(start: int, end: int, taken: list[Entity]) -> bool:
    """Giữ lại cho code cũ và test. Đường nóng dùng `Occupancy`."""
    return not any(start < t.end and end > t.start for t in taken)


def detect_labelled(text: str, taken: list[Entity]) -> list[Entity]:
    """Mẫu A — `TÊN: KẾT_QUẢ`.

    Bắt được cả kết quả **định tính** (`tổn thương dạng kính mờ hai đáy phổi`),
    thứ mà regex số-và-đơn-vị không thể chạm tới.
    """
    out: list[Entity] = []
    for m in _LABELLED.finditer(text):
        name = m.group("name")
        if _is_section(name):
            continue
        ns, ne = m.start("name"), m.end("name")
        vs, ve = m.start("value"), m.end("value")
        # Kết quả cắt tại dấu chấm câu đầu tiên — một dòng có thể chứa nhiều cặp.
        # ★ Dấu chấm THẬP PHÂN không phải hết câu: `"11.2 mmol/L"` bị cắt thành
        #   `"11"` nếu không loại trừ. Chỉ cắt khi sau dấu là khoảng trắng/hết.
        stop = _SENT_END.search(text[vs:ve])
        if stop:
            ve = vs + stop.start()
        if ne > ns and _free(ns, ne, taken):
            out.append(Entity(text[ns:ne], TYPE_TEST, ns, ne))
        if ve > vs and _free(vs, ve, taken + out):
            out.append(Entity(text[vs:ve], TYPE_RESULT, vs, ve))
    return out


def detect_measured(text: str, taken: list[Entity]) -> list[Entity]:
    """Mẫu B — `TÊN <giá trị đo>`, không có dấu hai chấm.

    Tên là cụm ngay trước giá trị, lùi tới ranh giới câu gần nhất.
    """
    drugs = [t for t in taken if t.type == "THUỐC"]
    out: list[Entity] = []
    for m in _MEASURE.finditer(text):
        vs, ve = m.start(), m.end()
        if not _free(vs, ve, taken + out):
            continue
        # ★ Hàm lượng thuốc KHÔNG phải kết quả xét nghiệm. `"amlodipine 5 mg"` —
        #   từ điển chỉ khớp tên hoạt chất nên `"5 mg"` còn trống, và luật đo sẽ
        #   vơ lấy nó. Đo được 11 kết quả giả kiểu này.
        if any(0 <= vs - d.end <= 2 for d in drugs):
            continue
        # Lùi tìm tên.
        left = text.rfind("\n", 0, vs) + 1
        seg = text[left:vs]
        brk = None
        for b in _BACK_STOP.finditer(seg):
            brk = b
        ns = left + (brk.end() if brk else 0)
        name = text[ns:vs].strip()
        if name and 2 <= len(name) <= 45 and not _is_section(name):
            start = ns + (len(text[ns:vs]) - len(text[ns:vs].lstrip()))
            if _free(start, start + len(name), taken + out):
                out.append(Entity(name, TYPE_TEST, start, start + len(name)))
        out.append(Entity(text[vs:ve], TYPE_RESULT, vs, ve))
    return out


def detect_test_phrases(
    text: str, taken: list[Entity], cat: labcatalog.Catalog | None = None
) -> list[Entity]:
    """Tên xét nghiệm nhận diện bằng ĐẦU CỤM, khi không có dấu hai chấm.

    Chạy SAU mọi mẫu cấu trúc: nó chỉ đòi khớp một đầu cụm nên ít ràng buộc nhất
    và dễ khoanh nhầm nhất.

    ★ Khoảng trống F. Không cắt thì cụm chạy tối đa 40 ký tự và nuốt cả câu:

        nội soi ở BV thì BS nói em có ổ loét trong bao       ← MỘT tên xét nghiệm
        └─ tên thật ─┘

        siêu âm vùng gan mật hiện tại cho thấy túi mật căng to với dịch…
        └──── tên thật ────┘             └──────── kết quả thật ───────┘

    Cắt ở dấu ngăn văn xuôi thì được **hai** span đúng thay vì **một** span sai —
    lãi kép, vì span sai vừa mất recall của cả hai vừa mất precision.
    """
    out: list[Entity] = []
    occ = Occupancy(taken)
    for m in _TEST_PHRASE.finditer(text):
        s, e = m.start(), m.end()
        result: tuple[int, int] | None = None
        if cat is not None:
            frag = text[s:e]
            cut = len(frag)
            for sep in cat.prose_separators:
                i = frag.find(sep)
                if 0 < i < cut:
                    cut = i
            stop = _PHRASE_STOP.search(frag)
            if stop and stop.start() > 0:
                cut = min(cut, stop.start())
            if cut < len(frag):
                e = s + cut
                result = _result_after(text, e, cat)
        while e > s and text[e - 1].isspace():
            e -= 1
        if e <= s or not occ.free(s, e):
            continue
        ent = Entity(text[s:e], TYPE_TEST, s, e)
        out.append(ent)
        occ.take(ent)
        if result and occ.free(*result):
            res = Entity(text[result[0] : result[1]], TYPE_RESULT, *result)
            out.append(res)
            occ.take(res)
    return out


# ══ PHASE 1 ═══════════════════════════════════════════════════════════════
# Bốn mẫu ở mục "PHASE 1" của docstring module. Tất cả sau cờ `labtest_extended`.

_BULLET_LINE = re.compile(r"^[ \t]*[-•+*•]\s")

# Tách đoạn TRONG một dòng. `;` luôn tách; `,` chỉ tách khi ngay sau là một nhãn
# mới — nếu không thì `"43,5 mmol/l"` bị xẻ đôi.
_SEG_SPLIT = re.compile(r";|,(?=[ \t]*[^,;:\n]{2,45}?:[ \t])")

# Cặp `nhãn: giá trị` bên trong MỘT đoạn (không neo `^` như `_LABELLED`).
_PAIR = re.compile(r"^[ \t]*(?P<name>[^:\n]{2,45}?)[ \t]*:[ \t]*(?P<value>\S[^\n]*?)[ \t]*$")

# Từ chức năng chấm dứt một cụm TÊN xét nghiệm. Không có chặn này thì
# `_TEST_PHRASE` nuốt cả `"nội soi ở BV thì BS nói em có ổ loét trong bao"`.
_PHRASE_STOP = re.compile(
    r"\s+(?:ở|tại|thì|mà|nói|rằng|của|cho|với|khi|nếu|do|vì|nên|và|hoặc|này|đó|em|tôi|bé)\b"
)


def _lines(text: str):
    """`(offset, chuỗi)` của từng dòng, offset TUYỆT ĐỐI trên `text` gốc."""
    pos = 0
    for line in text.split("\n"):
        yield pos, line
        pos += len(line) + 1


def _segments(text: str):
    """`(offset, đoạn, có_gạch_đầu_dòng)` — dòng cắt tiếp theo `;` và `,` trước nhãn mới.

    ★ Khoảng trống C. `_LABELLED` neo `^` nên `"GOT: 542; GPT: 628; GGT: 234"`
    chỉ cho ra một cặp và mất hai cặp sau. Đo trên `gold_real/24.txt`: riêng ba
    dòng kiểu này đã chứa 5 span bỏ sót.

    ★ GẠCH ĐẦU DÒNG: trả cờ, KHÔNG loại thẳng.
    `_LABELLED` định loại chúng bằng `(?![-•+*]\\s)`, nhưng lookahead đó **bị
    backtracking vô hiệu hoá**: `[ \\t]*` lùi một ký tự là lookahead nhìn thấy dấu
    cách chứ không thấy gạch, rồi khớp bình thường với `name` = `"- Huyết áp"`.
    Nên suốt thời gian qua mẫu A vẫn bắt dòng gạch đầu dòng — chỉ là bắt kèm cả
    dấu gạch vào tên.

    Đó là một tai nạn may mắn ở `gold_batch1` (văn phong SOAP, mọi dòng đều gạch
    đầu dòng: `- BUN: 20`) và là lỗi thật ở `gold_real` (bệnh án Việt dùng gạch
    đầu dòng cho trường khai thác triệu chứng: `- Vị trí:`, `- Tính chất:`).
    Sửa thành có chủ đích: giữ dòng gạch đầu dòng nhưng bắt nó qua một **cổng
    riêng** ở `_bulleted_pair_ok`.
    """
    for base, line in _lines(text):
        bullet = _BULLET_LINE.match(line)
        start = bullet.end() if bullet else 0
        prev = start
        for m in _SEG_SPLIT.finditer(line, start):
            yield base + prev, line[prev : m.start()], bool(bullet)
            prev = m.end()
        yield base + prev, line[prev:], bool(bullet)


def _bulleted_pair_ok(name: str, value: str, cat: labcatalog.Catalog) -> bool:
    """Dòng gạch đầu dòng `NHÃN: giá trị` có phải cặp xét nghiệm không.

    Cùng một hình thức, hai nghĩa hoàn toàn khác nhau:

        - BUN: cải thiện đến 20.6      ← cặp xét nghiệm THẬT
        - Mức độ nghiêm trọng: ngày càng nặng hơn   ← trường khai thác triệu chứng

    Cú pháp không phân biệt được. Ba dấu hiệu dưới đây thì có, và cả ba đều là
    tri thức về *nội dung* chứ không phải về *hình thức*.
    """
    return bool(
        cat.leading_test_name(name.strip())  # tên là một xét nghiệm đã biết
        or _MEASURE.match(value.strip())  # giá trị là số kèm đơn vị
        or cat.result_re.match(value.strip())  # giá trị là từ vựng kết quả
    )


def _cut_result(text: str, start: int, end: int, cat: labcatalog.Catalog) -> int:
    """Cắt kết quả trước mệnh đề diễn giải.

    Đo được: gold khoanh `"túi mật căng to với dịch quanh túi mật"` và dừng ngay
    trước `" gợi ý viêm túi mật cấp"` — phần sau là suy luận của bác sĩ, không
    phải thứ máy đo trả về.
    """
    frag = text[start:end]
    for stop in cat.result_stop_phrases:
        i = frag.find(stop)
        if i > 0:
            end = start + i
            frag = text[start:end]
    return end


def detect_pairs_in_segments(text: str, occ: Occupancy, cat: labcatalog.Catalog) -> list[Entity]:
    """Khoảng trống C — `NHÃN: giá trị`, nhiều cặp trên một dòng."""
    out: list[Entity] = []
    for base, seg, bulleted in _segments(text):
        m = _PAIR.match(seg)
        if not m or _is_section(m.group("name")):
            continue
        if bulleted and not _bulleted_pair_ok(m.group("name"), m.group("value"), cat):
            continue
        ns, ne = base + m.start("name"), base + m.end("name")
        vs, ve = base + m.start("value"), base + m.end("value")
        stop = _SENT_END.search(text[vs:ve])
        if stop:
            ve = vs + stop.start()
        ve = _cut_result(text, vs, ve, cat)  # bỏ mệnh đề diễn giải ở đuôi
        if ne > ns and occ.free(ns, ne):
            e = Entity(text[ns:ne], TYPE_TEST, ns, ne)
            out.append(e)
            occ.take(e)
        if ve > vs and occ.free(vs, ve):
            e = Entity(text[vs:ve], TYPE_RESULT, vs, ve)
            out.append(e)
            occ.take(e)
    return out


def detect_bulleted(text: str, occ: Occupancy, cat: labcatalog.Catalog) -> list[Entity]:
    """Khoảng trống E — tiêu đề xét nghiệm rồi danh sách gạch đầu dòng.

        Điện tâm đồ (ECG)          Men tim
         • ST chênh lên             • Troponin I/T ↑
           ↑ KẾT QUẢ                  ↑ TÊN XÉT NGHIỆM

    Hai khối giống hệt nhau về cú pháp. Phân biệt bằng **nội dung gạch đầu dòng
    có phải tên xét nghiệm không** — câu hỏi tra bảng, xem `labcatalog.py`.
    """
    out: list[Entity] = []
    lines = list(_lines(text))
    for i, (base, line) in enumerate(lines):
        head = re.sub(r"\s*\([^)]*\)\s*$", "", line.strip())  # bỏ "(ECG)" ở đuôi
        if ":" in line or not cat.is_test_name(head):
            continue
        # ★ Phải CÓ gạch đầu dòng theo sau mới là tiêu đề. Không có ràng buộc này
        #   thì mọi dòng trùng tên xét nghiệm đều bị nuốt làm tiêu đề, và
        #   `"Anti HBe (-)"` mất luôn phần kết quả vì tên đã bị chiếm.
        if i + 1 >= len(lines) or not _BULLET_LINE.match(lines[i + 1][1]):
            continue
        hs = base + line.index(head)
        if occ.free(hs, hs + len(head)):
            e = Entity(head, TYPE_TEST, hs, hs + len(head))
            out.append(e)
            occ.take(e)
        for nb, nline in lines[i + 1 :]:
            if not _BULLET_LINE.match(nline):
                break
            body = nline[_BULLET_LINE.match(nline).end() :]
            bs = nb + len(nline) - len(body)
            body = body.rstrip()
            name = cat.leading_test_name(body)
            if name:
                span, label = name, TYPE_TEST
            else:
                span, label = body, TYPE_RESULT
                # Đuôi diễn giải trong ngoặc không thuộc kết quả.
                span = re.sub(r"\s*\([^)]*\)\s*$", "", span).rstrip(" ↑↓→")
            if span and occ.free(bs, bs + len(span)):
                e = Entity(text[bs : bs + len(span)], label, bs, bs + len(span))
                out.append(e)
                occ.take(e)
    return out


def detect_catalog_tests(text: str, occ: Occupancy, cat: labcatalog.Catalog) -> list[Entity]:
    """Tên xét nghiệm từ danh mục, rồi kết quả đi liền sau.

    Khoảng trống D + F gộp: tên bắt bằng danh mục, còn kết quả bắt bằng **từ
    vựng định tính/xu hướng/trạng thái** hoặc **dấu ngăn văn xuôi**, hai thứ mà
    regex số-và-đơn-vị không chạm tới.
    """
    out: list[Entity] = []
    for m in _iter_catalog_hits(text, cat):
        s, e = m
        if not occ.free(s, e):
            continue
        ent = Entity(text[s:e], TYPE_TEST, s, e)
        out.append(ent)
        occ.take(ent)
        r = _result_after(text, e, cat)
        if r and occ.free(*r):
            rs, re_ = r
            res = Entity(text[rs:re_], TYPE_RESULT, rs, re_)
            out.append(res)
            occ.take(res)
    return out


def _iter_catalog_hits(text: str, cat: labcatalog.Catalog):
    """Vị trí các tên xét nghiệm trong danh mục. Viết tắt phải có ngữ cảnh."""
    for m in cat.name_re.finditer(text):
        if m.start() == 0 or not text[m.start() - 1].isalnum():
            yield m.start(), m.end()
    for m in cat.abbr_re.finditer(text):
        if m.start() and text[m.start() - 1].isalnum():
            continue
        # Dấu hiệu không thể nhầm (`:`, `(+)`, một con số), HOẶC một cụm kết quả
        # ĐẦY ĐỦ ngay sau. Không nhận từ định tính lẻ: `"Bệnh nhân K không sốt"`
        # sẽ thành xét nghiệm kali.
        after = m.end() + (len(text[m.end() :]) - len(text[m.end() :].lstrip(" \t")))
        if labcatalog.abbr_has_context(text, m.end()) or cat.result_re.match(text, after):
            yield m.start(), m.end()


def _result_after(text: str, pos: int, cat: labcatalog.Catalog) -> tuple[int, int] | None:
    """Kết quả ngay sau vị trí `pos`, qua dấu ngăn `": "`, `" "` hoặc văn xuôi.

    Bốn dấu ngăn đã đo (gold_real | gold_batch1): `": "` 10|57 · `" "` 8|85 ·
    văn xuôi 6|~19 · xuống dòng+gạch đầu dòng 2|~2.
    """
    tail = text[pos : pos + 120]
    offset = 0
    if tail[:1] == ":":
        offset = len(tail) - len(tail[1:].lstrip(" \t"))
    else:
        for sep in cat.prose_separators:
            if tail.startswith(sep):
                offset = len(sep)
                break
        else:
            stripped = tail.lstrip(" \t")
            if stripped is tail or not tail[:1].isspace():
                return None
            offset = len(tail) - len(stripped)
    m = cat.result_re.match(text, pos + offset)
    if not m or m.end() <= m.start():
        return None
    return m.start(), _cut_result(text, m.start(), m.end(), cat)


def detect(text: str, taken: list[Entity], *, extended: bool | None = None) -> list[Entity]:
    """Các lớp mẫu, ĐẶC HIỆU TRƯỚC.

    Thứ tự không tuỳ tiện: mẫu càng ràng buộc nhiều thì càng ít khả năng khoanh
    nhầm, nên được quyền lấy span trước. `_TEST_PHRASE` (chỉ cần khớp một đầu
    cụm) luôn đi cuối.

    Lọc entity rỗng/toàn khoảng trắng ở đây thay vì ở từng mẫu — một chỗ duy
    nhất, không thể quên. Đo được trên `100.txt`: span `[507, 508]` là một dấu
    cách, lọt ra ngoài thành entity hợp lệ.
    """
    if not flag("labtest_extended", override=extended):
        found = detect_labelled(text, taken)
        found += detect_measured(text, taken + found)
        found += detect_test_phrases(text, taken + found)
        return [e for e in found if e.text.strip()]

    cat = labcatalog.load_catalog()
    occ = Occupancy(taken)
    found = detect_pairs_in_segments(text, occ, cat)  # C — nhiều cặp một dòng
    found += detect_bulleted(text, occ, cat)  # E — tiêu đề + gạch đầu dòng
    found += detect_catalog_tests(text, occ, cat)  # D + F — danh mục & kết quả chữ
    found += detect_measured(text, taken + found)  # B — số + đơn vị
    found += detect_test_phrases(text, taken + found, cat)  # đầu cụm, ít ràng buộc nhất
    return [e for e in found if e.text.strip()]
