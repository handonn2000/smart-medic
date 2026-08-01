"""ConText/NegEx tiếng Việt — phạm vi, ưu tiên, và mặc định rỗng."""

from __future__ import annotations

from smart_medic.stages.assertion import (
    FAMILY,
    HISTORICAL,
    NEGATED,
    assign,
    find_scopes,
)
from smart_medic.stages.scoring import Entity


def ent(text: str, start: int, typ: str = "CHẨN_ĐOÁN") -> Entity:
    return Entity(text=text, type=typ, start=start, end=start + len(text))


def run(text: str, mention: str, typ: str = "CHẨN_ĐOÁN") -> tuple[str, ...]:
    i = text.index(mention)
    return assign(text, [ent(mention, i, typ)])[0].assertions


class TestMacDinhRong:
    """★ Jaccard cho rỗng-gặp-rỗng bằng 1,0 — bật cờ sai đắt hơn không bật."""

    def test_khong_co_tu_khoa_thi_rong(self):
        assert run("Bệnh nhân bị viêm phổi nặng.", "viêm phổi") == ()

    def test_nhan_khong_duoc_mang_assertion_thi_rong(self):
        text = "Tiền sử: công thức máu bất thường"
        assert run(text, "công thức máu", "TÊN_XÉT_NGHIỆM") == ()

    def test_khong_co_entity_thi_khong_no(self):
        assert assign("Tiền sử tăng huyết áp.", []) == []


class TestPhuDinh:
    def test_phu_dinh_don_gian(self):
        assert run("Không đau ngực.", "đau ngực", "TRIỆU_CHỨNG") == (NEGATED,)

    def test_liet_ke_moi_ve_co_tu_phu_dinh_rieng(self):
        text = "Không đau ngực, không chóng mặt."
        assert run(text, "đau ngực", "TRIỆU_CHỨNG") == (NEGATED,)
        assert run(text, "chóng mặt", "TRIỆU_CHỨNG") == (NEGATED,)

    def test_dau_phay_cat_pham_vi_phu_dinh(self):
        """`nghi nhồi máu não` KHÔNG bị phủ định dù đứng sau `không thấy`."""
        text = "chụp CT: không thấy xuất huyết nội sọ, nghi nhồi máu não giai đoạn sớm."
        assert run(text, "nhồi máu não") == ()

    def test_lien_tu_nguyen_nhan_cat_pham_vi(self):
        text = "Không dùng tramadol vì có thể hạ ngưỡng co giật."
        assert run(text, "co giật", "TRIỆU_CHỨNG") == ()

    def test_tranh_la_phu_dinh(self):
        assert run("Tránh ibuprofen và NSAID.", "ibuprofen", "THUỐC") == (NEGATED,)

    def test_pseudo_negation_di_ung(self):
        """★ `"Không dị ứng aspirin"` phủ định TÌNH TRẠNG DỊ ỨNG, không phủ định
        thuốc — thuốc vẫn được dùng. Đúng khái niệm pseudo-negation của NegEx."""
        assert run("Không dị ứng aspirin; dự phòng mạch vành.", "aspirin", "THUỐC") == ()

    def test_chi_nhin_xuoi(self):
        """ConText không nhìn ngược — khái niệm TRƯỚC từ khoá không bị ảnh hưởng."""
        assert run("viêm phổi đã khỏi, không sốt.", "viêm phổi") == ()


class TestTienSu:
    def test_tien_su_trong_dong(self):
        text = "Tiền sử suy tim, tăng huyết áp, rung nhĩ.\nKhám: mạch không đều"
        for m in ("suy tim", "tăng huyết áp", "rung nhĩ"):
            assert run(text, m) == (HISTORICAL,), m

    def test_khong_tran_sang_dong_sau(self):
        text = "Tiền sử suy tim.\nviêm phổi mới phát hiện"
        assert run(text, "viêm phổi") == ()

    def test_tieu_de_muc_trai_xuong_dong_duoi(self):
        """`3. Tiền sử:` là tiêu đề — nội dung nằm ở các dòng SAU."""
        text = "2. Bệnh sử:\nsốt cao\n\n3. Tiền sử:\ntăng huyết áp 8 năm\n\n4. Khám:\nviêm phổi"
        assert run(text, "tăng huyết áp") == (HISTORICAL,)
        assert run(text, "viêm phổi") == ()

    def test_khi_can_khong_cat_pham_vi(self):
        """`"khi cần"` là cách viết PRN — đưa `khi` vào ranh giới làm mất 3 ca."""
        text = "Thuốc đang dùng: salbutamol khi cần, montelukast 5 mg tối."
        assert run(text, "montelukast", "THUỐC") == (HISTORICAL,)

    def test_nghi_cat_pham_vi_tien_su(self):
        """Bệnh NGHI NGỜ không phải tiền sử."""
        text = "Tiền sử viêm dạ dày, nghi bệnh trào ngược dạ dày."
        assert run(text, "bệnh trào ngược dạ dày") == ()


class TestNguoiNha:
    def test_tien_su_gia_dinh(self):
        text = "Tiền sử gia đình: mẹ mắc đái tháo đường type 2.\nTriệu chứng: ho"
        assert run(text, "đái tháo đường type 2") == (FAMILY,)

    def test_gia_dinh_thang_tien_su(self):
        """`"Tiền sử gia đình"` phải thắng `"Tiền sử"` — từ khoá dài thắng."""
        text = "Tiền sử gia đình: anh trai bị gút."
        assert run(text, "gút") == (FAMILY,)

    def test_lien_tu_nguyen_nhan_KHONG_cat_pham_vi_gia_dinh(self):
        """★ Phạm vi người nhà rộng hơn phạm vi phủ định.

        `"bố mất vì nhồi máu cơ tim"` — cắt ở `vì` làm mất ca này.
        """
        text = "Tiền sử gia đình: bố mất vì nhồi máu cơ tim năm 55 tuổi."
        assert run(text, "nhồi máu cơ tim") == (FAMILY,)


class TestUuTien:
    def test_phu_dinh_thang_gia_dinh(self):
        """Gold ghi `isNegated`, không phải `isFamily`."""
        text = "Tiền sử gia đình: không ai mắc viêm khớp dạng thấp."
        assert run(text, "viêm khớp dạng thấp") == (NEGATED,)

    def test_chi_tra_ve_mot_co(self):
        text = "Tiền sử gia đình: mẹ mắc đái tháo đường."
        assert len(run(text, "đái tháo đường")) <= 1


class TestFindScopes:
    def test_pham_vi_bat_dau_sau_tu_khoa(self):
        text = "Tiền sử suy tim."
        s = [x for x in find_scopes(text) if x.label == HISTORICAL][0]
        assert s.start >= text.index("suy tim") - 1

    def test_van_ban_rong(self):
        assert find_scopes("") == []
