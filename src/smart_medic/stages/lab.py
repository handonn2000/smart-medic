"""Rule-based laboratory observation extraction for the no-training v3 path.

The task schema separates an observation name from its result.  This module
therefore emits adjacent ``TÊN_XÉT_NGHIỆM`` and ``KẾT_QUẢ_XÉT_NGHIỆM`` spans
instead of treating a complete line as one entity.  Matching happens on
``TextRef.norm`` and every span is mapped back to the untouched raw text.
"""

from __future__ import annotations

import re

from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef
from .extract import Candidate


# Corpus-derived bilingual test names and abbreviations.  These are phrase
# anchors, not codes: laboratory types must always have empty candidates.
_TEST_NAMES = (
    "tổng phân tích nước tiểu", "khí máu động mạch", "thời gian prothrombin",
    "thời gian thromboplastin", "nghiệm pháp gắng sức", "điện giải đồ",
    "điện tâm đồ", "chụp x-quang ngực", "chụp x quang ngực",
    "chụp ct sọ não", "cấy nước tiểu", "phân tích nước tiểu",
    "xét nghiệm chức năng gan", "xét nghiệm phân", "cấy máu",
    "bilirubin toàn phần", "bilirubin trực tiếp", "ldl-cholesterol",
    "hdl-cholesterol", "ldl cholesterol", "hdl cholesterol",
    "tỷ lệ prothrombin", "tỷ số de ritis", "glucose máu",
    "creatinin máu", "troponin ths", "siêu âm bụng có doppler",
    "siêu âm bụng", "siêu âm", "x-quang ngực", "x quang ngực",
    "fibrinogen", "prothrombin", "thromboplastin", "creatinine",
    "creatinin", "triglyceride", "triglycerid", "cholesterol",
    "bilirubin", "hemoglobin", "hematocrit", "ferritin", "troponin",
    "protein niệu 24h", "protein niệu", "protein máu", "albumin máu",
    "glucose", "albumin", "protein", "lactat", "lactate", "nitrite",
    "bạch cầu", "hồng cầu", "tiểu cầu", "ure", "urê", "natri", "kali",
    "calci", "calcium", "chloride", "đường huyết", "huyết áp",
    "wbc", "rbc", "hgb", "hct", "plt", "neut", "lymph", "crp", "ldl", "hdl",
    "got", "gpt", "ggt", "ast", "alt", "alp", "inr", "aptt", "pt", "tq",
    "hba1c", "bnp", "hco3", "po2", "pco2", "spo2", "ph", "bun", "hct", "hst",
    "ecg", "ctm", "shm", "na+", "k+", "cl-", "ca++", "ha",
)

_NAME_ALT = "|".join(sorted((re.escape(value) for value in _TEST_NAMES), key=len,
                             reverse=True))
_NAME_RE = re.compile(rf"(?<![\wăâđêôơư])(?:{_NAME_ALT})(?![\wăâđêôơư])")

_UNIT = (
    r"%|mmhg|mmol\s*/\s*l|micromol\s*/\s*l|[µμ]mol\s*/\s*l|mg\s*/\s*dl|"
    r"mg\s*/\s*l|mcg\s*/\s*l|"
    r"g\s*/\s*l|u\s*/\s*l|iu\s*/\s*l|ng\s*/\s*ml|pg\s*/\s*ml|"
    r"g\s*/\s*dl|10\^?\d+\s*/\s*l|m?eq\s*/\s*l|ml|g|mg|mcg"
)
_NUMBER = r"(?:[<>≤≥]\s*)?\d+(?:[.,]\d+)?(?:\s*[-/]\s*\d+(?:[.,]\d+)?)?"
_QUALITATIVE = (
    r"không\s+có\s+gì\s+đáng\s+chú\s+ý|không\s+phát\s+hiện\s+bất\s+thường|"
    r"âm\s+tính(?:\s*x\s*\d+)?|dương\s+tính|bình\s+thường|bất\s+thường|"
    r"dưới\s+ngưỡng(?:\s+điều\s+trị)?|trên\s+ngưỡng(?:\s+điều\s+trị)?|"
    r"tăng|giảm|thô|rõ|đều|ổn\s+định|không\s+rõ|\(\s*[+−-]\s*\)"
)
_VALUE_RE = re.compile(
    rf"(?P<qual>{_QUALITATIVE})|(?P<num>{_NUMBER})(?:\s*(?P<unit>{_UNIT}))?"
)
_QUAL_RE = re.compile(_QUALITATIVE)

_LAB_CONTEXT_RE = re.compile(
    r"\b(?:xét\s*nghiệm|cận\s+lâm\s+sàng|kết\s+quả|sinh\s+hóa|huyết\s+học|"
    r"đông\s+máu|định\s+lượng|đo\s+hoạt\s+độ|chụp|siêu\s+âm|cấy|"
    r"điện\s+tâm\s+đồ|ecg)\b"
)
_DRUG_CONTEXT_RE = re.compile(
    r"\b(?:uống|viên|tiêm|truyền|pha\s+vào|liều|thuốc)\b|\bx\s*\d+\s*ml\b"
)
_PAIR_PREFIX_RE = re.compile(
    r"^\s*(?:\([^)]{0,48}\)\s*)?(?P<relation>\:|=|-|là\b|bằng\b|"
    r"có\s+kết\s+quả\b|kết\s+quả\b|ghi\s+nhận\b|cho\s+thấy\b)?\s*"
)
_HARD_BREAK_RE = re.compile(r"[.!?]\s|\b(?:nhưng|tuy\s+nhiên)\b")


class LabObservationExtractor:
    """Extract test names and quantitative or qualitative result values."""

    name = "lab_observation_v3"

    @staticmethod
    def _candidate(
        tref: TextRef, ns: int, ne: int, ctype: ConceptType, role: str
    ) -> Candidate:
        rs, re_ = tref.to_raw(ns, ne)
        span = Span(rs, re_, tref.raw[rs:re_])
        return Candidate(
            span=span,
            type=ctype,
            provenance=Provenance(
                extractor=LabObservationExtractor.name,
                locate_method="normalized_lab_grammar",
                link_path="lab_name" if role == "name" else "lab_value",
                scores={"confidence": 0.96 if role == "value" else 0.92},
                evidence={"observation_role": role},
            ),
        )

    @staticmethod
    def _near_lab_context(norm: str, start: int, end: int) -> bool:
        window = norm[max(0, start - 100):min(len(norm), end + 100)]
        return bool(_LAB_CONTEXT_RE.search(window))

    @staticmethod
    def _drug_only_context(norm: str, start: int, end: int) -> bool:
        window = norm[max(0, start - 50):min(len(norm), end + 70)]
        return bool(_DRUG_CONTEXT_RE.search(window) and not _LAB_CONTEXT_RE.search(window))

    @staticmethod
    def _extend_name(tref: TextRef, start: int, end: int) -> int:
        """Include a lab suffix and same-line parenthetical expansion.

        The task examples annotate ``NEUT% (Tỷ lệ % bạch cầu trung
        tính)`` as one test name.  The base lexicon deliberately stays compact;
        this grammar expands the matched abbreviation without inventing text.
        """
        tail = tref.norm[end:min(len(tref.norm), end + 100)]
        match = re.match(r"(?P<pct>%|\s*%)(?P<paren>\s*\([^()]{1,80}\))?", tail)
        if not match:
            match = re.match(r"(?P<paren>\s*\([^()]{1,80}\))", tail)
        if not match:
            return end
        candidate_end = end + match.end()
        raw_extension = tref.slice_raw(end, candidate_end)
        if "\n" in raw_extension or "\r" in raw_extension:
            return end
        return candidate_end

    def extract(self, tref: TextRef) -> list[Candidate]:
        norm = tref.norm
        out: list[Candidate] = []
        paired_values: set[tuple[int, int]] = set()

        for name_match in _NAME_RE.finditer(norm):
            ns, base_ne = name_match.span()
            ne = self._extend_name(tref, ns, base_ne)
            after = norm[ne:min(len(norm), ne + 100)]
            hard_break = _HARD_BREAK_RE.search(after)
            if hard_break:
                after = after[:hard_break.start()]

            prefix = _PAIR_PREFIX_RE.match(after)
            search_start = prefix.end() if prefix else 0
            value_match = _VALUE_RE.search(after, search_start)
            if value_match and value_match.start() - search_start > 6:
                value_match = None
            next_name = _NAME_RE.search(after, search_start)
            if value_match and next_name and next_name.start() < value_match.start():
                value_match = None

            before = norm[max(0, ns - 48):ns]
            prefix_value = None
            for candidate in _QUAL_RE.finditer(before):
                suffix = before[candidate.end():]
                if not suffix.strip():
                    prefix_value = candidate

            has_context = self._near_lab_context(norm, ns, ne)
            if self._drug_only_context(norm, ns, ne) and not has_context:
                continue
            if prefix_value:
                prefix_surface = prefix_value.group().strip()
                generic_prefix = prefix_surface in {
                    "tăng", "giảm", "bình thường", "bất thường", "thô", "rõ",
                    "đều", "ổn định", "không rõ",
                }
                if generic_prefix and not has_context:
                    prefix_value = None
            if value_match and value_match.groupdict().get("qual"):
                relation = prefix.groupdict().get("relation") if prefix else None
                generic_qualitative = value_match.group().strip() in {
                    "tăng", "giảm", "bình thường", "bất thường", "thô", "rõ",
                    "đều", "ổn định", "không rõ",
                }
                if generic_qualitative and not (relation or has_context):
                    value_match = None
                if name_match.group() in {"ha", "huyết áp", "protein"} and not (
                    relation or has_context
                ):
                    value_match = None
            # ``Tăng huyết áp`` is overwhelmingly a diagnosis phrase in this
            # corpus.  Treat BP/HA as an observation only when an actual mmHg
            # measurement follows it.
            if name_match.group() in {"ha", "huyết áp"}:
                has_bp_value = bool(
                    value_match
                    and value_match.groupdict().get("unit")
                    and re.sub(r"\s+", "", value_match.group("unit")) == "mmhg"
                )
                if not has_bp_value:
                    prefix_value = None
                    value_match = None
                    has_context = False
            if not (has_context or value_match or prefix_value):
                continue

            out.append(self._candidate(tref, ns, ne, ConceptType.TEN_XET_NGHIEM, "name"))

            if value_match:
                # A unit-less bare number is accepted only with a separator or
                # explicit laboratory context; this avoids ages and dosages.
                has_unit = bool(value_match.groupdict().get("unit"))
                is_qual = bool(value_match.groupdict().get("qual"))
                explicit_pair = bool(prefix and prefix.groupdict().get("relation"))
                raw_value = tref.slice_raw(
                    ne + value_match.start(), ne + value_match.end()
                )
                unitless_count = (
                    not has_unit and not is_qual
                    and name_match.group().startswith(("cấy", "chụp", "siêu âm"))
                )
                if (
                    "\n" not in raw_value
                    and "\r" not in raw_value
                    and not unitless_count
                    and (is_qual or has_unit or has_context or explicit_pair)
                ):
                    vs, ve = ne + value_match.start(), ne + value_match.end()
                    paired_values.add((vs, ve))
                    out.append(self._candidate(
                        tref, vs, ve, ConceptType.KET_QUA_XET_NGHIEM, "value"
                    ))

            if prefix_value:
                vs = max(0, ns - 48) + prefix_value.start()
                ve = max(0, ns - 48) + prefix_value.end()
                if (vs, ve) not in paired_values:
                    paired_values.add((vs, ve))
                    out.append(self._candidate(
                        tref, vs, ve, ConceptType.KET_QUA_XET_NGHIEM, "value"
                    ))

        unique: dict[tuple[int, int, ConceptType], Candidate] = {}
        for candidate in out:
            key = (candidate.span.start, candidate.span.end, candidate.type)
            unique.setdefault(key, candidate)
        return sorted(
            unique.values(), key=lambda item: (item.span.start, item.span.end, item.type.value)
        )
