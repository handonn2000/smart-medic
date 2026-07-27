"""Extract — interface + implementation cho v0.

Provider pattern (system design §2, quyết định #2): Extractor có nhiều
implementation qua các vòng. Nếu lời gọi LLM nằm rải trong pipeline thì v3 phải
viết lại pipeline; nằm sau interface thì v3 chỉ đổi một dòng config.

    v0  GazetteerExtractor   offline, tất định   ← đang ở đây
    v1  LLMExtractor         cần API
    v3  EncoderExtractor     XLM-R distill, offline lại
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..kb.store import KnowledgeBase
from ..normalize import norm_text
from ..retrieval import IcdRetriever
from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef


#: ``p_t`` khi mã ICD khớp tốt nhất nằm ở chương R ("triệu chứng, dấu hiệu và
#: phát hiện bất thường").  Đo được: 27% mention khớp tên ICD nguyên văn rơi vào
#: chương R (khó thở→R06.0, đau đầu→R51).  Một span rơi vào đó là BẰNG CHỨNG
#: người gán nhãn gọi nó là TRIỆU_CHỨNG — mà TRIỆU_CHỨNG bắt buộc candidates
#: rỗng.  Trước đây cờ này bị dùng như blocklist (bỏ thẳng mention); giờ nó là
#: tiên nghiệm về TYPE, nên việc bỏ trống candidates xảy ra vì ĐÚNG LÝ DO.
#:
#: PLACEHOLDER — 0.15 chưa được hiệu chuẩn. Ước lượng thật là tỉ lệ span khớp
#: chương R mà gold vẫn gán CHẨN_ĐOÁN, đo trên data/dev_gold/ (đang dựng song
#: song, chưa có trong repo). Chỉ cần nó < PipelineConfig.min_type_confidence
#: là chính sách hiện tại không đổi.
SYMPTOM_CHAPTER_TYPE_CONFIDENCE = 0.15


@dataclass
class Candidate:
    """Một khái niệm ứng viên do Extractor đề xuất, ĐÃ định vị."""

    span: Span
    type: ConceptType
    codes: tuple[str, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)


class Extractor(Protocol):
    name: str

    def extract(self, tref: TextRef) -> list[Candidate]:
        ...


class GazetteerExtractor:
    """Baseline v0 — quét tên bệnh ICD nguyên văn.

    Đây cũng là BASELINE HỒI QUY VĨNH VIỄN: mọi vòng sau phải đo được là hơn nó.
    Chạy vài giây, offline 100%, không phụ thuộc mạng, hoàn toàn tất định.

    Type gate ngay tại đây (system design §4.4): mã chương R là "triệu chứng &
    dấu hiệu bất thường", KHÔNG phải chẩn đoán. Đo được 27% mention khớp
    nguyên văn rơi vào chương R (khó thở→R06.0, đau đầu→R51). Những mention
    này được gán TRIỆU_CHỨNG và candidates RỖNG — vì schema bắt buộc thế.
    """

    name = "gazetteer"

    # Exact string matches that are procedures, anatomy, generic findings or
    # treatment concepts rather than patient diagnoses.  These aliases are
    # frequent false positives in the 100-file corpus because their ICD rows
    # are valid but their surface use is not diagnostic.
    _BLOCKED_GENERIC_ALIASES = frozenset({
        "bàng quang",
        "bệnh tim mạch",
        "cách ly",
        "các bệnh hô hấp",
        "chống đông máu",
        "cột sống",
        "dò dịch não tủy",
        "giảm thể tích",
        "hiến máu",
        "khám răng",
        "nhiễm trùng",
        "niệu quản",
        "tác dụng phụ",
        "thuốc lợi tiểu",
        "tinh hoàn",
        "tổn thương",
        "tránh thai",
        "tuyến tiền liệt",
    })

    # Short ICD aliases that are valid only until a following token makes a
    # more specific concept.  The corresponding full phrases are emitted by
    # IcdCueExtractor, preventing incorrect spans such as ``viêm tủy`` inside
    # ``viêm tủy xương`` (dental pulpitis K04.0 vs osteomyelitis M86).
    _BLOCKED_FOLLOWING = {
        "nhiễm khuẩn": ("đường ", "hệ ", "máu", "huyết", "lợi", "da", "chi "),
        "phù gai": ("thị",),
        "viêm tủy": ("xương",),
    }

    # The organiser's GERD example explicitly accepts both child codes when
    # the text does not say whether oesophagitis is present.  Preserve this
    # contract instead of collapsing the hierarchy to the parent K21.
    _CONTRACT_AMBIGUOUS_CHILDREN = {
        "K21": ("K21.0", "K21.9"),
    }

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        max_candidates: int = 2,
        contextual_ambiguity: bool = False,
    ) -> None:
        self.kb = kb
        self.max_candidates = max_candidates
        self.contextual_ambiguity = contextual_ambiguity

    @staticmethod
    def _resolve_hierarchy(codes: tuple[str, ...], alias: str) -> tuple[str, ...]:
        """Choose a parent or unspecified child only when codes form one hierarchy."""
        if "K21" in codes and "trào ngược" in alias:
            return GazetteerExtractor._CONTRACT_AMBIGUOUS_CHILDREN["K21"]
        if len(codes) < 2:
            return codes
        ordered = sorted(set(codes), key=lambda code: (len(code), code))
        parent = ordered[0]
        children = [code for code in ordered[1:] if code.startswith(parent + ".")]
        if len(children) != len(ordered) - 1:
            return codes
        contracted = GazetteerExtractor._CONTRACT_AMBIGUOUS_CHILDREN.get(parent)
        if contracted and all(code in children for code in contracted):
            return contracted
        unspecified = any(
            phrase in alias for phrase in ("không đặc hiệu", "không xác định", "không rõ")
        )
        return (children[-1] if unspecified else parent,)

    def extract(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        for m in self.kb.icd_gaz.scan(tref.norm):
            if m.alias in self._BLOCKED_GENERIC_ALIASES:
                continue
            following = tref.norm[m.ne:m.ne + 32].lstrip()
            if any(
                following.startswith(prefix)
                for prefix in self._BLOCKED_FOLLOWING.get(m.alias, ())
            ):
                continue
            rs, re_ = tref.to_raw(m.ns, m.ne)
            text = tref.raw[rs:re_]
            span = Span(rs, re_, text)
            if not span.verify(tref.raw):
                continue                       # bất biến vỡ → loại, không đoán

            prov = Provenance(
                extractor=self.name,
                locate_method="gazetteer_scan",
                link_path="gazetteer_exact",
                kb_rows=[f"icd:{c}" for c in m.codes],
                scores={"confidence": 1.0},
            )

            if m.is_symptom_chapter:
                # Chương R → triệu chứng. KHÔNG gán mã: schema cấm. Ghi luôn
                # p_t để tầng quyết định của pipeline nhìn thấy CÙNG bằng chứng
                # ấy dưới dạng số, thay vì tin vào một type gate câm.
                prov.type_confidence = SYMPTOM_CHAPTER_TYPE_CONFIDENCE
                prov.evidence["type_prior"] = "icd_chapter_r"
                out.append(Candidate(span, ConceptType.TRIEU_CHUNG, (), prov))
            else:
                codes = m.codes
                if self.contextual_ambiguity:
                    codes = self._resolve_hierarchy(codes, m.alias)
                    prov.kb_rows = [f"icd:{code}" for code in codes]
                out.append(
                    Candidate(
                        span,
                        ConceptType.CHAN_DOAN,
                        codes[: self.max_candidates],
                        prov,
                    )
                )
        return out


class IcdCueExtractor:
    """Retrieve and rerank diagnosis phrases introduced by a strong cue.

    This is intentionally narrower than free-form NER.  With no labelled dev
    set, activating retrieval on every n-gram would turn recall into false
    positives.  Strong cues provide a conservative bridge for colloquial names
    such as ``thiếu men G6PD`` that the exact gazetteer cannot see.
    """

    name = "icd_cue_retrieval"
    _CUE_RE = re.compile(
        r"(?<![\wăâđêôơư])(?:chẩn\s*đoán(?:\s+là)?|mắc)\s*[:\-]?\s*"
    )
    _STANDALONE_RE = re.compile(
        r"(?<!\w)(?:nhiễm\s+(?:trùng|khuẩn)\s+đường\s+tiết\s+niệu|"
        r"nhiễm\s+(?:trùng|khuẩn)\s+(?:máu|huyết)|"
        r"viêm\s+(?:tủy\s+xương|xương\s+tủy)|"
        r"phù\s+gai\s+thị|thiếu\s+men\s+g6pd|cao\s+huyết\s+áp|"
        r"tiểu\s+đường(?:\s+(?:típ|type|loại)\s*[12])?|viêm\s+bao\s+tử|"
        r"xuất\s+huyết\s+tiêu\s+hóa|xhth|rụng\s+tóc\s+từng\s+vùng|"
        r"bàn\s+chân\s+bẹt)(?!\w)"
    )
    _STANDALONE_CODES = {
        "nhiễm trùng đường tiết niệu": "N39.0",
        "nhiễm khuẩn đường tiết niệu": "N39.0",
        "nhiễm trùng máu": "A41",
        "nhiễm trùng huyết": "A41",
        "nhiễm khuẩn máu": "A41",
        "nhiễm khuẩn huyết": "A41",
        "viêm tủy xương": "M86",
        "viêm xương tủy": "M86",
        "phù gai thị": "H47.1",
        "thiếu men g6pd": "D55.0",
        "cao huyết áp": "I10",
        "tiểu đường": "E14",
        "tiểu đường típ 1": "E10",
        "tiểu đường type 1": "E10",
        "tiểu đường loại 1": "E10",
        "tiểu đường típ 2": "E11",
        "tiểu đường type 2": "E11",
        "tiểu đường loại 2": "E11",
        "viêm bao tử": "K29.7",
        "xuất huyết tiêu hóa": "K92.2",
        "xhth": "K92.2",
        "rụng tóc từng vùng": "L63",
        "bàn chân bẹt": "Q66.5",
    }
    _WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
    _GENERIC = frozenset(
        {"bệnh", "hội", "chứng", "viêm", "xác", "định", "biến", "chứng"}
    )

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        threshold: float = 0.80,
        top_k: int = 5,
    ) -> None:
        self.kb = kb
        self.retriever = IcdRetriever(kb)
        self.threshold = threshold
        self.top_k = top_k
        self._cache: dict[str, list] = {}

    def extract(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        for match in self._STANDALONE_RE.finditer(tref.norm):
            preferred = self._STANDALONE_CODES.get(match.group())
            if preferred in self.kb.icd_concepts:
                out.append(self._make_direct_candidate(
                    tref, match.start(), match.end(), preferred
                ))
                continue
            ranked = self.retriever.retrieve(match.group(), top_k=self.top_k)
            preferred_ranked = [item for item in ranked if item.code == preferred]
            if preferred_ranked:
                ranked = preferred_ranked
            if ranked and ranked[0].score >= self.threshold:
                out.append(self._make_candidate(tref, match.start(), match.end(), ranked))

        for cue in self._CUE_RE.finditer(tref.norm):
            tail_start = cue.end()
            tail_end = min(len(tref.norm), tail_start + 96)
            for pos in range(tail_start, tail_end):
                raw_piece = tref.raw[tref.n2r[pos] : tref.n2r_end[pos]]
                if "\n" in raw_piece or "\r" in raw_piece:
                    tail_end = pos
                    break
            tail = tref.norm[tail_start:tail_end]
            tail = re.split(
                r"[.,;:!?()]|\s+-\s+|-(?=bệnh\b)|\b(?:nhưng|tuy nhiên|kèm theo|được|đang|hiện|cách đây)\b",
                tail,
                maxsplit=1,
            )[0]
            words = list(self._WORD_RE.finditer(tail))[:8]
            if not words:
                continue
            phrase_end = words[-1].end()
            phrase = tail[:phrase_end].strip()
            ranked = self._cache.get(phrase)
            if ranked is None:
                ranked = self.retriever.retrieve(phrase, top_k=self.top_k)
                self._cache[phrase] = ranked
            if not ranked:
                continue
            top = ranked[0]
            phrase_tokens = {m.group().casefold() for m in self._WORD_RE.finditer(phrase)}
            informative = phrase_tokens - self._GENERIC
            has_known_abbreviation = bool(phrase_tokens & {"g6pd", "copd", "gerd"})
            if len(informative) < 2 and not has_known_abbreviation:
                continue
            if top.score < self.threshold:
                continue

            ns, ne = tail_start, tail_start + phrase_end
            out.append(self._make_candidate(tref, ns, ne, ranked))
        unique: dict[tuple[int, int], Candidate] = {}
        for candidate in out:
            unique.setdefault((candidate.span.start, candidate.span.end), candidate)
        return sorted(unique.values(), key=lambda candidate: candidate.span.start)

    def _is_symptom_chapter(self, code: str) -> bool:
        return bool(int(self.kb.icd_concepts.get(code, {}).get("is_symptom_chapter", 0)))

    def _make_direct_candidate(
        self, tref: TextRef, ns: int, ne: int, code: str
    ) -> Candidate:
        rs, re_ = tref.to_raw(ns, ne)
        span = Span(rs, re_, tref.raw[rs:re_])
        confidence = 0.96
        prov = Provenance(
            extractor=self.name,
            locate_method="contextual_phrase_rewrite",
            link_path="icd_contextual_rewrite",
            kb_rows=[f"icd:{code}"],
            scores={"confidence": confidence, f"code:{code}": confidence},
            evidence={"normalized_surface": tref.norm[ns:ne]},
        )
        return self._typed_candidate(span, (code,), prov, code)

    def _make_candidate(self, tref: TextRef, ns: int, ne: int, ranked) -> Candidate:
        rs, re_ = tref.to_raw(ns, ne)
        span = Span(rs, re_, tref.raw[rs:re_])
        top = ranked[0]
        code_scores = {f"code:{r.code}": r.score for r in ranked}
        prov = Provenance(
            extractor=self.name,
            locate_method="strong_cue_prefix",
            link_path="icd_lexical_retrieval|rerank",
            kb_rows=[f"icd:{r.code}" for r in ranked],
            scores={"confidence": top.score, **code_scores},
            evidence={"best_alias": top.alias},
        )
        return self._typed_candidate(
            span, tuple(r.code for r in ranked), prov, top.code
        )

    def _typed_candidate(
        self, span: Span, codes: tuple[str, ...], prov: Provenance, best_code: str
    ) -> Candidate:
        """Quyết định TYPE bằng tiên nghiệm chương ICD, rồi ghi ``p_t``.

        Trước đây khớp chương R bị ``continue`` — mất luôn cả mention, tức là
        đánh đổi recall để tránh một mã sai.  Nhưng chương R không nói "đừng
        gán mã", nó nói "type gold nhiều khả năng là TRIỆU_CHỨNG".  Nên: giữ
        mention, đổi type theo argmax, và hạ ``p_t`` xuống dưới ngưỡng để tầng
        quyết định bỏ trống candidates VÌ ĐÚNG LÝ DO chứ không vì điểm rerank.
        """
        if not self._is_symptom_chapter(best_code):
            return Candidate(span, ConceptType.CHAN_DOAN, codes, prov)
        prov.type_confidence = SYMPTOM_CHAPTER_TYPE_CONFIDENCE
        prov.link_path = f"{prov.link_path}|symptom_chapter_prior"
        prov.evidence["type_prior"] = "icd_chapter_r"
        # kb_rows giữ nguyên để vẫn truy nguyên được quyết định này.
        return Candidate(span, ConceptType.TRIEU_CHUNG, (), prov)


class RxNormExtractor:
    """Conservative drug NER + SCD/SBD reranking + masked-token resolver.

    ``p_t`` giữ mặc định 1.0: một anchor RxNorm khớp nguyên văn TRONG ngữ cảnh
    dùng thuốc là bằng chứng trực tiếp rằng type gold là THUỐC — nhánh này
    không có chương R để nghi ngờ. Nên với thuốc, tầng quyết định không bao giờ
    bỏ trống; nó chỉ chọn kích thước tập.
    """

    name = "rxnorm_v3_2"

    _MASK_RE = re.compile(r"\*{3,}")
    _DOSE_RE = re.compile(
        r"\s+(?P<low>\d+(?:[.,]\d+)?)"
        r"(?:\s*-\s*(?P<high>\d+(?:[.,]\d+)?))?\s*"
        r"(?P<unit>mg|mcg|g|ml|microgam|microgram|miligam|milligram)\b",
        re.IGNORECASE,
    )
    _REGIMEN_SUFFIX_RE = re.compile(
        r"(?P<form>(?:\s+(?:xl|xr|er|sr|cr|dr|oral\s+suspension|"
        r"oral\s+solution|oral\s+tablet|oral\s+capsule)){0,2})"
        r"(?P<dose>\s+\d+(?:[.,]\d+)?(?:\s*-\s*\d+(?:[.,]\d+)?)?\s*"
        r"(?:mg|mcg|g|ml|microgam|microgram|miligam|milligram)\b)?"
        r"(?P<bare_volume>\s+ml\b)?"
        r"(?P<quantity>\s*(?:x|×)\s*\d+(?:[.,]\d+)?"
        r"(?:\s*(?:viên|ống|gói|lần))?)?"
        r"(?P<route>\s*(?:[,;]\s*)?(?:po|iv|im|sc|sl|uống|tiêm|truyền)"
        r"(?:\s+tĩnh\s+mạch)?)?"
        r"(?P<frequency>\s*(?:daily|once\s+daily|once|bid|tid|qid|qhs|qam|"
        r"q\d+h)(?::?prn)?|\s*prn|\s*/\s*ngày|\s+mỗi\s+ngày|"
        r"\s+\d{1,2}h\s+sáng|\s+(?:sáng|chiều|tối)"
        r"(?:\s+(?:trước|sau)\s+ăn)?|\s+(?:trước|sau)\s+ăn)?",
        re.IGNORECASE,
    )
    _PREPOSED_REGIMEN_RE = re.compile(
        r"(?P<regimen>(?:\d+(?:[.,]\d+)?(?:\s*-\s*\d+(?:[.,]\d+)?)?\s*"
        r"(?:mg|mcg|g|ml|microgam|microgram|miligam|milligram)\b"
        r"(?:\s+(?:po|iv|im|sc|sl|uống|tiêm|truyền))?|"
        r"(?:po|iv|im|sc|sl|uống|tiêm|truyền))\s*)$",
        re.IGNORECASE,
    )
    _DRUG_CONTEXT_RE = re.compile(
        r"\b(?:thuốc|uống|dùng|liều|viên|kê đơn|dị ứng|ngừng|tiêm|truyền|"
        r"được cho|điều trị bằng|mg|mcg|microgam|miligam|iv|po|bid)\b",
        re.IGNORECASE,
    )
    _CONTEXTUAL_ANALYTE_DRUG_RE = re.compile(
        r"(?<!\w)glucose\s+(?P<pct>\d+(?:[.,]\d+)?)\s*%\s*x\s*"
        r"(?P<volume>\d+(?:[.,]\d+)?)\s*ml\s+"
        r"(?:truyền|tiêm)(?:\s+tĩnh\s+mạch)?(?!\w)",
        re.IGNORECASE,
    )
    _ANALYTE_OR_AMBIGUOUS = frozenset(
        {
            "albumin", "bilirubin", "caffeine", "calcium", "cholesterol",
            "citrate", "creatinine", "fibrinogen", "glucose", "guaiac",
            "hemoglobin", "insulin", "iron", "lactate", "lipase",
            "magnesium", "oxygen", "potassium", "prothrombin", "protein",
            "sodium", "troponin", "vitamin b12", "vitamin k", "water",
        }
    )
    _UNIT_CANON = {
        "microgam": "mcg", "microgram": "mcg",
        "miligam": "mg", "milligram": "mg",
    }
    _SURFACE_SYNONYMS = {
        "senna": "sennosides, usp",
    }

    @classmethod
    def _amount(cls, value: str, unit: str) -> tuple[float, str]:
        unit = cls._UNIT_CANON.get(unit.casefold(), unit.casefold())
        number = float(value.replace(",", "."))
        if unit == "mcg":
            return number / 1000.0, "mg"
        if unit == "g":
            return number * 1000.0, "mg"
        return number, unit

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        threshold: float = 0.84,
        max_candidates: int = 2,
        contextual_analytes: bool = False,
    ) -> None:
        self.kb = kb
        self.threshold = threshold
        self.max_candidates = max_candidates
        self.contextual_analytes = contextual_analytes
        self._by_first: dict[str, list[str]] = {}
        self._anchor_rows: dict[str, dict] = {}
        self._targets: list[dict] = []
        self._target_by_first: dict[str, list[dict]] = {}
        self._target_by_token: dict[str, list[dict]] = {}
        self._target_by_brand: dict[str, list[dict]] = {}

        for row in kb.rx_aliases:
            alias = row["alias_norm"]
            if int(row.get("is_target", 0)):
                self._targets.append(row)
                first = alias.split(" ", 1)[0]
                self._target_by_first.setdefault(first, []).append(row)
                for token in set(re.findall(r"[^\W_]+", alias)):
                    self._target_by_token.setdefault(token, []).append(row)
                for brand in re.findall(r"\[([^\]]+)\]", alias):
                    self._target_by_brand.setdefault(brand, []).append(row)
            if not int(row.get("is_anchor", 0)):
                continue
            if len(alias) < 4 or len(alias) > 64 or alias in self._ANALYTE_OR_AMBIGUOUS:
                continue
            if alias.startswith(("glucose-", "propionibacterium ")):
                continue
            self._anchor_rows.setdefault(alias, row)

        # Add conservative surface synonyms only when the source KB contains a
        # traceable ingredient anchor.  The canonical phrase is used solely
        # for target lookup; emitted text always remains the raw surface.
        for surface in self._SURFACE_SYNONYMS:
            source = next(
                (
                    row for alias, row in self._anchor_rows.items()
                    if alias.startswith(surface + " ")
                ),
                None,
            )
            if source is not None:
                self._anchor_rows.setdefault(surface, source)

        for alias in self._anchor_rows:
            self._by_first.setdefault(alias.split(" ", 1)[0], []).append(alias)
        for aliases in self._by_first.values():
            aliases.sort(key=len, reverse=True)

    @staticmethod
    def _boundary_ok(text: str, start: int, end: int) -> bool:
        return not (
            (start > 0 and text[start - 1].isalnum())
            or (end < len(text) and text[end].isalnum())
        )

    def _context_ok(self, norm: str, start: int, end: int) -> bool:
        window = norm[max(0, start - 90) : min(len(norm), end + 90)]
        return bool(self._DRUG_CONTEXT_RE.search(window) or self._DOSE_RE.search(" " + window))

    @classmethod
    def _extend_regimen(cls, tref: TextRef, anchor_end: int) -> int:
        """Extend a drug anchor through strength, route and frequency only."""
        match = cls._REGIMEN_SUFFIX_RE.match(tref.norm, anchor_end)
        if not match:
            return anchor_end
        if not any(match.group(name) for name in (
            "form", "dose", "bare_volume", "quantity", "route", "frequency"
        )):
            return anchor_end
        candidate_end = match.end()
        for pos in range(anchor_end, candidate_end):
            raw_piece = tref.raw[tref.n2r[pos]:tref.n2r_end[pos]]
            if "\n" in raw_piece or "\r" in raw_piece:
                return pos
        return candidate_end

    @classmethod
    def _regimen_start(cls, tref: TextRef, anchor_start: int) -> int:
        """Include an immediately preposed dose/route (``80mg po lasix``)."""
        window_start = max(0, anchor_start - 48)
        prefix = tref.norm[window_start:anchor_start]
        match = cls._PREPOSED_REGIMEN_RE.search(prefix)
        if not match:
            return anchor_start
        candidate_start = window_start + match.start("regimen")
        raw_piece = tref.slice_raw(candidate_start, anchor_start)
        return anchor_start if "\n" in raw_piece or "\r" in raw_piece else candidate_start

    def _scan_plain(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        norm = tref.norm
        i, n = 0, len(norm)
        while i < n:
            if not norm[i].isalnum() or (i > 0 and norm[i - 1].isalnum()):
                i += 1
                continue
            j = i
            while j < n and (norm[j].isalnum() or norm[j] in "-_"):
                j += 1
            first = norm[i:j]
            match = next(
                (
                    alias for alias in self._by_first.get(first, ())
                    if norm.startswith(alias, i)
                    and self._boundary_ok(norm, i, i + len(alias))
                ),
                None,
            )
            if match is None:
                i = j + 1
                continue
            end = i + len(match)
            if not self._context_ok(norm, i, end):
                i = end
                continue

            mention_start = self._regimen_start(tref, i)
            mention_end = self._extend_regimen(tref, end)
            rs, re_ = tref.to_raw(mention_start, mention_end)
            span = Span(rs, re_, tref.raw[rs:re_])
            codes, scores, alias = self._link(
                match, tref, mention_start, mention_end
            )
            anchor = self._anchor_rows[match]
            rows = [f"rx-anchor:{anchor['rxcui']}"]
            rows.extend(f"rx:{code}" for code in codes)
            confidence = scores[0] if scores else 0.0
            prov = Provenance(
                extractor=self.name,
                locate_method="rxnorm_anchor_scan",
                link_path="rxnorm_rerank" if codes else "rxnorm_anchor_only",
                kb_rows=rows,
                scores={
                    "confidence": confidence,
                    **{f"code:{c}": s for c, s in zip(codes, scores)},
                },
                evidence={"anchor": match, **({"best_alias": alias} if alias else {})},
            )
            out.append(Candidate(span, ConceptType.THUOC, codes, prov))
            i = mention_end
        return out

    def _scan_contextual_analytes(self, tref: TextRef) -> list[Candidate]:
        """Recover analytes that are unambiguously used as medication.

        ``glucose`` is excluded from ordinary drug anchors because it is most
        often a laboratory analyte.  The corpus also contains the explicit
        infusion ``Glucose 5% x 1000ml truyền tĩnh mạch``.  Five percent
        glucose is 50 mg/mL, which maps directly to the current RxNorm SCD for
        a 1000 mL injection.  Other concentrations/volumes remain unlinked.
        """
        if not self.contextual_analytes:
            return []
        out: list[Candidate] = []
        for match in self._CONTEXTUAL_ANALYTE_DRUG_RE.finditer(tref.norm):
            pct = float(match.group("pct").replace(",", "."))
            volume = float(match.group("volume").replace(",", "."))
            codes = ("1795612",) if pct == 5.0 and volume == 1000.0 else ()
            rs, re_ = tref.to_raw(match.start(), match.end())
            confidence = 0.98 if codes else 0.86
            out.append(Candidate(
                Span(rs, re_, tref.raw[rs:re_]),
                ConceptType.THUOC,
                codes,
                Provenance(
                    extractor="rxnorm_v3",
                    locate_method="contextual_analyte_drug_grammar",
                    link_path=(
                        "contextual_analyte_drug|rxnorm_exact"
                        if codes else "contextual_analyte_drug|unlinked"
                    ),
                    kb_rows=[f"rx:{code}" for code in codes],
                    scores={
                        "confidence": confidence,
                        **{f"code:{code}": confidence for code in codes},
                    },
                    evidence={
                        "percent": f"{pct:g}",
                        "volume_ml": f"{volume:g}",
                        "conversion": "5% w/v = 50 mg/mL" if codes else "unsupported",
                    },
                ),
            ))
        return out

    def _link(
        self, anchor: str, tref: TextRef, start: int, end: int
    ) -> tuple[tuple[str, ...], tuple[float, ...], str]:
        # Linking evidence must be local to this regimen.  The previous broad
        # window could pick up the dose of an adjacent numbered medication.
        norm = tref.norm
        regimen = norm[start:end]
        context_end = min(len(norm), end + 160)
        for pos in range(end, context_end):
            raw_piece = tref.raw[tref.n2r[pos]:tref.n2r_end[pos]]
            if "\n" in raw_piece or "\r" in raw_piece:
                context_end = pos
                break
        tail = norm[end:context_end]
        boundary = re.search(r"\s+\d{1,2}\s*[.]\s+", tail)
        if boundary:
            tail = tail[:boundary.start()]
        context = regimen + tail
        canonical_anchor = self._SURFACE_SYNONYMS.get(anchor, anchor)
        dose = self._DOSE_RE.search(" " + regimen)
        if dose is None:
            contextual_dose = self._DOSE_RE.search(tail)
            if contextual_dose:
                cue_prefix = tail[max(0, contextual_dose.start() - 28):contextual_dose.start()]
                if re.search(r"(?:với\s+liều|liều|hàm\s+lượng)\s*$", cue_prefix):
                    dose = contextual_dose
        strength = dose.group("low").replace(",", ".") if dose else ""
        high_strength = dose.group("high").replace(",", ".") if dose and dose.group("high") else ""
        unit = (
            self._UNIT_CANON.get(dose.group("unit").casefold(), dose.group("unit").casefold())
            if dose else ""
        )
        administration_volume = bool(
            dose and unit == "ml" and re.search(r"\boral\s+(?:solution|suspension)\b", regimen)
        )
        allow_nearest_strength = bool(re.search(
            r"\b(?:po|iv|im|sc|sl|daily|bid|tid|qid|qhs|qam|q\d+h|"
            r"oral\s+(?:tablet|capsule|solution|suspension))\b",
            regimen,
        ))
        query_amounts = [] if administration_volume or not strength else [self._amount(strength, unit)]
        if high_strength:
            query_amounts.append(self._amount(high_strength, unit))

        candidates: list[dict] = []
        candidates.extend(self._target_by_first.get(canonical_anchor.split(" ", 1)[0], ()))
        for token in set(re.findall(r"[^\W_]+", canonical_anchor)):
            candidates.extend(self._target_by_token.get(token, ()))
        candidates.extend(self._target_by_brand.get(anchor, ()))

        ranked: dict[str, tuple[float, str, bool]] = {}
        context_tokens = set(re.findall(r"[^\W_]+", norm_text(context)))
        explicit_parenteral_route = bool(
            {"iv", "im", "sc", "tiêm", "truyền"} & context_tokens
        )
        for row in candidates:
            target = row["alias_norm"]
            exact_brand = row["tty"] == "SBD" and f"[{anchor}]" in target
            name_match = (
                target == canonical_anchor
                or f" {canonical_anchor} " in f" {target} "
                or f"[{anchor}]" in target
            )
            if not name_match:
                continue
            score = 0.55
            exact_strength = False
            row_strength, row_unit = row.get("strength", ""), row.get("unit", "")
            row_amount = self._amount(row_strength, row_unit) if row_strength and row_unit else None
            comparable = [
                amount for amount in query_amounts
                if row_amount and amount[1] == row_amount[1]
            ]
            if comparable and row_amount and any(
                abs(amount[0] - row_amount[0]) < 1e-9 for amount in comparable
            ):
                exact_strength = True
                score += 0.27
            elif comparable and row_amount and len(query_amounts) == 1:
                query_value = comparable[0][0]
                relative_gap = abs(query_value - row_amount[0]) / max(query_value, 1.0)
                single_ingredient = target.count(" mg") + target.count(" mcg") <= 1
                if allow_nearest_strength and relative_gap <= 0.50 and single_ingredient:
                    score += max(0.10, 0.17 - 0.08 * relative_gap)
                    if row_amount[0] <= query_value:
                        score += 0.01
                else:
                    continue
            elif query_amounts:
                continue
            target_tokens = set(target.split())
            score += 0.08 * (len(context_tokens & target_tokens) / max(1, len(context_tokens)))
            form_known = False
            form_supported = False
            if "oral tablet" in target:
                form_known = True
                form_supported = bool(
                    {"viên", "tablet", "pills", "po", "uống"} & context_tokens
                )
            elif "oral capsule" in target:
                form_known = True
                form_supported = bool({"capsule", "nang"} & context_tokens)
            elif "injection" in target or "injectable" in target:
                form_known = True
                form_supported = bool({"iv", "tiêm", "truyền"} & context_tokens)
            elif "oral solution" in target or "suspension" in target:
                form_known = True
                form_supported = bool(
                    {"ml", "siro", "solution", "dịch", "uống"} & context_tokens
                )
            if form_supported:
                score += 0.08
            elif form_known and not (
                exact_brand and exact_strength and not explicit_parenteral_route
            ):
                score -= 0.16
            qualifier_signals = {
                "delayed release": {"delayed", "chậm"},
                "extended release": {"extended", "er", "xl", "sr", "chậm"},
                "disintegrating": {"disintegrating", "tan"},
                "chewable": {"chewable", "nhai"},
                "effervescent": {"effervescent", "sủi"},
                "sublingual": {"sublingual", "ngậm"},
                "enteric coated": {"enteric", "bao"},
            }
            for qualifier, signals in qualifier_signals.items():
                if qualifier in target and not (signals & context_tokens):
                    score -= 0.12
            if (
                ("oral suspension" in target and "oral suspension" in context)
                or ("oral solution" in target and "oral solution" in context)
            ):
                score += 0.12
            if row["tty"] == "SBD" and "[" in target and f"[{anchor}]" not in target:
                score -= 0.15
            if target.count(" mg") + target.count(" mcg") > 1:
                score -= 0.20  # multi-ingredient product without full evidence
            if " / ml" in target and "ml" not in context_tokens:
                score -= 0.15
            score += 0.12 if row["tty"] == "SCD" else 0.06
            score = round(min(score, 1.0), 6)
            code = row["rxcui"]
            old = ranked.get(code)
            if old is None or score > old[0]:
                ranked[code] = (score, target, exact_strength)

        ordered = sorted(ranked.items(), key=lambda item: (-item[1][0], item[0]))
        ordered = [item for item in ordered if item[1][0] >= self.threshold]
        if dose and ordered and not ordered[0][1][2]:
            # A non-exact strength is a dosage-form inference (for example a
            # 1.5 mg regimen using a 1 mg tablet), not genuine ambiguity.
            ordered = ordered[:1]
        ordered = ordered[: self.max_candidates]
        return (
            tuple(code for code, _ in ordered),
            tuple(value[0] for _, value in ordered),
            ordered[0][1][1] if ordered else "",
        )

    def _scan_masked(self, tref: TextRef, plain: list[Candidate]) -> list[Candidate]:
        out: list[Candidate] = []
        linked = [m for m in plain if m.codes]
        distinct = {m.codes for m in linked}
        for match in self._MASK_RE.finditer(tref.norm):
            ns, ne = match.span()
            regimen_end = self._extend_regimen(tref, ne)
            rs, re_ = tref.to_raw(ns, regimen_end)
            span = Span(rs, re_, tref.raw[rs:re_])
            nearest = min(
                linked,
                key=lambda m: min(abs(span.start - m.span.end), abs(m.span.start - span.end)),
                default=None,
            )
            codes: tuple[str, ...] = ()
            rows: list[str] = []
            confidence = 0.0
            evidence: dict[str, str] = {}
            same_length = [
                candidate for candidate in linked
                if len(candidate.provenance.evidence.get("anchor", "")) == len(match.group())
            ]
            length_codes = {candidate.codes for candidate in same_length}
            if len(length_codes) == 1:
                resolved = same_length[0]
                # Coreference must not turn a ranked list into artificial
                # ambiguity by assigning one flat score to every raw code.
                # Propagate only the best product; the normal pipeline filter
                # has not run yet at extractor time.
                codes = resolved.codes[:1]
                confidence = min(0.90, resolved.provenance.scores.get("confidence", 0.0))
                rows = list(resolved.provenance.kb_rows)
                evidence = {
                    "resolved_from": resolved.span.text,
                    "constraint": "same_file_and_mask_length",
                }
            if nearest is not None:
                distance = min(abs(span.start - nearest.span.end), abs(nearest.span.start - span.end))
                if not codes and (distance <= 220 or (len(distinct) == 1 and distance <= 700)):
                    codes = nearest.codes[:1]
                    confidence = min(0.88, nearest.provenance.scores.get("confidence", 0.0))
                    rows = list(nearest.provenance.kb_rows)
                    evidence = {"resolved_from": nearest.span.text, "distance": str(distance)}
            prov = Provenance(
                extractor=self.name,
                locate_method="masked_token",
                link_path=(
                    "masked_length_coreference" if codes and "constraint" in evidence
                    else "masked_coreference" if codes else "masked_unresolved"
                ),
                kb_rows=rows,
                scores={"confidence": confidence, **{f"code:{c}": confidence for c in codes}},
                evidence=evidence,
            )
            out.append(Candidate(span, ConceptType.THUOC, codes, prov))
        return out

    def _apply_anchor_fallback(self, plain: list[Candidate]) -> None:
        """Emit the ingredient/brand RXCUI when no product code was found.

        The v2/v3 policy targeted TTY=SCD because 5/6 codes in the official
        examples are SCD.  But every one of those examples is a *full regimen*
        (``amlodipine 10 mg po daily``).  A bare ``omeprazole`` carries neither
        strength nor dose form, so it cannot have an SCD gold code at all — the
        plausible gold is the ingredient.  Returning ``()`` there is not
        caution, it is the one choice that scores zero for certain: Jaccard of
        an empty prediction against a non-empty gold is 0 by definition, while
        any single code has expected value ``P(correct) >= 0``.

        The anchor is an exact, unambiguous KB alias — all 27,242 anchor
        aliases resolve to exactly one RXCUI — so this carries the same
        epistemic weight as ``gazetteer_exact`` and bypasses the retrieval
        threshold for the same reason.

        MUST run after :meth:`_scan_masked`: masked-token coreference reads
        ``codes`` off the plaintext mentions to infer what a ``*****`` hides,
        and only a *product* match is evidence for that.  An ingredient
        fallback would make every drug mention look like a coreference anchor.
        """
        for candidate in plain:
            if candidate.codes:
                continue
            anchor = candidate.provenance.evidence.get("anchor")
            row = self._anchor_rows.get(anchor) if anchor else None
            if row is None:
                continue
            rxcui = row["rxcui"]
            candidate.codes = (rxcui,)
            candidate.provenance.link_path = "rxnorm_anchor_exact"
            candidate.provenance.scores["confidence"] = 1.0
            candidate.provenance.scores[f"code:{rxcui}"] = 1.0
            candidate.provenance.evidence["anchor_tty"] = row.get("tty", "")

    def extract(self, tref: TextRef) -> list[Candidate]:
        plain = self._scan_plain(tref)
        analytes = self._scan_contextual_analytes(tref)
        masked = self._scan_masked(tref, plain)
        self._apply_anchor_fallback(plain)
        return plain + analytes + masked


class CompositeExtractor:
    """Compose providers while preserving the exact ICD baseline."""

    name = "v2_composite"

    def __init__(
        self, primary: Extractor, *extras: Extractor, name: str = "v2_composite"
    ) -> None:
        self.primary = primary
        self.extras = extras
        self.name = name

    def extract(self, tref: TextRef) -> list[Candidate]:
        exact = self.primary.extract(tref)
        out = list(exact)
        for provider in self.extras:
            for candidate in provider.extract(tref):
                # In medication lists, phrases after ``điều trị`` describe the
                # indication/symptom, not a newly asserted diagnosis.  The
                # organiser example explicitly labels ``táo bón`` this way.
                if (
                    candidate.type is ConceptType.TRIEU_CHUNG
                    and candidate.provenance.evidence.get("type_signal")
                    == "medication_treatment_indication"
                ):
                    out = [
                        old for old in out
                        if not (
                            old.type is ConceptType.CHAN_DOAN
                            and candidate.span.overlaps(old.span)
                        )
                    ]
                # Fuzzy diagnosis retrieval must never replace an exact ICD
                # match.  Other types are left for the pipeline's global
                # longest-span overlap policy.
                if candidate.type is ConceptType.CHAN_DOAN and any(
                    candidate.span.overlaps(old.span)
                    and old.type in {ConceptType.CHAN_DOAN, ConceptType.TRIEU_CHUNG}
                    for old in exact
                ):
                    continue
                if any(
                    candidate.type is old.type
                    and candidate.span.start == old.span.start
                    and candidate.span.end == old.span.end
                    for old in out
                ):
                    continue
                out.append(candidate)
        return out
