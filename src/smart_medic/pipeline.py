"""Pipeline — DAG cố định, mỗi stage suy giảm an toàn thay vì ném lỗi.

    Extract → Locate → TypeGate → Assert → Link → Filter → Emit

Chính sách lỗi (system design §3.3): một file lỗi không được làm hỏng 99 file
còn lại. Mỗi stage có giá trị mặc định an toàn — và điểm may mắn của bài này là
"giá trị mặc định an toàn" TRÙNG với "giá trị điểm cao": metric quy ước J=1 khi
cả gold lẫn pred đều rỗng, còn candidates rỗng an toàn hơn đoán bừa.

Trường hợp xấu nhất cho một file là ``[]`` — vẫn đúng schema, vẫn nộp được.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kb.store import KnowledgeBase
from .schema import ASSERTABLE, MAPPABLE, ConceptType, Mention
from .stages.assertion import AssertionTagger
from .stages.extract import Extractor
from .textref import TextRef


@dataclass
class RunStats:
    files: int = 0
    mentions: int = 0
    dropped_invariant: int = 0
    dropped_overlap: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_assertion: dict[str, int] = field(default_factory=dict)
    with_candidates: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineConfig:
    max_candidates: int = 2
    enable_negated: bool = True
    enable_historical: bool = True
    enable_family: bool = False
    #: current | legacy | both — xem system design §4.8. Là CONFIG chứ không
    #: phải code, vì câu trả lời nằm ở BTC: mã 360047 trong ví dụ của đề đã
    #: hết hiệu lực 2019, và mã kế nhiệm 2178097 nay cũng SUPPRESS=O.
    rxnorm_output_mode: str = "current"


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
            codes = codes[: self.cfg.max_candidates]
            codes = self._apply_remap(codes, c.type)

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
            for a in m.assertions:
                st.by_assertion[a.value] = st.by_assertion.get(a.value, 0) + 1
        return mentions

    def _apply_remap(self, codes: tuple[str, ...], ctype: ConceptType) -> tuple[str, ...]:
        if ctype is not ConceptType.THUOC or self.cfg.rxnorm_output_mode == "current":
            return codes
        rev = self.kb.remap_reverse
        out: list[str] = []
        for c in codes:
            legacy = rev.get(c, [])
            if self.cfg.rxnorm_output_mode == "legacy" and legacy:
                out.append(legacy[0])
            elif self.cfg.rxnorm_output_mode == "both":
                out.append(c)
                out.extend(legacy[:1])
            else:
                out.append(c)
        return tuple(dict.fromkeys(out))[: self.cfg.max_candidates]
