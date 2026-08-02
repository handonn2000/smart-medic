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


class TestKhongSinhEntityRong:
    def test_loc_entity_toan_khoang_trang(self):
        """★ Bug thật trên `100.txt`: span [507,508] là một dấu cách."""
        for e in detect("Ghi chú:  \nHb 9.3 g/dL", []):
            assert e.text.strip(), repr(e.text)

    def test_tu_vung_dien_ngon_bi_chan(self):
        """Blog/hỏi–đáp dùng tiêu đề mà bệnh án không có."""
        for head in ("Câu trả lời của bác sĩ:", "Lý do nhập viện:", "Thời điểm khởi phát:"):
            assert detect_labelled(f"{head} đau bụng 3 ngày", []) == [], head


class TestGachDauDong:
    """★ Bệnh án Việt dùng gạch đầu dòng cho TRƯỜNG CỦA MẪU khai thác triệu
    chứng, không cho tên xét nghiệm. Đo trên `gold_real`: 38 entity thừa."""

    def test_truong_cua_mau_bi_loai(self):
        for line in ("- Vị trí: Vùng hạ sườn phải", "- Mức độ nghiêm trọng: nặng hơn"):
            assert detect_labelled(line, []) == [], line

    def test_ten_xet_nghiem_that_van_duoc_giu(self):
        """Tên xét nghiệm thật đứng đầu dòng TRẦN, không có gạch."""
        ents = detect_labelled("đường huyết: 11.2 mmol/L", [])
        assert types_of(ents, TYPE_TEST) == ["đường huyết"]


class TestDauCumXetNghiem:
    """44/118 ca bỏ sót là tên xét nghiệm không có dấu hai chấm, không kèm số."""

    def test_bat_duoc_cum_khong_co_dau_hai_cham(self):
        from smart_medic.stages.labtest import detect_test_phrases

        for phrase in ("xét nghiệm máu", "Điện tâm đồ", "siêu âm ổ bụng"):
            got = detect_test_phrases(phrase, [])
            assert got and got[0].type == TYPE_TEST, phrase

    def test_khong_cuop_span_da_co(self):
        from smart_medic.stages.labtest import detect_test_phrases

        taken = [Entity("xét nghiệm máu", TYPE_TEST, 0, 14)]
        assert detect_test_phrases("xét nghiệm máu", taken) == []

    def test_dung_o_ranh_gioi_cau(self):
        from smart_medic.stages.labtest import detect_test_phrases

        got = detect_test_phrases("siêu âm ổ bụng, sau đó bệnh nhân về nhà", [])
        assert got[0].text == "siêu âm ổ bụng"


# ══ PHASE 1 ═══════════════════════════════════════════════════════════════


class TestOccupancy:
    """`bisect` thay quét tuyến tính. Phải cho KẾT QUẢ Y HỆT `_free`."""

    def test_dong_y_voi_free_tren_moi_to_hop(self):
        from smart_medic.stages.labtest import Occupancy, _free

        taken = [Entity("a", TYPE_TEST, 10, 20), Entity("b", TYPE_TEST, 30, 40)]
        occ = Occupancy(taken)
        for s in range(0, 50):
            for e in range(s + 1, min(s + 15, 51)):
                assert occ.free(s, e) == _free(s, e, taken), (s, e)

    def test_add_roi_thi_khong_con_tu_do(self):
        from smart_medic.stages.labtest import Occupancy

        occ = Occupancy([])
        assert occ.free(5, 10)
        occ.add(5, 10)
        assert not occ.free(5, 10)
        assert not occ.free(9, 12), "chạm đuôi vẫn là chồng lấn"
        assert occ.free(10, 15), "kề nhau KHÔNG phải chồng lấn"

    def test_rong(self):
        from smart_medic.stages.labtest import Occupancy

        assert Occupancy().free(0, 100)


class TestKhoangTrongC:
    """Nhiều cặp `NHÃN: giá trị` trên MỘT dòng — `_LABELLED` neo `^` nên mất hết
    trừ cặp đầu. Đo trên `gold_real/24.txt`: 5 span bỏ sót chỉ vì chuyện này."""

    def test_ba_cap_ngan_bang_cham_phay(self):
        text = "GOT: 542 U/l; GPT: 628 U/l; GGT: 234 U/l"
        ents = detect(text, [], extended=True)
        assert types_of(ents, TYPE_TEST) == ["GOT", "GPT", "GGT"]
        assert types_of(ents, TYPE_RESULT) == ["542 U/l", "628 U/l", "234 U/l"]

    def test_mau_cu_chi_lay_duoc_cap_dau(self):
        """Đối chứng: tắt cờ thì đúng hành vi trước Phase 1."""
        text = "GOT: 542 U/l; GPT: 628 U/l; GGT: 234 U/l"
        assert types_of(detect(text, [], extended=False), TYPE_TEST) == ["GOT"]

    def test_dau_phay_thap_phan_khong_bi_xe(self):
        """`,` chỉ tách khi ngay sau là nhãn mới — nếu không thì `43,5` vỡ đôi."""
        ents = detect("Ure: 5,9 mmol/l", [], extended=True)
        assert types_of(ents, TYPE_RESULT) == ["5,9 mmol/l"]

    def test_dau_phay_truoc_nhan_moi_thi_tach(self):
        ents = detect("Mạch: 89 lần/phút, HA: 180/100 mmHg", [], extended=True)
        assert "HA" in types_of(ents, TYPE_TEST)


class TestKhoangTrongD:
    """Kết quả KHÔNG phải số — gốc của recall 0,424, thấp nhất trong 5 nhãn."""

    def test_dinh_tinh(self):
        ents = detect("HBsAg: dương tính", [], extended=True)
        assert types_of(ents, TYPE_RESULT) == ["dương tính"]

    def test_ky_hieu_cong_tru(self):
        ents = detect("Anti HBe (-)", [], extended=True)
        assert types_of(ents, TYPE_TEST) == ["Anti HBe"]
        assert types_of(ents, TYPE_RESULT) == ["(-)"]

    def test_mo_ta_binh_thuong(self):
        ents = detect("Siêu âm tim: chưa phát hiện bất thường", [], extended=True)
        assert types_of(ents, TYPE_RESULT) == ["chưa phát hiện bất thường"]

    def test_trang_thai_cho_ket_qua(self):
        ents = detect("INR: đang chờ", [], extended=True)
        assert types_of(ents, TYPE_RESULT) == ["đang chờ"]

    def test_mau_cu_khong_cham_toi_duoc(self):
        """Đối chứng: `_MEASURE` là regex số+đơn vị, không có cửa nào bắt được."""
        from smart_medic.stages.labtest import detect_measured

        assert detect_measured("cấy máu dương tính", []) == []


class TestKhoangTrongE:
    """Tiêu đề + gạch đầu dòng. Hai khối GIỐNG HỆT nhau về cú pháp, nhãn ngược
    nhau — chỉ danh mục phân biệt được."""

    def test_bullet_la_ket_qua_khi_khong_phai_ten_xet_nghiem(self):
        text = "Điện tâm đồ (ECG)\n • ST chênh lên / chênh xuống\n • Sóng T đảo"
        ents = detect(text, [], extended=True)
        assert "Điện tâm đồ" in types_of(ents, TYPE_TEST)
        assert types_of(ents, TYPE_RESULT) == ["ST chênh lên / chênh xuống", "Sóng T đảo"]

    def test_bullet_la_TEN_khi_no_la_mot_xet_nghiem(self):
        text = "Men tim\n • Troponin I/T ↑ (chẩn đoán nhồi máu)\n • CK-MB ↑"
        names = types_of(detect(text, [], extended=True), TYPE_TEST)
        assert names == ["Men tim", "Troponin I/T", "CK-MB"]

    def test_truong_cua_mau_trieu_chung_van_bi_loai(self):
        """★ Không được kéo theo trường khai thác triệu chứng — đo được 38 thừa."""
        text = "Đặc điểm triệu chứng\n - Vị trí: Vùng hạ sườn phải\n - Tính chất: liên tục"
        assert detect(text, [], extended=True) == []

    def test_bullet_co_nhan_va_gia_tri_do_van_duoc_giu(self):
        """Văn phong SOAP để mọi thứ sau gạch đầu dòng — cổng `_bulleted_pair_ok`."""
        ents = detect("   - BUN: 20 mg/dL", [], extended=True)
        assert types_of(ents, TYPE_TEST) == ["BUN"]


class TestKhoangTrongF:
    """Dấu ngăn văn xuôi. Không cắt thì MỘT span sai thay vì HAI span đúng."""

    def test_cat_o_cho_thay(self):
        text = "siêu âm vùng gan mật cho thấy túi mật căng to"
        ents = detect(text, [], extended=True)
        assert "siêu âm vùng gan mật" in types_of(ents, TYPE_TEST)

    def test_khong_nuot_ca_cau_qua_tu_chuc_nang(self):
        """★ Ca thật ở `gold_real/7.txt` — cụm 40 ký tự nuốt trọn mệnh đề."""
        text = "nội soi ở BV thì BS nói em có ổ loét trong bao tử"
        names = types_of(detect(text, [], extended=True), TYPE_TEST)
        assert names == ["nội soi"], names

    def test_cat_ket_qua_truoc_menh_de_dien_giai(self):
        """Gold dừng trước `" gợi ý …"` — đó là suy luận, không phải kết quả."""
        text = "Siêu âm tim: túi mật căng to gợi ý viêm túi mật cấp"
        res = types_of(detect(text, [], extended=True), TYPE_RESULT)
        assert res and "gợi ý" not in res[0]


class TestVietTatPhaiCoNguCanh:
    """`N`, `HA`, `SA`, `TC` khớp trần thì bắn khắp nơi."""

    def test_viet_tat_co_gia_tri_di_kem_thi_duoc(self):
        assert types_of(detect("N 51,4%", [], extended=True), TYPE_TEST) == ["N"]

    def test_viet_tat_tran_thi_bi_bo_qua(self):
        """`"K"` trong câu văn thường không phải kali."""
        assert detect("Bệnh nhân K không sốt", [], extended=True) == []

    def test_phan_biet_hoa_thuong(self):
        """`"ca"` trong `"ca bệnh"` không phải canxi."""
        assert detect("ca bệnh nặng", [], extended=True) == []


class TestCoLabtestExtended:
    def test_tat_co_thi_ve_dung_hanh_vi_cu(self):
        text = "GOT: 542 U/l; GPT: 628 U/l"
        assert len(detect(text, [], extended=False)) < len(detect(text, [], extended=True))

    def test_offset_van_dung_khi_bat_co(self):
        text = "Cận lâm sàng\nGOT: 542 U/l; GPT: 628 U/l\nHBsAg (+)"
        for e in detect(text, [], extended=True):
            assert text[e.start : e.end] == e.text, e

    def test_khong_chong_lan_khi_bat_co(self):
        text = "Điện tâm đồ (ECG)\n • Sóng T đảo\nGOT: 542 U/l; GPT: 628 U/l\nHBsAg (+)"
        spans = sorted((e.start, e.end) for e in detect(text, [], extended=True))
        for a, b in zip(spans, spans[1:], strict=False):
            assert a[1] <= b[0], (a, b)
