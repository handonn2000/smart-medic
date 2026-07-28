"""Pipeline — DAG cố định, mỗi stage suy giảm an toàn thay vì ném lỗi.

    Extract → Locate → TypeGate → Assert → Link → Filter → Emit

Chính sách lỗi (system design §3.3): một file lỗi không được làm hỏng 99 file
còn lại. Mỗi stage có giá trị mặc định an toàn, và metric quy ước J=1 khi cả
gold lẫn pred đều rỗng — nên hỏng thì trả rỗng vẫn nộp được.

CẢNH BÁO, sửa từ v3.3: "candidates rỗng an toàn hơn đoán bừa" là SAI khi mention
đã khớp và gold khác rỗng — lúc đó J(∅, G) = 0 tuyệt đối, còn một mã bất kỳ có
kỳ vọng P(c ∈ G) ≥ 0. Rỗng chỉ an toàn khi gold cũng rỗng, mà điều đó do TYPE
quyết định chứ không do retrieval. Xem :func:`select_candidate_set`.

Trường hợp xấu nhất cho một file là ``[]`` — vẫn đúng schema, vẫn nộp được.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .kb.store import KnowledgeBase
from .schema import ASSERTABLE, MAPPABLE, ConceptType, Mention, Provenance
from .stages.assertion import AssertionTagger
from .stages.extract import Extractor
from .textref import TextRef


#: Link paths whose codes come from an exact, unambiguous KB alias rather than
#: from ranked retrieval.  They carry no rerank score to threshold against, and
#: thresholding them would silently discard the most reliable codes we have.
EXACT_LINK_PATHS = ("gazetteer_exact", "rxnorm_anchor_exact")


@dataclass(frozen=True)
class CandidateDecision:
    """Kết quả của tầng quyết định candidates cho MỘT mention."""

    codes: tuple[str, ...]
    #: True = dự đoán "gold cũng rỗng". Khác hẳn với "retrieval yếu nên bỏ".
    abstained: bool = False
    #: Số mã bị loại khi chọn kích thước tập (không phải do bỏ trống).
    dropped: int = 0


def _icd_siblings(a: str, b: str) -> bool:
    """True khi hai mã là hai phân nhánh CÙNG cha (``K21.0`` / ``K21.9``).

    Đây chính là hình dạng của ví dụ BTC tự đưa ra: một alias tiếng Việt, hai
    con của cùng một mã cha, và văn bản không có gì để chọn giữa chúng — nên
    gold liệt kê CẢ HAI.  Ngược lại ``I60`` / ``I60.8`` KHÔNG phải: cha và con
    ruột của nó là lựa chọn về độ đặc hiệu, gold chỉ lấy một.

    Mã RxNorm thuần số, không có dấu chấm → thuốc không bao giờ lọt cửa này.
    """
    if a == b or "." not in a or "." not in b:
        return False
    return a.split(".", 1)[0] == b.split(".", 1)[0]


def select_candidate_set(
    codes: Sequence[str],
    *,
    scores: Mapping[str, float],
    link_path: str = "",
    type_confidence: float = 1.0,
    min_type_confidence: float = 0.0,
    max_candidates: int = 2,
    candidate_threshold: float = 0.0,
    ambiguity_margin: float = 0.0,
) -> CandidateDecision:
    """Chọn tập candidates tối ưu kỳ vọng dưới độ đo Jaccard.

    Hàm thuần (không sửa gì) để :mod:`smart_medic.metric_simulator` mô phỏng
    ĐÚNG chính sách đang chạy chứ không phải một bản sao đã lệch.

    **1. Khi nào bỏ trống.** Với một mention khớp và gold ``G`` khác rỗng::

        J(∅, G)   = |∅ ∩ G| / |∅ ∪ G| = 0        — luôn luôn đúng bằng 0
        E[J({c})] = P(c ∈ G)                     — luôn ≥ 0

    Nên bỏ trống bị *weakly dominated* bởi mọi phỏng đoán, MIỄN LÀ gold khác
    rỗng.  Bỏ trống chỉ có lãi khi gold cũng rỗng — tức khi TYPE sai (gold gọi
    span này là TRIỆU_CHỨNG, mà TRIỆU_CHỨNG bắt buộc candidates rỗng), chứ
    không phải khi retrieval không chắc.  Đặt ``p_t`` = P(type gold thuộc
    MAPPABLE) và ``a₁`` = P(mã đầu bảng đúng)::

        emit  ⟺  p_t·a₁ > 1 − p_t  ⟺  p_t > 1/(1 + a₁)

    ``min_type_confidence`` chính là vế phải đó (xem
    :attr:`PipelineConfig.min_type_confidence`).

    **2. Kích thước tập.** Với gold đơn phần tử và xác suất đã hiệu chuẩn
    ``p₁ ≥ p₂ ≥ …``, ``E[J(top-k)] = (Σᵢ≤ₖ pᵢ)/k`` đạt cực đại tại ``k = 1``
    LUÔN LUÔN — vì ``(p₁+p₂)/2 > p₁`` đòi ``p₂ > p₁``, vô lý.  Mã thứ hai chỉ
    có lãi khi CHÍNH GOLD có thể có hai mã.  Gọi ``q`` = P(gold = {c₁, c₂})::

        E[J({c₁})]    = q·½ + (1−q)·p₁'
        E[J({c₁,c₂})] = q·1 + (1−q)·(p₁' + p₂')/2
        thêm mã 2  ⟺  q/(1−q) > p₁' − p₂'

    Điều kiện phụ thuộc ``q``, KHÔNG phụ thuộc khoảng cách điểm rerank.  Ta chỉ
    có hai nguồn bằng chứng thật cho ``q > 0``:

    * điểm hai mã BẰNG NHAU (``p₁' − p₂' = 0``) — không có gì phân biệt chúng,
      nên bất kỳ ``q > 0`` nào cũng làm vế trái thắng; và
    * hai mã là anh em cùng cha trong ICD — đúng hình dạng ví dụ K21.0/K21.9
      mà BTC đã chấm là gold hai mã.

    ``ambiguity_margin`` bây giờ MANG NGHĨA ``q/(1−q)``, mặc định 0.0 = đòi hòa
    điểm tuyệt đối.  Nó không còn là hằng số chỉnh tay 0.04 nữa.

    **3. Điểm rerank** chỉ còn dùng để XẾP HẠNG và để chặn mã thứ hai; nó không
    bao giờ gây bỏ trống nữa, vì đó là trục sai.
    """
    if not codes:
        return CandidateDecision(())
    if type_confidence < min_type_confidence:
        return CandidateDecision((), abstained=True)

    exact = any(path in link_path for path in EXACT_LINK_PATHS)
    default = scores.get("confidence", 0.0)
    # sorted() ổn định → mã hòa điểm giữ nguyên thứ tự KB ⇒ tất định.
    ranked = sorted(
        ((code, scores.get(f"code:{code}", default)) for code in codes),
        key=lambda item: -item[1],
    )

    out = [ranked[0][0]]
    if max_candidates > 1 and len(ranked) > 1:
        (top, top_score), (second, second_score) = ranked[0], ranked[1]
        if (
            top_score - second_score <= ambiguity_margin
            and _icd_siblings(top, second)
            and (exact or second_score >= candidate_threshold)
        ):
            out.append(second)
    return CandidateDecision(tuple(out), dropped=len(codes) - len(out))


@dataclass
class RunStats:
    files: int = 0
    mentions: int = 0
    dropped_invariant: int = 0
    dropped_overlap: int = 0
    #: Mã bị loại khi chọn KÍCH THƯỚC tập (đuôi danh sách rerank).
    dropped_threshold: int = 0
    #: Mã bị bỏ vì p_t thấp — tức ta dự đoán gold cũng rỗng.
    dropped_type_confidence: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_assertion: dict[str, int] = field(default_factory=dict)
    by_link_path: dict[str, int] = field(default_factory=dict)
    with_candidates: int = 0
    errors: list[str] = field(default_factory=list)


    def recount(self, mention_sets: Iterable[list[Mention]], *, files: int) -> None:
        """Recount final mentions after deterministic batch post-processing."""
        self.files = files
        self.mentions = 0
        self.by_type.clear()
        self.by_assertion.clear()
        self.by_link_path.clear()
        self.with_candidates = 0
        for mentions in mention_sets:
            self.mentions += len(mentions)
            for mention in mentions:
                self.by_type[mention.type.value] = (
                    self.by_type.get(mention.type.value, 0) + 1
                )
                if mention.candidates:
                    self.with_candidates += 1
                path = mention.provenance.link_path or "unknown"
                self.by_link_path[path] = self.by_link_path.get(path, 0) + 1
                for assertion in mention.assertions:
                    self.by_assertion[assertion.value] = (
                        self.by_assertion.get(assertion.value, 0) + 1
                    )


@dataclass
class PipelineConfig:
    max_candidates: int = 2
    #: Điểm rerank tối thiểu cho MÃ THỨ HAI. Không còn gây bỏ trống candidates
    #: (xem :func:`select_candidate_set`) — đó là trục sai.
    candidate_threshold: float = 0.80
    #: ``q/(1−q)`` với ``q`` = P(gold thật sự liệt kê cả hai mã anh em).
    #: 0.0 = chỉ nhận cặp hòa điểm tuyệt đối.
    #:
    #: HIỆU CHUẨN 27/07 trên data/dev_gold (20 file): 171/171 mention có mã đều
    #: có ĐÚNG MỘT mã ⇒ q ≈ 0. Đo lại trên cả ba biến thể gold độc lập: 1/290.
    #: NHƯNG cả bốn gold đều do LLM sinh từ cùng một prompt nên chia sẻ thiên
    #: kiến, còn ví dụ chính thức của BTC (GERD → {K21.0, K21.9}) thì CÓ hai mã.
    #: Giữ 0.0: cổng hiện tại đòi hòa điểm tuyệt đối VÀ hai mã là anh em ICD —
    #: đúng hình dạng ví dụ BTC, và q≈0.003 vẫn đủ để E[J] chọn thêm mã khi
    #: p₁−p₂ = 0. Không siết thêm khi bằng chứng chỉ là gold LLM.
    ambiguity_margin: float = 0.0
    #: ``a₁`` = P(mã đầu bảng nằm trong gold).
    #:
    #: HIỆU CHUẨN 27/07 trên data/dev_gold: 56/93 = 0.602 trên các cặp đã ghép
    #: mà hai bên đều có mã. Phân rã theo link_path rất lệch:
    #:     icd_contextual_rewrite  16/16 = 1.000
    #:     rxnorm_anchor_exact     15/15 = 1.000   ← fallback IN/BN của Phase 1
    #:     icd_lexical_retrieval    1/1  = 1.000
    #:     gazetteer_exact         24/61 = 0.393   ← ĐƯỜNG "TIN CẬY NHẤT" LẠI TỆ NHẤT
    #: 22/37 lỗi gazetteer là sai ĐỘ ĐẶC HIỆU: ta trả mã cha 3 ký tự (N17, G80,
    #: K58, K26) còn gold muốn con ".9" không đặc hiệu (N17.9, G80.9, ...).
    #: Xem docs/TODO-v4.md — đây là lỗi cơ học, không phải giới hạn model.
    a1_top1_accuracy: float = 0.602
    #: Sàn cứng bổ sung cho ``p_t``, áp CHỒNG lên ngưỡng suy ra từ ``a₁``.
    #: 0.0 = tin hoàn toàn vào công thức (a₁=0.602 → ngưỡng 0.624).
    #:
    #: HIỆU CHUẨN 27/07: không cần sàn thêm. 40/40 span bị gắn cờ chương R mà
    #: ghép được với gold đều được gold gọi là TRIỆU_CHỨNG — p_t thực đo bằng 0,
    #: nằm sâu dưới ngưỡng 0.624, nên tiên nghiệm chương R đã tự bỏ trống đúng.
    type_confidence_floor: float = 0.0
    enable_negated: bool = True
    enable_historical: bool = True
    enable_family: bool = False
    #: current | legacy | both — xem system design §4.8. Là CONFIG chứ không
    #: phải code, vì câu trả lời nằm ở BTC: mã 360047 trong ví dụ của đề đã
    #: hết hiệu lực 2019, và mã kế nhiệm 2178097 nay cũng SUPPRESS=O.
    rxnorm_output_mode: str = "current"

    def __post_init__(self) -> None:
        if self.rxnorm_output_mode not in {"current", "legacy", "both"}:
            raise ValueError(
                "rxnorm_output_mode phải là current, legacy hoặc both"
            )
        if not 0.0 <= self.a1_top1_accuracy <= 1.0:
            raise ValueError("a1_top1_accuracy phải nằm trong [0, 1]")

    @property
    def min_type_confidence(self) -> float:
        """``1/(1 + a₁)`` — ngưỡng ``p_t`` để phát mã thay vì bỏ trống.

        Suy ra trực tiếp từ ``p_t·a₁ > 1 − p_t``; với ``a₁ = 0.5`` là 0.667.
        ``type_confidence_floor`` chỉ có thể siết chặt thêm, không nới ra.
        """
        return max(self.type_confidence_floor, 1.0 / (1.0 + self.a1_top1_accuracy))


class Pipeline:
    def __init__(
        self, kb: KnowledgeBase, extractor: Extractor, cfg: PipelineConfig | None = None
    ) -> None:
        self.kb = kb
        self.extractor = extractor
        self.cfg = cfg or PipelineConfig()

    def run(self, tref: TextRef, stats: RunStats | None = None) -> list[Mention]:
        st = stats if stats is not None else RunStats()
        try:
            cands = self.extractor.extract(tref)
        except Exception as exc:                       # noqa: BLE001
            st.errors.append(f"extract: {type(exc).__name__}: {exc}")
            return []                                  # suy giảm, không sập

        tagger = AssertionTagger(
            tref,
            enable_negated=self.cfg.enable_negated,
            enable_historical=self.cfg.enable_historical,
            enable_family=self.cfg.enable_family,
        )

        mentions: list[Mention] = []
        taken: list[Mention] = []
        for c in sorted(cands, key=lambda x: (x.span.start, -(x.span.end - x.span.start))):
            if not c.span.verify(tref.raw):
                st.dropped_invariant += 1
                continue
            if any(c.span.overlaps(m.span) for m in taken):
                st.dropped_overlap += 1
                continue

            # ── TypeGate: chỉ CHẨN_ĐOÁN và THUỐC được giữ candidates ──
            codes = tuple(c.codes) if c.type in MAPPABLE else ()
            codes = self._select_candidates(codes, c.provenance, st)
            codes = self._apply_remap(codes, c.type, c.provenance)

            flags, evidence = (frozenset(), {})
            if c.type in ASSERTABLE:
                flags, evidence = tagger.tag(c.span, c.type)

            prov = c.provenance
            prov.evidence.update(evidence)
            if codes and not prov.kb_rows:
                # Chặn cứng mã bịa: không truy được về dòng KB thì bỏ mã.
                codes = ()
                prov.link_path += "|dropped_no_provenance"

            m = Mention(
                span=c.span, type=c.type, assertions=flags,
                candidates=codes, provenance=prov,
            )
            mentions.append(m)
            taken.append(m)

        st.files += 1
        st.mentions += len(mentions)
        for m in mentions:
            st.by_type[m.type.value] = st.by_type.get(m.type.value, 0) + 1
            if m.candidates:
                st.with_candidates += 1
            path = m.provenance.link_path or "unknown"
            st.by_link_path[path] = st.by_link_path.get(path, 0) + 1
            for a in m.assertions:
                st.by_assertion[a.value] = st.by_assertion.get(a.value, 0) + 1
        return mentions

    def _select_candidates(
        self, codes, provenance: Provenance, stats: RunStats
    ) -> tuple[str, ...]:
        """Tầng quyết định candidates — bọc :func:`select_candidate_set`.

        Ở đây chỉ có kế toán: hàm quyết định thật là hàm thuần phía trên, để
        metric_simulator dùng chung đúng một chính sách.  Bỏ trống được ghi
        RIÊNG (``dropped_type_confidence``) khỏi cắt đuôi danh sách
        (``dropped_threshold``) — hai chuyện khác hẳn nhau và trước đây bị gộp
        vào một con số khiến báo cáo "24 mã bị ngưỡng loại" bị đọc nhầm thành
        24 mention đã bỏ trống.
        """
        if not codes:
            return ()
        decision = select_candidate_set(
            codes,
            scores=provenance.scores,
            link_path=provenance.link_path,
            type_confidence=provenance.type_confidence,
            min_type_confidence=self.cfg.min_type_confidence,
            max_candidates=self.cfg.max_candidates,
            candidate_threshold=self.cfg.candidate_threshold,
            ambiguity_margin=self.cfg.ambiguity_margin,
        )
        if decision.abstained:
            stats.dropped_type_confidence += len(codes)
            provenance.link_path += "|abstained_low_type_confidence"
            return ()
        stats.dropped_threshold += decision.dropped
        return decision.codes

    def _apply_remap(
        self, codes: tuple[str, ...], ctype: ConceptType, provenance: Provenance
    ) -> tuple[str, ...]:
        if ctype is not ConceptType.THUOC or self.cfg.rxnorm_output_mode == "current":
            return codes
        rev = self.kb.remap_reverse
        out: list[str] = []
        for c in codes:
            legacy = rev.get(c, [])
            if self.cfg.rxnorm_output_mode == "legacy" and legacy:
                selected = legacy[0]
                out.append(selected)
                provenance.kb_rows.append(f"rx-remap:{selected}->{c}")
                provenance.scores[f"code:{selected}"] = provenance.scores.get(
                    f"code:{c}", provenance.scores.get("confidence", 0.0)
                )
                provenance.scores.pop(f"code:{c}", None)
            elif self.cfg.rxnorm_output_mode == "both":
                out.append(c)
                if legacy:
                    selected = legacy[0]
                    out.append(selected)
                    provenance.kb_rows.append(f"rx-remap:{selected}->{c}")
                    provenance.scores[f"code:{selected}"] = provenance.scores.get(
                        f"code:{c}", provenance.scores.get("confidence", 0.0)
                    )
            else:
                out.append(c)
        return tuple(dict.fromkeys(out))[: self.cfg.max_candidates]
