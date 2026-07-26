"""Opt-in v4 medication normalization.

The submitted v3.3 extractor is deliberately left untouched.  This module
wraps it and applies two narrowly-scoped operations to *unlinked* medication
mentions only:

* exact, reviewed aliases from a separately checksummed CSV source; and
* an exact, unique RxNorm Ingredient (IN) or Brand Name (BN) backoff.

The latter is enabled only in ``hierarchical`` mode.  It does not pretend that
an ingredient is a fully specified clinical drug: the returned TTY is recorded
in provenance so experiments can measure this policy independently.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ..kb.store import KnowledgeBase
from ..normalize import norm_drug, norm_text
from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef
from .extract import Candidate, RxNormExtractor


class MedicationDataError(ValueError):
    """Raised when a reviewed medication alias file is unsafe to consume."""


@dataclass(frozen=True)
class MedicationAttributes:
    """Structured, text-supported medication attributes for review/linking."""

    name: str
    strengths: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    dose_form: str = ""
    route: str = ""
    frequency: str = ""
    quantity: str = ""
    masked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class MedicationAttributeParser:
    """Deterministic, conservative parser for medication review attributes."""

    _MASK_RE = re.compile(r"\*{3,}")
    _STRENGTH_RE = re.compile(
        r"(?<![\w.,])(?P<low>\d+(?:[.,]\d+)?)"
        r"(?:\s*-\s*(?P<high>\d+(?:[.,]\d+)?))?\s*"
        r"(?P<unit>mg|mcg|µg|μg|g|ml|iu|ui|đv|unit|units|meq|mmol|%)(?!\w)",
        re.IGNORECASE,
    )
    _QUANTITY_RE = re.compile(
        r"(?:x|×)\s*(\d+(?:[.,]\d+)?)\s*"
        r"(viên|ống|gói|lọ|chai|lần|tablet|capsule)?\b",
        re.IGNORECASE,
    )
    _FORM_PATTERNS = (
        ("extended release tablet", re.compile(
            r"\b(?:xl|xr|er|sr|cr|viên\s+(?:phóng|giải)\s*thích\s+chậm)\b",
            re.IGNORECASE,
        )),
        ("tablet", re.compile(r"\b(?:viên|tablet|tab)\b", re.IGNORECASE)),
        ("capsule", re.compile(r"\b(?:viên\s+nang|capsule|cap)\b", re.IGNORECASE)),
        ("oral suspension", re.compile(
            r"\b(?:oral\s+suspension|hỗn\s+dịch)\b", re.IGNORECASE
        )),
        ("oral solution", re.compile(
            r"\b(?:oral\s+solution|dung\s+dịch|siro|syrup)\b", re.IGNORECASE
        )),
        ("injection", re.compile(
            r"\b(?:injection|injectable|tiêm|truyền)\b", re.IGNORECASE
        )),
        ("cream", re.compile(r"\b(?:cream|kem\s+bôi|thuốc\s+bôi)\b", re.IGNORECASE)),
        ("patch", re.compile(r"\b(?:patch|miếng\s+dán)\b", re.IGNORECASE)),
    )
    _ROUTE_PATTERNS = (
        ("IV", re.compile(r"\b(?:iv|tĩnh\s+mạch|truyền\s+tm)\b", re.IGNORECASE)),
        ("IM", re.compile(r"\b(?:im|tiêm\s+bắp)\b", re.IGNORECASE)),
        ("SC", re.compile(r"\b(?:sc|dưới\s+da)\b", re.IGNORECASE)),
        ("SL", re.compile(r"\b(?:sl|ngậm\s+dưới\s+lưỡi)\b", re.IGNORECASE)),
        ("PO", re.compile(r"\b(?:po|uống|đường\s+miệng|oral)\b", re.IGNORECASE)),
    )
    _FREQUENCY_RE = re.compile(
        r"\b(?:once\s+daily|daily|bid|tid|qid|qhs|qam|q\d+h|prn|"
        r"mỗi\s+ngày|hàng\s+ngày|ngày\s+\d+\s+lần|"
        r"\d+\s+lần\s*/\s*ngày|sáng|chiều|tối)\b",
        re.IGNORECASE,
    )
    _UNIT_CANON = {
        "µg": "mcg", "μg": "mcg", "ui": "iu", "đv": "iu",
        "unit": "iu", "units": "iu",
    }

    def parse(self, surface: str, *, anchor: str = "") -> MedicationAttributes:
        normalized = norm_text(surface)
        strengths: list[str] = []
        units: list[str] = []
        for match in self._STRENGTH_RE.finditer(normalized):
            low = match.group("low").replace(",", ".")
            high = (match.group("high") or "").replace(",", ".")
            strengths.append(low if not high else f"{low}-{high}")
            raw_unit = match.group("unit").casefold()
            units.append(self._UNIT_CANON.get(raw_unit, raw_unit))

        dose_form = next(
            (name for name, pattern in self._FORM_PATTERNS if pattern.search(normalized)),
            "",
        )
        route = next(
            (name for name, pattern in self._ROUTE_PATTERNS if pattern.search(normalized)),
            "",
        )
        frequency_match = self._FREQUENCY_RE.search(normalized)
        quantity_match = self._QUANTITY_RE.search(normalized)
        return MedicationAttributes(
            name=norm_drug(anchor) if anchor else "",
            strengths=tuple(strengths),
            units=tuple(units),
            dose_form=dose_form,
            route=route,
            frequency=frequency_match.group(0) if frequency_match else "",
            quantity=quantity_match.group(0) if quantity_match else "",
            masked=bool(self._MASK_RE.search(normalized)),
        )


@dataclass(frozen=True)
class DrugAliasRecord:
    alias_norm: str
    rxcui: str
    tty: str
    ingredient: str
    strength: str
    unit: str
    dose_form: str
    source: str
    source_version: str
    license: str
    evidence_level: str
    line_number: int


class DrugAliasStore:
    """Reviewed external aliases, kept outside the immutable runtime KB."""

    REQUIRED_COLUMNS = frozenset({
        "alias", "rxcui", "tty", "ingredient", "strength", "unit",
        "dose_form", "source", "source_version", "license",
        "evidence_level", "review_status",
    })
    ALLOWED_TTYS = frozenset({"IN", "BN", "SCD", "SBD"})
    ALLOWED_EVIDENCE = frozenset({"ingredient", "brand", "product"})

    def __init__(
        self,
        records: tuple[DrugAliasRecord, ...] = (),
        *,
        source_path: Path | None = None,
        sha256: str = "",
    ) -> None:
        self.records = records
        self.source_path = source_path
        self.sha256 = sha256
        by_alias: dict[str, list[DrugAliasRecord]] = {}
        for record in records:
            by_alias.setdefault(record.alias_norm, []).append(record)
        self._by_alias = {
            alias: tuple(sorted(rows, key=lambda row: (row.rxcui, row.line_number)))
            for alias, rows in by_alias.items()
        }
        self.scan_aliases = tuple(sorted(self._by_alias, key=lambda value: (-len(value), value)))

    @classmethod
    def empty(cls) -> "DrugAliasStore":
        return cls()

    @classmethod
    def from_csv(cls, path: Path, kb: KnowledgeBase) -> "DrugAliasStore":
        if path.is_symlink() or not path.is_file():
            raise MedicationDataError(f"drug alias source is not a regular file: {path}")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise MedicationDataError(f"drug alias source must be UTF-8: {path}") from exc

        reader = csv.DictReader(text.splitlines())
        fields = set(reader.fieldnames or ())
        missing = cls.REQUIRED_COLUMNS - fields
        if missing:
            raise MedicationDataError(
                "drug alias source is missing columns: " + ", ".join(sorted(missing))
            )

        records: list[DrugAliasRecord] = []
        for line_number, row in enumerate(reader, start=2):
            if (row.get("review_status") or "").strip().casefold() != "approved":
                continue
            alias = norm_drug((row.get("alias") or "").strip())
            rxcui = (row.get("rxcui") or "").strip()
            tty = (row.get("tty") or "").strip().upper()
            evidence_level = (row.get("evidence_level") or "").strip().casefold()
            if len(alias) < 4:
                raise MedicationDataError(f"line {line_number}: alias is too short")
            if not rxcui.isdigit() or rxcui not in kb.rx_concepts:
                raise MedicationDataError(
                    f"line {line_number}: unknown/current-invalid RxCUI {rxcui!r}"
                )
            actual_tty = kb.rx_concepts[rxcui].get("tty", "")
            if tty not in cls.ALLOWED_TTYS or actual_tty != tty:
                raise MedicationDataError(
                    f"line {line_number}: TTY {tty!r} does not match current KB {actual_tty!r}"
                )
            if evidence_level not in cls.ALLOWED_EVIDENCE:
                raise MedicationDataError(
                    f"line {line_number}: unsupported evidence_level {evidence_level!r}"
                )
            source = (row.get("source") or "").strip()
            source_version = (row.get("source_version") or "").strip()
            license_name = (row.get("license") or "").strip()
            if not source or not source_version or not license_name:
                raise MedicationDataError(
                    f"line {line_number}: source, source_version and license are required"
                )
            records.append(DrugAliasRecord(
                alias_norm=alias,
                rxcui=rxcui,
                tty=tty,
                ingredient=norm_drug((row.get("ingredient") or "").strip()),
                strength=(row.get("strength") or "").strip().replace(",", "."),
                unit=MedicationAttributeParser._UNIT_CANON.get(
                    (row.get("unit") or "").strip().casefold(),
                    (row.get("unit") or "").strip().casefold(),
                ),
                dose_form=norm_drug((row.get("dose_form") or "").strip()),
                source=source,
                source_version=source_version,
                license=license_name,
                evidence_level=evidence_level,
                line_number=line_number,
            ))
        return cls(tuple(records), source_path=path, sha256=digest)

    @staticmethod
    def _compatible(record: DrugAliasRecord, attrs: MedicationAttributes) -> bool:
        if record.strength:
            pairs = set(zip(attrs.strengths, attrs.units))
            if (record.strength, record.unit) not in pairs:
                return False
        if record.dose_form and (
            not attrs.dose_form
            or norm_drug(record.dose_form) != norm_drug(attrs.dose_form)
        ):
            return False
        return True

    def resolve(
        self,
        alias: str,
        attrs: MedicationAttributes,
        *,
        specificity: str,
    ) -> DrugAliasRecord | None:
        rows = [
            row for row in self._by_alias.get(norm_drug(alias), ())
            if self._compatible(row, attrs)
            and (specificity == "hierarchical" or row.tty in {"SCD", "SBD"})
        ]
        by_code = {row.rxcui: row for row in rows}
        return next(iter(by_code.values())) if len(by_code) == 1 else None

    def manifest_entry(self) -> dict | None:
        if self.source_path is None:
            return None
        return {
            "path": self.source_path.name,
            "sha256": self.sha256,
            "approved_rows": len(self.records),
        }


class _HierarchyIndex:
    """Exact current IN/BN lookup built from the already verified RxNorm KB."""

    ALLOWED_TTYS = frozenset({"IN", "BN"})

    def __init__(self, kb: KnowledgeBase) -> None:
        by_alias: dict[str, dict[str, str]] = {}
        for row in kb.rx_aliases:
            tty = row.get("tty", "")
            rxcui = row.get("rxcui", "")
            if tty not in self.ALLOWED_TTYS or rxcui not in kb.rx_concepts:
                continue
            by_alias.setdefault(row["alias_norm"], {})[rxcui] = tty
        self._by_alias = by_alias

    def resolve(self, alias: str) -> tuple[str, str] | None:
        choices = self._by_alias.get(norm_drug(alias), {})
        if len(choices) != 1:
            return None
        return next(iter(choices.items()))


class V4MedicationExtractor:
    """V3-compatible medication extractor with opt-in exact v4 backoff."""

    _MASK_RE = re.compile(r"\*{3,}")

    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        specificity: str = "strict",
        alias_store: DrugAliasStore | None = None,
        threshold: float = 0.84,
        max_candidates: int = 2,
        contextual_analytes: bool = True,
    ) -> None:
        if specificity not in {"strict", "hierarchical"}:
            raise ValueError("specificity must be strict or hierarchical")
        self.kb = kb
        self.specificity = specificity
        self.alias_store = alias_store or DrugAliasStore.empty()
        self.base = RxNormExtractor(
            kb,
            threshold=threshold,
            max_candidates=max_candidates,
            contextual_analytes=contextual_analytes,
        )
        self.parser = MedicationAttributeParser()
        self.hierarchy = _HierarchyIndex(kb)
        self.name = f"rxnorm_v4_{specificity}"

    @staticmethod
    def _copy_provenance(provenance: Provenance) -> Provenance:
        return Provenance(
            extractor=provenance.extractor,
            locate_method=provenance.locate_method,
            link_path=provenance.link_path,
            kb_rows=list(provenance.kb_rows),
            scores=dict(provenance.scores),
            evidence=dict(provenance.evidence),
        )

    def _linked_candidate(
        self,
        candidate: Candidate,
        *,
        rxcui: str,
        tty: str,
        path: str,
        confidence: float,
        source_ref: str = "",
    ) -> Candidate:
        provenance = self._copy_provenance(candidate.provenance)
        provenance.extractor = self.name
        provenance.locate_method += "|v4_exact_backoff"
        provenance.link_path = path
        provenance.kb_rows.append(f"rx:{rxcui}")
        if source_ref:
            provenance.kb_rows.append(source_ref)
        provenance.scores = {
            "confidence": confidence,
            f"code:{rxcui}": confidence,
        }
        provenance.evidence.update({
            "specificity_tty": tty,
            "specificity_policy": self.specificity,
        })
        return Candidate(candidate.span, ConceptType.THUOC, (rxcui,), provenance)

    def _enrich(self, candidate: Candidate) -> Candidate:
        if candidate.codes or self._MASK_RE.search(candidate.span.text):
            return candidate
        anchor = candidate.provenance.evidence.get("anchor", "")
        attrs = self.parser.parse(candidate.span.text, anchor=anchor)

        external = self.alias_store.resolve(
            anchor, attrs, specificity=self.specificity
        ) if anchor else None
        if external is not None:
            return self._linked_candidate(
                candidate,
                rxcui=external.rxcui,
                tty=external.tty,
                path=f"rxnorm_external_alias|{self.specificity}",
                confidence=0.96,
                source_ref=(
                    f"drug-alias:{self.alias_store.sha256[:16]}:{external.line_number}"
                ),
            )

        if self.specificity == "hierarchical" and anchor:
            resolved = self.hierarchy.resolve(anchor)
            if resolved is not None:
                rxcui, tty = resolved
                return self._linked_candidate(
                    candidate,
                    rxcui=rxcui,
                    tty=tty,
                    path="rxnorm_hierarchical_backoff",
                    confidence=0.92 if tty == "IN" else 0.94,
                )
        return candidate

    @staticmethod
    def _boundary_ok(text: str, start: int, end: int) -> bool:
        return not (
            (start > 0 and text[start - 1].isalnum())
            or (end < len(text) and text[end].isalnum())
        )

    def _scan_external(
        self, tref: TextRef, existing: list[Candidate]
    ) -> list[Candidate]:
        out: list[Candidate] = []
        for alias in self.alias_store.scan_aliases:
            start = 0
            while True:
                start = tref.norm.find(alias, start)
                if start < 0:
                    break
                alias_end = start + len(alias)
                if not self._boundary_ok(tref.norm, start, alias_end):
                    start = alias_end
                    continue
                regimen_start = self.base._regimen_start(tref, start)
                regimen_end = self.base._extend_regimen(tref, alias_end)
                rs, re_ = tref.to_raw(regimen_start, regimen_end)
                span = Span(rs, re_, tref.raw[rs:re_])
                if (
                    not self.base._context_ok(tref.norm, start, alias_end)
                    or any(span.overlaps(candidate.span) for candidate in existing + out)
                ):
                    start = alias_end
                    continue
                # The v3 span grammar intentionally stops after its supported
                # regimen suffixes.  A reviewed source may require an
                # attribute immediately after that span (for example
                # ``81 mg viên uống``), so inspect only the remainder of the
                # same short clause for compatibility without enlarging the
                # emitted raw span.
                attribute_end = min(len(tref.norm), regimen_end + 96)
                for pos in range(regimen_end, attribute_end):
                    raw_piece = tref.raw[tref.n2r[pos]:tref.n2r_end[pos]]
                    if "\n" in raw_piece or "\r" in raw_piece or tref.norm[pos] in ".;":
                        attribute_end = pos
                        break
                attribute_text = tref.slice_raw(regimen_start, attribute_end)
                attrs = self.parser.parse(attribute_text, anchor=alias)
                record = self.alias_store.resolve(
                    alias, attrs, specificity=self.specificity
                )
                codes = (record.rxcui,) if record else ()
                confidence = 0.96 if record else 0.86
                rows = [] if record is None else [
                    f"rx:{record.rxcui}",
                    f"drug-alias:{self.alias_store.sha256[:16]}:{record.line_number}",
                ]
                evidence = {
                    "anchor": alias,
                    "specificity_policy": self.specificity,
                    **({"specificity_tty": record.tty} if record else {}),
                }
                out.append(Candidate(
                    span,
                    ConceptType.THUOC,
                    codes,
                    Provenance(
                        extractor=self.name,
                        locate_method="reviewed_external_alias_scan",
                        link_path=(
                            f"rxnorm_external_alias|{self.specificity}"
                            if record else "rxnorm_external_alias|unlinked"
                        ),
                        kb_rows=rows,
                        scores={
                            "confidence": confidence,
                            **{f"code:{code}": confidence for code in codes},
                        },
                        evidence=evidence,
                    ),
                ))
                start = alias_end
        return out

    def extract(self, tref: TextRef) -> list[Candidate]:
        base = self.base.extract(tref)
        enriched = [self._enrich(candidate) for candidate in base]
        return enriched + self._scan_external(tref, enriched)
