"""Đọc input không xê dịch offset — tái hiện đúng ca lỗi thật của BTC.

Mẫu `sample_output.json` có 19/19 mục lệch offset vì văn bản gốc dùng CRLF còn
file `.txt` đã bị làm phẳng. Test này khoá lại lớp lỗi đó.
"""

from __future__ import annotations

from smart_medic.stages.textio import (
    has_crlf,
    is_nfc,
    read_document,
    verify_spans,
)

# Danh sách đánh số, mỗi dòng kết thúc bằng " \r\n" — đúng hình dạng đã tái dựng
# được từ mẫu thật của BTC.
_DOC = (
    "Danh sách thuốc trước nhập viện chính xác và đầy đủ. \r\n"
    "1. amlodipine 10 mg po daily \r\n"
    "2. aspirin 81 mg po daily \r\n"
    "3. clonazepam 1.5 mg po qhs điều trị lo âu mất ngủ"
)


def _write(tmp_path, text: str):
    p = tmp_path / "1.txt"
    p.write_bytes(text.encode("utf-8"))
    return p


def _spans(text: str) -> list[tuple[int, int, str]]:
    out = []
    for mention in ("amlodipine 10 mg po daily", "aspirin 81 mg po daily", "mất ngủ"):
        i = text.index(mention)
        out.append((i, i + len(mention), mention))
    return out


class TestGiuNguyenCRLF:
    def test_doc_dung_thi_offset_khop(self, tmp_path):
        p = _write(tmp_path, _DOC)
        text = read_document(p)
        assert verify_spans(text, _spans(_DOC)) == []

    def test_read_text_lam_lech_offset(self, tmp_path):
        """★ Đây là bug thật, không phải giả định.

        `Path.read_text()` bật universal newlines: `\\r\\n` → `\\n`, ngắn đi 1 ký
        tự mỗi dòng. Span tính trên văn bản gốc trỏ sai — im lặng.
        """
        p = _write(tmp_path, _DOC)
        flattened = p.read_text(encoding="utf-8")

        assert len(flattened) < len(_DOC)
        bad = verify_spans(flattened, _spans(_DOC))
        assert bad, "read_text() phải làm lệch span — nếu không, giả định đã sai"

    def test_do_lech_tang_dan_theo_so_dong(self, tmp_path):
        """Lệch tích luỹ: dòng càng xa đầu file, sai càng nhiều."""
        p = _write(tmp_path, _DOC)
        flattened = p.read_text(encoding="utf-8")
        spans = _spans(_DOC)
        lech = [s - flattened.index(t) for s, _e, t in spans]
        assert lech == sorted(lech)
        assert lech[-1] > lech[0]

    def test_nhan_dien_duoc_crlf(self):
        assert has_crlf(_DOC)
        assert not has_crlf(_DOC.replace("\r\n", "\n"))


class TestKhongChuanHoaUnicode:
    def test_khong_tu_dong_doi_NFC_NFD(self, tmp_path):
        """Chuẩn hoá Unicode đổi ĐỘ DÀI chuỗi ⇒ đổi offset.

        Đo trên mẫu thật: cùng văn bản là 532 ký tự NFC nhưng 582 ký tự NFD.
        """
        import unicodedata

        nfd = unicodedata.normalize("NFD", _DOC)
        assert len(nfd) > len(_DOC)

        p = _write(tmp_path, nfd)
        text = read_document(p)
        assert text == nfd, "read_document không được tự chuẩn hoá"
        assert not is_nfc(text)

    def test_bao_duoc_trang_thai_nfc(self, tmp_path):
        p = _write(tmp_path, _DOC)
        assert is_nfc(read_document(p))


class TestVerifySpans:
    def test_khop_thi_rong(self):
        assert verify_spans("abcdef", [(0, 3, "abc")]) == []

    def test_lech_thi_bao_ca_mong_lan_duoc(self):
        bad = verify_spans("abcdef", [(1, 4, "abc")])
        assert bad == [(1, 4, "abc", "bcd")]
