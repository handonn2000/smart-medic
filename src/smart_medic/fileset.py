"""Chọn tập file theo số hiệu — một định nghĩa duy nhất cho mọi CLI.

Vì sao là module riêng chứ không để mỗi script tự parse: gold, nhãn bạc, holdout
và bước chấm điểm đều phải nói về **cùng một tập file**. Ba bản parse gần giống
nhau thì sớm muộn sẽ lệch nhau ở ca biên (khoảng ngược, trùng số, khoảng trắng),
và kiểu lệch đó không ném exception — nó chỉ làm train và chấm nhìn vào hai tập
khác nhau, rồi mọi con số so sánh sau đó đều vô nghĩa.
"""

from __future__ import annotations


def parse_file_selector(spec: str) -> tuple[int, ...]:
    """``'1,3,4'`` hoặc ``'1-100'`` hoặc trộn cả hai → tuple số hiệu file.

    Dạng khoảng tồn tại để chạy nhãn BẠC trên toàn corpus (``--files 1-100``)
    bằng ĐÚNG code đã dùng cho gold, thay vì một script song song sẽ trôi khỏi
    nhau. Nhãn bạc và nhãn gold phải đi qua cùng một đường gán vị trí, cùng một
    lớp lọc ``Span.verify`` — nếu không thì model học trên một phân phối span
    khác với phân phối được chấm.

    Thứ tự xuất hiện được giữ và số trùng bị khử → tất định (NFR3).
    """
    out: list[int] = []
    for token in spec.replace(",", " ").split():
        if "-" in token[1:]:
            lo_text, _, hi_text = token.partition("-")
            lo, hi = int(lo_text), int(hi_text)
            if lo > hi:
                raise ValueError(f"khoảng ngược: {token!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(token))
    # dedup giữ thứ tự → tất định
    return tuple(dict.fromkeys(out))
