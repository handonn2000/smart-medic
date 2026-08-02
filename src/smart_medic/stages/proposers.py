"""Bốn nguồn đề xuất span, quy về MỘT giao diện cho arbiter.

★ TRỌNG SỐ PHẢI ĐO, KHÔNG ĐƯỢC ĐẶT THEO TRỰC GIÁC
──────────────────────────────────────────────────
Trọng số của một proposer ở một nhãn = **precision của nó ở nhãn đó**. Đó là
diễn giải đúng của bài toán: weighted interval scheduling tối đa hoá tổng trọng
số, nên nếu trọng số là xác suất đúng thì nghiệm là tập span có kỳ vọng đúng lớn
nhất.

⚠️ Đo trên đâu là vấn đề. Prompt Phase 4 nói *"dựa trên precision đã đo trên
gold_real"* — nhưng quy tắc §5.7 nói **`gold_real` không bao giờ là NGUỒN**. Hai
câu đó mâu thuẫn nhau, và quy tắc thắng: chỉnh trọng số theo `gold_real` rồi
chấm cổng trên chính `gold_real` là tự khen.

Nên trọng số ở đây đo trên **`gold_batch1`** (858 span, văn bản lâm sàng THẬT,
ngoài miền, và **không phải cổng**). Số đo ghi trong `WEIGHTS` bên dưới kèm ngày
đo, để lần sau ai đổi thì biết phải đo lại chứ không phải chỉnh tay.
"""

from __future__ import annotations

from smart_medic.kb.query import KBStore
from smart_medic.stages import labtest, tagger
from smart_medic.stages.arbiter import Proposal
from smart_medic.stages.flags import weight as flag_weight
from smart_medic.stages.ner import Gazetteer, detect_masked_drugs
from smart_medic.stages.ner import detect as gazetteer_detect
from smart_medic.stages.scoring import Entity

RULE_GAZETTEER = "gazetteer"
RULE_LABTEST = "labtest"
RULE_MASKED = "masked_drug"
MODEL = "tagger"

# Precision theo (proposer, nhãn) — ĐO TRÊN `gold_batch1` ngày 2026-08-02.
# Đổi proposer thì phải ĐO LẠI, đừng chỉnh tay.
#
# ★ SỐ ĐO LẬT NGƯỢC GIẢ ĐỊNH CỦA KẾ HOẠCH.
#   Prompt Phase 4 đoán: *"THUỐC: luật thắng model · TRIỆU_CHỨNG: model thắng
#   luật"*. Vế đầu đúng, **vế sau sai hẳn**:
#
#       nhãn           gazetteer/labtest   tagger      ai thắng
#       CHẨN_ĐOÁN            0,614          0,816      ← MODEL (kế hoạch đoán luật)
#       TRIỆU_CHỨNG          0,883          0,673      ← LUẬT  (kế hoạch đoán model)
#       THUỐC                0,974          0,864      ← luật
#       TÊN_XÉT_NGHIỆM       0,714          0,633      ← luật
#       KẾT_QUẢ_XÉT_NGHIỆM   0,710          0,569      ← luật
#
#   Có lý do: gazetteer CHẨN_ĐOÁN kéo cả 16.944 mã ICD nên bắn rất bừa, còn
#   `SYMPTOM_HEADS` của nhánh triệu chứng là tập từ đóng nên chặt tay. Model thì
#   ngược lại — nó học từ corpus tổng hợp, nơi triệu chứng là cách nói dân dã do
#   LLM sinh, phân bố hẹp hơn thực tế.
#
# ⚠️ Precision KHÔNG phải toàn bộ câu chuyện. Một đề xuất KHÔNG có đối thủ thì
#    luôn được chọn (miễn trọng số > 0), nên model vẫn thêm recall ở mọi chỗ luật
#    im lặng — nó chỉ thua ở những span có tranh chấp.
WEIGHTS: dict[tuple[str, str], float] = {
    (RULE_GAZETTEER, "CHẨN_ĐOÁN"): 0.614,
    (RULE_GAZETTEER, "TRIỆU_CHỨNG"): 0.883,
    (RULE_GAZETTEER, "THUỐC"): 0.974,
    (RULE_LABTEST, "TÊN_XÉT_NGHIỆM"): 0.714,
    (RULE_LABTEST, "KẾT_QUẢ_XÉT_NGHIỆM"): 0.710,
    (MODEL, "CHẨN_ĐOÁN"): 0.816,
    (MODEL, "TRIỆU_CHỨNG"): 0.673,
    (MODEL, "THUỐC"): 0.864,
    (MODEL, "TÊN_XÉT_NGHIỆM"): 0.633,
    (MODEL, "KẾT_QUẢ_XÉT_NGHIỆM"): 0.569,
}

# Mặc định khi một cặp chưa được đo. Cố tình đặt thấp: proposer chưa có số đo
# thì không được thắng proposer đã có số đo.
DEFAULT_WEIGHT = 0.50

# ★ Thuốc bị che `***` — không proposer nào khác chạm tới, và mẫu của nó là
#   hiển nhiên (một dãy dấu sao). Cho trọng số cao nhất để không bao giờ bị
#   một span dài hơn nuốt mất.
MASKED_WEIGHT = 0.99


def _w(proposer: str, type_: str) -> float:
    return WEIGHTS.get((proposer, type_), DEFAULT_WEIGHT)


def _wrap(ents: list[Entity], proposer: str, scale: float = 1.0) -> list[Proposal]:
    return [
        Proposal(
            start=e.start,
            end=e.end,
            type=e.type,
            text=e.text,
            weight=_w(proposer, e.type) * scale,
            proposer=proposer,
            candidates=e.candidates,
            assertions=e.assertions,
        )
        for e in ents
    ]


def propose(
    text: str,
    store: KBStore,
    gaz: Gazetteer,
    *,
    model_weight: float | None = None,
) -> list[Proposal]:
    """Gom đề xuất từ cả bốn nguồn. **Được phép chồng lấn** — arbiter xử sau.

    ★ Khác biệt cốt lõi so với chuỗi cũ: ở đây không proposer nào nhìn thấy
    `taken` của proposer khác. Không ai bị chặn vì chạy sau. Quyết định thắng
    thua dời hết sang một chỗ có căn cứ đo được.
    """
    mw = flag_weight("arbiter_model_weight") if model_weight is None else model_weight

    gaz_ents = gazetteer_detect(text, gaz)
    out = _wrap(gaz_ents, RULE_GAZETTEER)
    # Hai luật này cần biết vùng đã có gì để không cắt nhầm ranh giới — đó là
    # ràng buộc NGỮ NGHĨA của chính chúng (hàm lượng thuốc không phải kết quả
    # xét nghiệm), không phải tranh chấp span. Nên vẫn truyền `taken`.
    out += _wrap(detect_masked_drugs(text, gaz_ents), RULE_MASKED, MASKED_WEIGHT / DEFAULT_WEIGHT)
    out += _wrap(labtest.detect(text, gaz_ents), RULE_LABTEST)
    if mw > 0:
        out += _wrap(tagger.detect(text), MODEL, mw)
    return out
