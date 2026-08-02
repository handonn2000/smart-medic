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
"""

from __future__ import annotations

import re

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
    r"|K/u[lL]|G/[lL]|ng/m[lL]|pg/m[lL]|mg|kg|ml|mL|lần/phút)\b|%|°C)"
)

# Nhãn đứng trước dấu hai chấm. Giới hạn độ dài để không nuốt cả câu.
_LABELLED = re.compile(r"(?m)^[ \t]*(?P<name>[^:\n]{2,45}?)[ \t]*:[ \t]*(?P<value>[^\n]+)$")

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


def _free(start: int, end: int, taken: list[Entity]) -> bool:
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


def detect(text: str, taken: list[Entity]) -> list[Entity]:
    """Cả hai mẫu. Mẫu A chạy trước vì nó đặc hiệu hơn.

    Lọc entity rỗng/toàn khoảng trắng ở đây thay vì ở từng mẫu — một chỗ duy
    nhất, không thể quên. Đo được trên `100.txt`: span `[507, 508]` là một dấu
    cách, lọt ra ngoài thành entity hợp lệ.
    """
    found = detect_labelled(text, taken)
    found += detect_measured(text, taken + found)
    return [e for e in found if e.text.strip()]
