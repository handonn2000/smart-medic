"""Chuẩn hóa mã ứng viên về đúng bộ mã mà KB đang dùng.

Vì sao tầng này tồn tại: ``candidates`` chiếm **trọng số 0.4** và được chấm bằng
Jaccard, nên một mã sai chính tả hay sai phiên bản không bị trừ một phần — nó
cho **0 điểm nguyên mention**. Trước đây đường ingest chỉ ép kiểu string, không
hề kiểm mã có tồn tại; hai lớp lỗi sau đã xảy ra thật khi dựng gold dev:

* **ICD-10-CM (Mỹ) lẫn vào ICD-10 WHO.** 8/136 mã do LLM trả về không có trong
  KB vì chúng đặc hiệu hơn một bậc so với danh mục WHO/Việt Nam đang dùng:
  ``G47.33``, ``I25.10``, ``I25.41``, ``I48.91``, ``K05.9``, ``K20.9``,
  ``L03.90``, ``R56.9``. Cắt bớt hậu tố thì cả 8 đều có mặt.
* **RXCUI đã hết hiệu lực.** RxNorm có 22.330 mã đã remap và 7.939 mã bị xóa
  hẳn, nên mã do LLM nhớ từ một bản cũ là chuyện thường.

Hai phép sửa dưới đây đều **tất định và truy vết được**: cắt hậu tố chỉ đi từ mã
đặc hiệu về mã cha có thật trong KB, còn remap RxNorm đọc thẳng bảng
``RXNCUI.RRF`` của chính bản RxNorm đang dùng. Mã nào không cứu được thì **loại
bỏ và báo cáo**, không đoán bừa — với Jaccard, một mã sai và không có mã đều
cho 0, nhưng mã sai còn làm hỏng cả việc chẩn đoán lỗi về sau.

BIẾT TRƯỚC GIỚI HẠN, đo trên chính bảng trong repo:

* Bảng remap chỉ cứu được một phần: **13.528/22.330 (60,6%) mã đích của remap
  bản thân chúng cũng không có trong ``rxnorm_concepts``** (đã obsolete hoặc bị
  lọc ``SUPPRESS``). Chuỗi kế thừa cụt giữa chừng là trường hợp phổ biến, không
  phải ngoại lệ — nên nhánh "remap không dẫn tới đâu → loại bỏ" chạy thường
  xuyên chứ không phải nhánh chết.
* Có mã hỏng mà bảng **không hề biết**: ``727`` (nhôm hydroxid, retire 04/2005,
  mã đúng là ``612``) KHÔNG có trong ``RXNCUI.RRF`` của bản này — nó được phát
  hiện nhờ tra RxNav *bên ngoài*. Tầng này chỉ loại được nó, không sửa được.
  Muốn sửa thì phải gọi mạng, mà điều đó vi phạm NFR1 nên **cố ý không làm**.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Mã ICD ngắn nhất còn có nghĩa là 3 ký tự (``A82``); đừng cắt xuống dưới mức đó.
ICD_MIN_LEN = 3

#: Chặn vòng lặp khi bảng remap RxNorm có chu trình (đã thấy chuỗi kế thừa dài).
RX_REMAP_MAX_HOPS = 8


@dataclass(frozen=True)
class CodeFix:
    """Một lần sửa mã, đủ thông tin để người đọc log dựng lại lý do."""

    original: str
    result: str | None
    reason: str

    def __str__(self) -> str:
        arrow = self.result if self.result is not None else "LOẠI BỎ"
        return f"{self.original} → {arrow} ({self.reason})"


def normalize_icd(code: str, concepts) -> CodeFix:
    """Đưa mã ICD về mã có thật trong KB bằng cách cắt dần hậu tố.

    Chỉ đi một chiều: từ đặc hiệu về tổng quát. Không bao giờ *thêm* độ đặc hiệu
    — đoán ``.9`` là việc của tầng quyết định, có bằng chứng riêng, không phải
    việc của tầng chuẩn hóa này.
    """
    cleaned = code.strip().upper().replace(" ", "")
    if not cleaned:
        return CodeFix(code, None, "rỗng")
    if cleaned in concepts:
        reason = "khớp KB" if cleaned == code else "chuẩn hóa hoa/khoảng trắng"
        return CodeFix(code, cleaned, reason)

    candidate = cleaned
    while len(candidate) > ICD_MIN_LEN:
        candidate = candidate[:-1].rstrip(".")
        if candidate in concepts:
            return CodeFix(code, candidate, "cắt hậu tố về mã WHO có trong KB")
    return CodeFix(code, None, "không có trong KB kể cả sau khi cắt hậu tố")


def normalize_rxcui(code: str, rx_concepts, remap) -> CodeFix:
    """Đưa RXCUI về mã còn hiệu lực, đi theo bảng remap nếu cần."""
    cleaned = code.strip()
    if not cleaned:
        return CodeFix(code, None, "rỗng")
    if not rx_concepts:
        # KB nạp không kèm RxNorm — không có cơ sở để phán, giữ nguyên.
        return CodeFix(code, cleaned, "KB không có nhánh RxNorm, bỏ qua kiểm tra")
    if cleaned in rx_concepts:
        return CodeFix(code, cleaned, "khớp KB")

    seen = {cleaned}
    current = cleaned
    for _ in range(RX_REMAP_MAX_HOPS):
        nxt = remap.get(current)
        if nxt is None or nxt in seen:
            break
        seen.add(nxt)
        current = nxt
        if current in rx_concepts:
            return CodeFix(code, current, "theo bảng remap RxNorm về mã còn hiệu lực")
    return CodeFix(code, None, "không có trong KB và remap không dẫn tới mã còn hiệu lực")


def normalize_candidates(values, type_name: str, kb) -> tuple[list[str], list[CodeFix]]:
    """Chuẩn hóa cả danh sách ``candidates`` của một mention.

    Trả về ``(mã đã sạch, các lần sửa đáng kể)``. "Đáng kể" nghĩa là mã đã đổi
    hoặc bị loại — mã khớp KB ngay từ đầu không sinh log, nếu không log sẽ ngập
    và không ai đọc.
    """
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return [], []

    out: list[str] = []
    fixes: list[CodeFix] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        if type_name == "CHẨN_ĐOÁN":
            fix = normalize_icd(raw, kb.icd_concepts)
        elif type_name == "THUỐC":
            fix = normalize_rxcui(raw, kb.rx_concepts, kb.rx_remap)
        else:
            # Ba type còn lại không được mang mã; type-gate ở tầng trên lo việc
            # xóa, ở đây không tự ý đoán bộ mã nào.
            continue
        if fix.result != raw:
            fixes.append(fix)
        if fix.result is not None and fix.result not in out:
            out.append(fix.result)
    return out, fixes
