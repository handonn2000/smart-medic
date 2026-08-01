"""Kiểm tra nhánh RxNorm trong artifact đã build."""

from __future__ import annotations

import time

import pytest

from smart_medic.kb import config
from smart_medic.kb.query import KBStore, lookup, neighbors, search_lexical

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def store():
    if not config.KB_SQLITE.is_file():
        pytest.skip("chưa có artifact — chạy `smk kb build`")
    with KBStore() as s:
        if not s.conn.execute("SELECT count(*) FROM concepts WHERE vocab='rxnorm'").fetchone()[0]:
            pytest.skip("artifact chưa có RxNorm — chạy `smk kb build --source all`")
        yield s


class TestLookup:
    def test_ma_trong_vi_du_cua_PRD(self, store):
        """PRD trả 243670 cho "aspirin 81 mg po daily"."""
        c = lookup(store, "rxnorm", "243670")
        assert c is not None
        assert c.pref_en == "aspirin 81 MG Oral Tablet"
        assert c.entity_kind == "drug"

    def test_uu_tien_TTY_chon_SCD_lam_ten_hien_thi(self, store):
        """243670 có cả SCD, SY, PSN — phải chọn SCD."""
        rows = store.conn.execute(
            "SELECT term_type FROM terms t JOIN concepts c USING (concept_id) "
            "WHERE c.code = '243670' AND c.vocab = 'rxnorm'"
        ).fetchall()
        assert {r[0] for r in rows} >= {"SCD", "SY"}

    def test_hoat_chat_thuan(self, store):
        assert lookup(store, "rxnorm", "1191").pref_en == "aspirin"


class TestDoThiThuoc:
    def test_duong_di_hoat_chat_den_thuoc_ke_don(self, store):
        """IN → SCDC → SCD. RxNorm KHÔNG có cạnh trực tiếp IN → SCD.

        Đây là tiêu chí "neighbors từ IN:1191 ra được tập SCD chứa aspirin";
        trong RxNorm nó là đường đi hai bước chứ không phải một.
        """
        aspirin = lookup(store, "rxnorm", "1191")
        scdc = neighbors(store, aspirin.concept_id, rel="has_ingredient", direction="in")
        assert scdc, "không có SCDC nào chứa aspirin"

        scds = [
            d
            for c in scdc
            for d in neighbors(store, c.concept_id, rel="consists_of", direction="in")
        ]
        assert len(scds) > 0
        assert any(c.code == "243670" for c in scds)

    def test_chieu_quan_he_khong_bi_lat(self, store):
        """243670 consists_of 315431, KHÔNG phải ngược lại."""
        scd = lookup(store, "rxnorm", "243670")
        out = neighbors(store, scd.concept_id, rel="consists_of", direction="out")
        assert any(c.code == "315431" for c in out)

    def test_ten_thuong_mai(self, store):
        scd = lookup(store, "rxnorm", "243670")
        assert neighbors(store, scd.concept_id, rel="has_tradename", direction="out")


class TestTruyHoi:
    @pytest.mark.parametrize(
        ("query", "code"),
        [
            ("aspirin 81 mg po daily", "243670"),
            ("amlodipine 10 mg po daily", "308135"),
            ("omeprazole", "7646"),
            ("metoprolol", "6918"),
        ],
    )
    def test_mention_thuoc_that(self, store, query, code):
        hits = search_lexical(store, query, vocab="rxnorm", top_k=10)
        assert code in [h.code for h in hits]

    def test_khong_lan_sang_bo_ma_khac(self, store):
        hits = search_lexical(store, "aspirin", vocab="rxnorm", top_k=20)
        assert hits and all(h.concept.vocab == "rxnorm" for h in hits)

    def test_toc_do_truy_van(self, store):
        """Bộ lọc vocab phải nằm TRONG biểu thức MATCH.

        Đặt ở WHERE thì planner chọn `concepts` làm vòng ngoài rồi SCAN
        terms_fts — đo được 7,4 s cho một truy vấn. Ngưỡng rộng rãi ở đây chỉ
        để bắt hồi quy về đúng lớp lỗi đó, không phải để đo hiệu năng tinh.
        """
        t0 = time.perf_counter()
        for q in ("aspirin 81 mg po daily", "trào ngược dạ dày", "omeprazole"):
            search_lexical(store, q, vocab="rxnorm", top_k=10)
        assert time.perf_counter() - t0 < 2.0


class TestKhongHoiQuyPhase1:
    def test_icd_van_nguyen_ven(self, store):
        n = store.conn.execute(
            "SELECT count(*) FROM concepts WHERE vocab='icd10' AND entity_kind='disease'"
        ).fetchone()[0]
        assert n == 16944

    def test_hai_bo_ma_cung_ton_tai(self, store):
        vocabs = {r[0] for r in store.conn.execute("SELECT DISTINCT vocab FROM concepts")}
        assert {"icd10", "rxnorm"} <= vocabs
