"""E6 — tên hoạt chất tiếng Việt bắc cầu qua ATC (`enrich/atc_vi.py`).

Trọng tâm là **bốn chỗ sai âm thầm**: cả bốn đều cho ra batch trông hợp lệ,
không ném exception, và chỉ lộ ra khi đã nạp vào KB rồi đo lại. Vì vậy chúng
phải bị chặn ở tầng test chứ không phải ở tầng review.
"""

from __future__ import annotations

import json

import pytest

from smart_medic.kb.enrich.atc_vi import (
    AtcVietnameseNames,
    is_level5,
    is_single_ingredient,
)

# Header thật của bảng DDD nằm ở dòng thứ 3 — hai dòng đầu là tiêu đề trình bày.
# Fixture tái tạo đúng hình dạng đó, vì bỏ qua nó là lỗi đọc file kinh điển.
DDD_HEADER = "BẢNG DDD MẪU (THEO ATC/DDD INDEX 2016),,,\n,,,\nSTT,Nhóm Thuốc,Mã ATC,Thuốc\n"

# RXNCONSO.RRF: 0 RXCUI … 11 SAB, 13 CODE, 14 STR, 16 SUPPRESS.
def _conso_line(rxcui: str, sab: str, code: str, string: str, suppress: str = "N") -> str:
    col = [""] * 18
    col[0], col[11], col[13], col[14], col[16] = rxcui, sab, code, string, suppress
    return "|".join(col) + "|\n"


@pytest.fixture
def make_source(tmp_path):
    """Dựng cặp file (ddd.csv, RXNCONSO.RRF) tối thiểu và trả về enricher."""

    def _make(rows: list[tuple[str, str]], atoms: list[tuple[str, str, str]]) -> AtcVietnameseNames:
        csv_path = tmp_path / "ddd.csv"
        body = "".join(f"{i},Nhóm,{atc},{name}\n" for i, (atc, name) in enumerate(rows, 1))
        csv_path.write_text(DDD_HEADER + body, encoding="utf-8-sig")

        rrf = tmp_path / "RXNCONSO.RRF"
        rrf.write_text(
            "".join(_conso_line(rx, sab, code, "x") for rx, sab, code in atoms), encoding="utf-8"
        )
        return AtcVietnameseNames(csv_path, rrf)

    return _make


class TestLocThuocPhoiHop:
    """Bộ lọc 1-2: tên phối hợp và ký hiệu danh mục BHYT."""

    @pytest.mark.parametrize(
        "name",
        [
            "Amoxicilin + Acid clavulanic",
            "Magie hydroxid + Nhôm oxit + Simethicon",
            "Alverin (citrat) + simethicon",
            "Paracetamol*",
            "Insulin (người)",
        ],
    )
    def test_tu_choi_ten_khong_phai_don_chat(self, name):
        assert not is_single_ingredient(name)

    @pytest.mark.parametrize("name", ["Acetazolamid", "Acid Thioctic", "Alverin citrat"])
    def test_chap_nhan_ten_don_chat(self, name):
        """`Acid Thioctic` có dấu cách nhưng vẫn là MỘT hoạt chất — không được lọc nhầm."""
        assert is_single_ingredient(name)

    def test_thuoc_phoi_hop_khong_lot_vao_batch(self, make_source):
        """Gán một mã đơn chất cho thuốc phối hợp là SAI về bản chất, không phải
        chuyện nhiễu: mention "amoxicilin + acid clavulanic" phải ra RxCUI của
        thuốc phối hợp, chứ không phải của amoxicilin."""
        e = make_source(
            [("J01CA04", "Amoxicilin"), ("J01CR02", "Amoxicilin + Acid clavulanic")],
            [("723", "ATC", "J01CA04"), ("19711", "ATC", "J01CR02")],
        )
        batch = e.enrich({"rxnorm": {"723", "19711"}})
        assert [t["term"] for t in batch.terms] == ["Amoxicilin"]


class TestChiNhanMaCap5:
    """Bộ lọc 3 — chỗ dễ bỏ sót nhất, và hỏng hoàn toàn im lặng."""

    @pytest.mark.parametrize("code", ["A10BF01", "S01EC01", "V03AB23"])
    def test_ma_7_ky_tu_la_hoat_chat(self, code):
        assert is_level5(code)

    @pytest.mark.parametrize("code", ["A", "A10", "A10B", "A10BF", "A10BF011"])
    def test_ma_ngan_hon_la_ten_NHOM(self, code):
        assert not is_level5(code)

    def test_ma_nhom_bi_loai_khoi_batch(self, make_source):
        """RxNorm CÓ atom ATC cho cả mã nhóm. Không lọc thì tên một hoạt chất cụ
        thể bị gắn thẳng vào concept nhóm — không exception nào nổ ra."""
        e = make_source(
            [("A10BF01", "Acarbose"), ("A10B", "Thuốc hạ đường huyết uống")],
            [("16681", "ATC", "A10BF01"), ("99999", "ATC", "A10B")],
        )
        batch = e.enrich({"rxnorm": {"16681", "99999"}})
        assert [t["term"] for t in batch.terms] == ["Acarbose"]


class TestAnhXaVaEvidence:
    def test_anh_xa_ten_vi_sang_rxcui(self, make_source):
        e = make_source(
            [("S01EC01", "Acetazolamid")],
            [("167", "ATC", "S01EC01")],
        )
        batch = e.enrich({"rxnorm": {"167"}})
        assert len(batch.terms) == 1
        t = batch.terms[0]
        assert (t["code"], t["term"], t["lang"]) == ("167", "Acetazolamid", "vi")

    def test_evidence_dung_dang_va_giu_ma_atc(self, make_source):
        """`derived` bắt buộc có evidence (§P3.3 quy tắc 3). Giữ mã ATC để truy
        ngược được từ một term bất kỳ về đúng dòng nguồn."""
        e = make_source([("S01EC01", "Acetazolamid")], [("167", "ATC", "S01EC01")])
        batch = e.enrich({"rxnorm": {"167"}})
        assert json.loads(batch.terms[0]["evidence"]) == {"via": "atc", "atc": "S01EC01"}

    def test_khong_sinh_tier_authoritative(self, make_source):
        """Luật §P3.3: `DELETE FROM terms WHERE tier != 'authoritative'` phải đưa
        KB về đúng trạng thái Phase 2, nên mọi dòng ở đây phải gỡ được."""
        e = make_source([("S01EC01", "Acetazolamid")], [("167", "ATC", "S01EC01")])
        batch = e.enrich({"rxnorm": {"167"}})
        assert batch.terms
        assert {t["tier"] for t in batch.terms} == {"derived"}

    def test_bo_qua_atom_da_bi_rut(self, make_source, tmp_path):
        """`SUPPRESS != 'N'` là atom RxNorm đã rút; dùng nó là gắn tên vào concept
        mà chính RxNorm không còn công nhận."""
        csv_path = tmp_path / "ddd.csv"
        csv_path.write_text(DDD_HEADER + "1,Nhóm,S01EC01,Acetazolamid\n", encoding="utf-8-sig")
        rrf = tmp_path / "RXNCONSO.RRF"
        rrf.write_text(_conso_line("167", "ATC", "S01EC01", "x", suppress="O"), encoding="utf-8")
        batch = AtcVietnameseNames(csv_path, rrf).enrich({"rxnorm": {"167"}})
        assert batch.terms == []

    def test_bo_qua_sab_khac_atc(self, make_source):
        """Cột CODE của SAB khác mang mã của hệ khác — trùng độ dài 7 là ngẫu nhiên."""
        e = make_source([("S01EC01", "Acetazolamid")], [("167", "SNOMEDCT_US", "S01EC01")])
        assert e.enrich({"rxnorm": {"167"}}).terms == []

    def test_ma_ngoai_KB_bi_bo_va_duoc_bao_cao(self, make_source):
        """Bỏ qua CÓ BÁO CÁO — đây là tín hiệu bản RxNorm đã lệch so với bảng DDD."""
        e = make_source(
            [("S01EC01", "Acetazolamid"), ("A10BF01", "Acarbose")],
            [("167", "ATC", "S01EC01"), ("16681", "ATC", "A10BF01")],
        )
        batch = e.enrich({"rxnorm": {"167"}})
        assert [t["term"] for t in batch.terms] == ["Acetazolamid"]
        assert e.skipped == [("rxnorm", "A10BF01")]

    def test_khong_dung_toi_concept_nao(self, make_source):
        """Enricher chỉ THÊM dòng `terms`; không sửa `concepts` (kể cả `pref_vi`)."""
        e = make_source([("S01EC01", "Acetazolamid")], [("167", "ATC", "S01EC01")])
        batch = e.enrich({"rxnorm": {"167"}})
        assert batch.relations == [] and batch.attributes == []

    def test_kb_rong_thi_khong_doc_file_nao(self, tmp_path):
        """Không có concept RxNorm thì đừng quét file 131 MB."""
        e = AtcVietnameseNames(tmp_path / "khong-ton-tai.csv", tmp_path / "khong-ton-tai.rrf")
        assert e.enrich({"icd10": {"A00"}}).terms == []


class TestDocBangDDD:
    def test_header_o_dong_thu_3(self, make_source):
        """Đọc thẳng bằng `DictReader` sẽ lấy nhầm dòng tiêu đề làm tên cột và mọi
        lần tra cột đều trả None — batch rỗng mà không có lỗi nào."""
        e = make_source([("S01EC01", "Acetazolamid")], [("167", "ATC", "S01EC01")])
        assert e._vietnamese_names() == {"S01EC01": ["Acetazolamid"]}

    def test_gop_nhieu_bien_the_ten_tren_cung_ma(self, make_source):
        e = make_source(
            [("S01EC01", "Acetazolamid"), ("S01EC01", "Acetazolamide"), ("S01EC01", "Acetazolamid")],
            [("167", "ATC", "S01EC01")],
        )
        assert e._vietnamese_names() == {"S01EC01": ["Acetazolamid", "Acetazolamide"]}
