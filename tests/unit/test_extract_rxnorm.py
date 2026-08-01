"""Bộ lọc của extractor RxNorm, chạy trên RRF giả — nhanh, không cần 1,2 GB thật.

Ba bất biến được kiểm ở đây đều là loại "sai thì không có triệu chứng":
suppress lọt lưới, chiều quan hệ bị lật, và atom mồ côi.
"""

from __future__ import annotations

import pytest

from smart_medic.kb.extract.rxnorm_rrf import ALLOWED_RELA, RxNormExtractor

# RXNCONSO có 18 trường; dựng bằng code thay vì đếm tay dấu `|` — đếm tay
# đúng là cách làm hỏng fixture mà không ai nhận ra.
_CONSO_FIELDS = 18


def _conso(rxcui: str, sab: str, tty: str, text: str, suppress: str = "N") -> str:
    row = [""] * _CONSO_FIELDS
    row[0] = rxcui  # rxcui
    row[1] = "ENG"  # lat
    row[11] = sab
    row[12] = tty
    row[13] = rxcui  # code
    row[14] = text  # str
    row[16] = suppress
    return "|".join(row) + "|"


CONSO = (
    "\n".join(
        [
            _conso("1191", "RXNORM", "IN", "aspirin"),
            _conso("243670", "RXNORM", "SCD", "aspirin 81 MG Oral Tablet"),
            _conso("243670", "RXNORM", "SY", "ASA 81 MG Oral Tablet"),
            _conso("243670", "GS", "CD", "Aspirin 81mg Oral tablet"),
            _conso("315431", "RXNORM", "SCDC", "aspirin 81 MG"),
            _conso("999999", "RXNORM", "SCD", "thuốc đã lỗi thời", suppress="O"),
            _conso("888888", "SNOMEDCT_US", "PT", "chất không do RxNorm khẳng định"),
        ]
    )
    + "\n"
)

# rxcui1|rxaui1|stype1|rel|rxcui2|rxaui2|stype2|rela|rui|srui|sab|...
REL = """\
315431||CUI|RO|243670||CUI|consists_of|1||RXNORM|||
243670||CUI|RO|315431||CUI|constitutes|2||RXNORM|||
1191||CUI|RO|315431||CUI|has_ingredient|3||RXNORM|||
315431||CUI|RO|1191||CUI|ingredient_of|4||RXNORM|||
1191||CUI|RO|243670||CUI|has_inactive_ingredient|5||RXNORM|||
||AUI|RO|||AUI|has_ingredient|6||MMSL|||
"""


@pytest.fixture
def batch(tmp_path):
    (tmp_path / "RXNCONSO.RRF").write_text(CONSO, encoding="utf-8")
    (tmp_path / "RXNREL.RRF").write_text(REL, encoding="utf-8")
    return RxNormExtractor(tmp_path).extract()


class TestLocSuppress:
    def test_bo_atom_suppress_khac_N(self, batch):
        assert all("lỗi thời" not in t["term"] for t in batch.terms)

    def test_bo_concept_chi_co_atom_suppress(self, batch):
        assert "999999" not in {c["code"] for c in batch.concepts}


class TestNguonChu:
    def test_rxcui_khong_co_atom_RXNORM_thi_khong_thanh_concept(self, batch):
        """SAB khác chỉ được gắn synonym vào concept đã có, không tự tạo concept."""
        assert "888888" not in {c["code"] for c in batch.concepts}

    def test_atom_mo_coi_bi_bo(self, batch):
        assert all(t["code"] != "888888" for t in batch.terms)

    def test_atom_sab_khac_van_thanh_synonym(self, batch):
        """E3 — nguồn làm giàu miễn phí: atom GS/SNOMED gắn vào concept RxNorm."""
        terms = {t["term"] for t in batch.terms if t["code"] == "243670"}
        assert "Aspirin 81mg Oral tablet" in terms


class TestChieuQuanHe:
    def test_chieu_dung_la_rxcui2_toi_rxcui1(self, batch):
        """Dòng `rxcui1=315431 rela=consists_of rxcui2=243670`
        đọc là "243670 consists_of 315431" — lật chiều là hỏng cả đồ thị."""
        edges = {(r["src_code"], r["rel"], r["dst_code"]) for r in batch.relations}
        assert ("243670", "consists_of", "315431") in edges
        assert ("315431", "consists_of", "243670") not in edges

    def test_chi_luu_mot_chieu(self, batch):
        rels = {r["rel"] for r in batch.relations}
        assert "constitutes" not in rels  # chiều nghịch của consists_of
        assert "ingredient_of" not in rels

    def test_bo_quan_he_ngoai_danh_sach(self, batch):
        assert all(r["rel"] in ALLOWED_RELA for r in batch.relations)
        assert all("inactive" not in r["rel"] for r in batch.relations)

    def test_bo_dong_muc_atom(self, batch):
        """5,7 triệu dòng atom-level trong file thật — phải bị loại hết."""
        assert all(r["src_code"] and r["dst_code"] for r in batch.relations)

    def test_duong_di_scd_den_hoat_chat(self, batch):
        """SCD → SCDC → IN. Không có cạnh trực tiếp SCD → IN trong RxNorm."""
        edges = {(r["src_code"], r["rel"], r["dst_code"]) for r in batch.relations}
        assert ("243670", "consists_of", "315431") in edges
        assert ("315431", "has_ingredient", "1191") in edges


class TestTenHienThi:
    def test_uu_tien_SCD_hon_SY(self, batch):
        c = next(c for c in batch.concepts if c["code"] == "243670")
        assert c["pref_en"] == "aspirin 81 MG Oral Tablet"

    def test_hoat_chat_thuan_dung_IN(self, batch):
        c = next(c for c in batch.concepts if c["code"] == "1191")
        assert c["pref_en"] == "aspirin"

    def test_moi_concept_deu_co_ten(self, batch):
        assert all(c["pref_en"] for c in batch.concepts)

    def test_entity_kind_la_drug(self, batch):
        assert {c["entity_kind"] for c in batch.concepts} == {"drug"}
