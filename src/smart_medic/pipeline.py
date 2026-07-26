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
from typing import Iterable

from .kb.store import KnowledgeBase
from .schema import ASSERTABLE, MAPPABLE, ConceptType, Mention, Provenance
from .stages.assertion import AssertionTagger
from .stages.extract import Extractor
from .textref import TextRef


@dataclass
class RunStats:
    files: int = 0
    mentions: int = 0
    dropped_invariant: int = 0
    dropped_overlap: int = 0
    dropped_threshold: int = 0
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
    candidate_threshold: float = 0.80
    ambiguity_margin: float = 0.04
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
            codes = self._filter_codes(codes, c.provenance, st)
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

    def _filter_codes(self, codes, provenance, stats: RunStats) -> tuple[str, ...]:
        """Apply the v2 precision threshold to non-exact link paths.

        Exact gazetteer hits are the regression anchor and bypass the threshold.
        Retrieved codes carry per-code rerank scores in provenance.  A second
        code is retained only when it is genuinely close to the first.
        """
        if not codes:
            return ()
        if "gazetteer_exact" in provenance.link_path:
            return tuple(codes[: self.cfg.max_candidates])

        scored = [
            (code, provenance.scores.get(f"code:{code}", provenance.scores.get("confidence", 0.0)))
            for code in codes
        ]
        kept = [(code, score) for code, score in scored if score >= self.cfg.candidate_threshold]
        if not kept:
            stats.dropped_threshold += len(codes)
            provenance.link_path += "|dropped_threshold"
            return ()

        out = [kept[0][0]]
        if (
            self.cfg.max_candidates > 1
            and len(kept) > 1
            and kept[0][1] - kept[1][1] <= self.cfg.ambiguity_margin
        ):
            out.append(kept[1][0])
        stats.dropped_threshold += len(codes) - len(out)
        return tuple(out)

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
