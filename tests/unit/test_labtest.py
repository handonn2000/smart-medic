"""Tên & kết quả xét nghiệm bằng cấu trúc câu, không bằng từ điển."""

from __future__ import annotations

from smart_medic.stages.labtest import (
    TYPE_RESULT,
    TYPE_TEST,
    _is_section,
    detect,
    detect_labelled,
    detect_measured,
)
from smart_medic.stages.scoring import Entity


def types_of(ents, typ):
    return [e.text for e in ents if e.type == typ]


class TestMauA:
    """`TÊN: KẾT_QUẢ` — cách DUY NHẤT bắt được kết quả định tính."""

    def test_cap_ten_va_gia_tri(self):
        text = "đường huyết: 11.2 mmol/L"
        ents = detect_labelled(text, [])
        assert types_of(ents, TYPE_TEST) == ["đường huyết"]
        assert types_of(ents, TYPE_RESULT) == ["11.2 mmol/L"]

    def test_ket_qua_dinh_tinh(self):
        """★ Regex số-và-đơn-vị không thể chạm tới lớp này."""
        text = "X-quang ngực: tổn thương dạng kính mờ hai đáy phổi"
        ents = detect_labelled(text, [])
        assert types_of(ents, TYPE_TEST) == ["X-quang ngực"]
        assert types_of(ents, TYPE_RESULT) == ["tổn thương dạng kính mờ hai đáy phổi"]

    def test_bo_qua_tieu_de_hanh_chinh(self):
        for head in ("3. Tiền sử:", "Chẩn đoán:", "Điều trị:"):
            text = f"{head} tăng huyết áp 8 năm"
            assert detect_labelled(text, []) == [], head

    def test_bo_qua_bien_the_tieu_de(self):
        """Khớp ĐẦU CỤM, không khớp chính xác — bệnh án dùng vô số biến thể."""
        for head in ("Chẩn đoán nền:", "Điều chỉnh thuốc:", "Triệu chứng gần đây:"):
            text = f"{head} viêm phổi"
            assert detect_labelled(text, []) == [], head

    def test_khong_de_len_entity_da_co(self):
        text = "Chẩn đoán: viêm phổi"
        taken = [Entity("viêm phổi", "CHẨN_ĐOÁN", 11, 20)]
        for e in detect_labelled(text, taken):
            assert not (e.start < 20 and e.end > 11)


class TestMauB:
    """`TÊN <giá trị đo>` — không có dấu hai chấm."""

    def test_ten_lien_truoc_gia_tri(self):
        ents = detect_measured("BUN 28 mg/dL", [])
        assert types_of(ents, TYPE_TEST) == ["BUN"]
        assert types_of(ents, TYPE_RESULT) == ["28 mg/dL"]

    def test_phan_tram(self):
        ents = detect_measured("spo2 96%", [])
        assert types_of(ents, TYPE_RESULT) == ["96%"]

    def test_lui_tim_ten_dung_ranh_gioi(self):
        ents = detect_measured("Hb 9.3 g/dL, creatinine 1.4 mg/dL", [])
        assert set(types_of(ents, TYPE_TEST)) == {"Hb", "creatinine"}

    def test_ham_luong_thuoc_KHONG_phai_ket_qua(self):
        """★ `"amlodipine 5 mg"` — từ điển chỉ khớp tên hoạt chất nên `"5 mg"`
        còn trống. Không chặn thì luật đo vơ lấy nó."""
        text = "Đang dùng amlodipine 5 mg và metformin 500 mg."
        taken = [
            Entity("amlodipine", "THUỐC", 10, 20),
            Entity("metformin", "THUỐC", 28, 37),
        ]
        assert types_of(detect_measured(text, taken), TYPE_RESULT) == []


class TestIsSection:
    def test_nhan_dien_tieu_de(self):
        assert _is_section("Tiền sử")
        assert _is_section("3. Cận lâm sàng")
        assert _is_section("Chẩn đoán nền")

    def test_ten_xet_nghiem_that_khong_bi_nham(self):
        assert not _is_section("đường huyết")
        assert not _is_section("công thức máu toàn phần")
        assert not _is_section("X-quang ngực")


class TestDetect:
    def test_hai_mau_khong_chong_lan(self):
        text = "đường huyết: 11.2 mmol/L. spo2 96%"
        spans = sorted((e.start, e.end) for e in detect(text, []))
        for a, b in zip(spans, spans[1:], strict=False):
            assert a[1] <= b[0]

    def test_van_ban_khong_co_xet_nghiem(self):
        assert detect("Bệnh nhân bị viêm phổi.", []) == []

    def test_offset_tro_dung_vao_van_ban(self):
        text = "  công thức máu: tăng bạch cầu"
        for e in detect(text, []):
            assert text[e.start : e.end] == e.text
