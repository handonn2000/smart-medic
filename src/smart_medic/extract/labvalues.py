"""L3 · lane R · the lab line. The cheapest recall in the project.

41.7% of gold entities (3,098 / 7,435) are the two lab types, and 94/100 test
files carry a `TÊN: giá trị` line. Dropping either type outright costs 56.42 and
60.41 points. Nothing else in this project buys that much for this little code.

Every rule is in `resources/lab_patterns.yaml`, not here — those patterns get
retuned many times over, and a clinician has to be able to read them.

## What the corpus actually looks like (162 gold files, 1,350 lab results)

    1,343/1,350 (99.5%)  have a TÊN_XÉT_NGHIỆM somewhere before them
    76.3%                sit within 2 characters of that name
    ' ' 771 · ': ' 240   the two separators that matter
    753 of 1,350         are a bare number; 77 a ratio; 28 a percentage

So the rule is **name, then value**, with a narrow window — not "find a colon".
Two lanes implement it, in this order:

1. **Lexicon lane** — a lab name from the gazetteer or from `names:` /
   `abbreviations:`, then a value in the window after it. This is the lane that
   works on prose, which is what `restyled/` (and therefore gold) mostly is:
   `H&H 30 va 39 ổn định, INR 1.86, BUN va creatinine bình thường`.
2. **KV lane** — a `LayoutUnit` whose label is a lab name and whose value is a
   measurement. Only 12.6% of gold lab names line up with a layout label, so this
   lane barely scores on gold — but it is the lane that carries the 94/100 test
   files, so it has to be right even though it cannot be measured here.

## The traps

* **Decimal comma.** `Chol: 4,7 mmol/l`. The `numeric` pattern swallows `,7`, and
  `value_order` puts `numeric` last so `159/49` and `98%` are not shredded first.
  Splitting `4,7` turns one result into two wrong spans; boundary error costs 6.95.
* **Offsets.** All matching happens on `doc.normalized`; every span leaves through
  `Document.to_raw_span()`. `LayoutUnit` offsets arrive in *raw* space, so the KV
  lane converts them in with `to_norm_span()` and back out again.
* **Type leakage.** `Chẩn đoán: viêm phổi` has the exact shape of a lab line.
  `non_lab_labels:` is the gate. A wrong type is penalised twice — one spurious
  entity and one missed entity, across all three score terms.
* **Assertions.** These two types may never carry an assertion (11.59 points).
  This module emits none; `validate/schema.py` enforces it at serialisation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..io.config import load_pipeline, load_yaml, repo_root, require
from ..io.document import Document
from ..layout.kv import LayoutUnit
from .spans import Span, TokenView, tokenize, tokenize_key

__all__ = ["LabRules", "default_lab_rules", "spans", "SOURCE", "NAME_TYPE", "VALUE_TYPE"]

SOURCE = "labvalues"
NAME_TYPE = "TÊN_XÉT_NGHIỆM"
VALUE_TYPE = "KẾT_QUẢ_XÉT_NGHIỆM"

#: Combining marks. Python's `\w` rejects them, so a lookahead written only with
#: `\w` would let an abbreviation match end in the middle of a Vietnamese
#: character on the 41/162 gold files that are not in NFC.
_MARKS = "̀-ͯ᪰-᫿᷀-᷿"
_NOT_WORD_AHEAD = rf"(?![\w{_MARKS}])"
_NOT_WORD_BEHIND = rf"(?<![\w{_MARKS}])"


@dataclass(frozen=True)
class LabRules:
    """The compiled form of `resources/lab_patterns.yaml`. Holds no literal."""

    names: frozenset[tuple[str, ...]]
    names_require_value: frozenset[tuple[str, ...]]
    names_never: frozenset[tuple[str, ...]]
    name_max_tokens: int
    abbreviations: re.Pattern
    abbreviation_requires_value: bool
    non_lab_labels: frozenset[str]
    label_max_tokens: int
    unknown_label_requires_measurement: bool
    value: re.Pattern                 # anchored: separator + value
    value_only: re.Pattern            # anchored: value alone
    continuation: re.Pattern          # anchored: joiner + value
    unit: re.Pattern
    separator_max_chars: int
    max_continuations: int

    @classmethod
    def from_yaml(cls, cfg: dict | None = None) -> "LabRules":
        cfg = cfg or load_yaml(repo_root() / "resources" / "lab_patterns.yaml")

        patterns = require(cfg, "value_patterns")
        order = require(cfg, "value_order")
        numeric_alts = "|".join(f"(?:{require(patterns, k)})" for k in order)
        comparator = require(patterns, "comparator")

        # Longest first, so 'tăng cao' is preferred over 'tăng' — `re` alternation
        # takes the FIRST match, not the longest, so the order is the rule.
        quals = sorted(require(cfg, "qualitative_results"), key=len, reverse=True)
        qual_alts = "|".join(re.escape(q) for q in quals)

        value_body = (
            rf"(?:(?:{comparator})[ \t]*)?(?:{numeric_alts})"
            rf"|(?:{qual_alts}){_NOT_WORD_AHEAD}"
        )
        separator = require(cfg, "separator")
        # One optional line break each side: `restyled/` hard-wraps mid-phrase, so
        # `INR \n1.86` is one lab reading split across two lines. More than one
        # break is a paragraph, and a value on the far side of a paragraph belongs
        # to a different name.
        sep = rf"(?:{separator})(?:\r?\n[ \t]*(?:{separator}))?"

        return cls(
            names=frozenset(
                tokenize_key(n) for n in require(cfg, "names") if tokenize_key(n)
            ),
            names_require_value=frozenset(
                tokenize_key(n)
                for n in require(cfg, "names_require_value")
                if tokenize_key(n)
            ),
            names_never=frozenset(
                tokenize_key(n) for n in require(cfg, "names_never") if tokenize_key(n)
            ),
            name_max_tokens=max(
                (len(tokenize_key(n)) for n in require(cfg, "names")), default=1
            ),
            abbreviations=cls._abbrev_pattern(require(cfg, "abbreviations")),
            abbreviation_requires_value=bool(
                require(cfg, "abbreviation_requires_value")
            ),
            non_lab_labels=frozenset(
                _fold(x) for x in require(cfg, "non_lab_labels")
            ),
            label_max_tokens=int(require(cfg, "label_max_tokens")),
            unknown_label_requires_measurement=bool(
                require(cfg, "unknown_label_requires_measurement")
            ),
            value=re.compile(rf"(?P<sep>{sep})(?P<val>{value_body})", re.IGNORECASE),
            value_only=re.compile(rf"(?P<val>{value_body})", re.IGNORECASE),
            continuation=re.compile(
                rf"(?:{require(cfg, 'continuation')})(?P<val>{value_body})",
                re.IGNORECASE,
            ),
            unit=re.compile(
                "[ \t]*(?:"
                + "|".join(
                    re.escape(u)
                    for u in sorted(require(cfg, "units"), key=len, reverse=True)
                )
                + ")",
                re.IGNORECASE,
            ),
            separator_max_chars=int(require(cfg, "separator_max_chars")),
            max_continuations=int(require(cfg, "max_continuations")),
        )

    @staticmethod
    def _abbrev_pattern(abbrevs: list[str]) -> re.Pattern:
        """CASE-SENSITIVE alternation. `M` and `T` are abbreviations only in caps.

        Matched as literal text rather than as tokens because `H&H` is not one
        token, and lowercasing them would make `m` match every `m` in the document.
        """
        alts = "|".join(
            re.escape(a) for a in sorted(abbrevs, key=len, reverse=True)
        )
        return re.compile(rf"{_NOT_WORD_BEHIND}(?:{alts}){_NOT_WORD_AHEAD}")


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


@lru_cache(maxsize=1)
def default_lab_rules() -> LabRules:
    return LabRules.from_yaml()


@lru_cache(maxsize=1)
def _scores() -> dict:
    return require(load_pipeline(), "extract.recall_floor.labvalues")


# ──────────────────────────────── the lexicon ────────────────────────────────
@lru_cache(maxsize=1)
def _lab_name_keys() -> frozenset[tuple[str, ...]]:
    """Lab-name token tuples: `names:` plus every gazetteer key that is one.

    The gazetteer covers 74.5% of gold lab-name surface forms on its own. The gap
    is almost entirely vital signs — `nhịp thở`, `nhiệt độ`, `mạch`, `cân nặng` —
    which nobody annotates because they are common knowledge. `names:` closes it;
    measured coverage ceiling with both is ~0.90.
    """
    from .aho import load_gazetteer

    rules = default_lab_rules()
    keys = set(rules.names)
    try:
        gaz = load_gazetteer()
    except Exception:  # noqa: BLE001 — the lexicon lane still works without it
        return frozenset(keys - rules.names_never)
    for entry in gaz.entries:
        if entry.type_dist and max(entry.type_dist, key=entry.type_dist.get) == NAME_TYPE:
            keys.add(entry.key)
    return frozenset(keys - rules.names_never)


# ─────────────────────────────── value scanning ───────────────────────────────
def _value_after(
    norm: str, at: int, rules: LabRules
) -> list[tuple[int, int]]:
    """Values reachable from normalised offset `at`. Normalised spans, in order.

    Returns the first value plus up to `max_continuations` more joined by
    `và` / `,` / `/` — `H&H 30 va 39` is two results, not one span covering both.
    """
    m = rules.value.match(norm, at)
    if m is None or len(m.group("sep")) > rules.separator_max_chars:
        return []
    out = [(m.start("val"), m.end("val"))]
    cursor = m.end("val")
    for _ in range(rules.max_continuations):
        nxt = rules.continuation.match(norm, cursor)
        if nxt is None:
            break
        out.append((nxt.start("val"), nxt.end("val")))
        cursor = nxt.end("val")
    return out


def _emit(
    doc: Document, ns: int, ne: int, etype: str, score: float, out: list[Span]
) -> None:
    """Map a normalised span to raw and append it. The only exit door."""
    if ne <= ns:
        return
    start, end = doc.to_raw_span(ns, ne)
    if end <= start:
        return
    out.append(
        Span(
            start=start,
            end=end,
            type_dist={etype: 1.0},
            score=score,
            source=SOURCE,
        )
    )


# ───────────────────────────────── lane 1 · prose ─────────────────────────────
def _lexicon_lane(
    doc: Document, view: TokenView, rules: LabRules, out: list[Span]
) -> None:
    norm = doc.normalized
    sc = _scores()
    name_score = float(require(sc, "name_score"))
    value_score = float(require(sc, "value_score"))
    keys = _lab_name_keys()
    texts = view.texts
    n = len(texts)
    max_len = max(rules.name_max_tokens, max((len(k) for k in keys), default=1))

    i = 0
    while i < n:
        hit = None
        for length in range(min(max_len, n - i), 0, -1):
            if texts[i : i + length] in keys:
                hit = length
                break
        if hit is None:
            i += 1
            continue
        j = i + hit - 1
        values = _value_after(norm, view.tokens[j].end, rules)
        # `mạch` is a lab name in `M 67` and part of a diagnosis in `bệnh mạch
        # vành`. For the names measured to be ambiguous, a following value is the
        # evidence; without it the hit is dropped rather than guessed.
        if not values and texts[i : j + 1] in rules.names_require_value:
            i = j + 1
            continue
        _emit(doc, view.tokens[i].start, view.tokens[j].end, NAME_TYPE, name_score, out)
        for vs, ve in values:
            _emit(doc, vs, ve, VALUE_TYPE, value_score, out)
        i = j + 1


def _abbreviation_lane(
    doc: Document, rules: LabRules, out: list[Span]
) -> None:
    """`Dấu sinh tồn: M67 HA 159/49 … thở 18.` — the name is one or two capitals.

    Case-sensitive, and (by `abbreviation_requires_value`) only accepted when a
    value follows. Without that guard `M` matches every capital M in the document.
    """
    norm = doc.normalized
    sc = _scores()
    name_score = float(require(sc, "abbrev_name_score"))
    value_score = float(require(sc, "value_score"))

    for m in rules.abbreviations.finditer(norm):
        values = _value_after(norm, m.end(), rules)
        if rules.abbreviation_requires_value and not values:
            continue
        _emit(doc, m.start(), m.end(), NAME_TYPE, name_score, out)
        for vs, ve in values:
            _emit(doc, vs, ve, VALUE_TYPE, value_score, out)


# ────────────────────────────── lane 2 · KV units ─────────────────────────────
def _kv_lane(
    doc: Document,
    view: TokenView,
    units: tuple[LayoutUnit, ...],
    rules: LabRules,
    out: list[Span],
) -> None:
    norm = doc.normalized
    sc = _scores()
    known_score = float(require(sc, "kv_known_label_score"))
    unknown_score = float(require(sc, "kv_unknown_label_score"))
    value_score = float(require(sc, "value_score"))
    keys = _lab_name_keys()

    for unit in units:
        if unit.label_span is None or unit.value_span is None:
            continue
        label = _fold(unit.label)
        if not label or label in rules.non_lab_labels:
            continue

        label_key = tokenize_key(label)
        if not label_key or len(label_key) > rules.label_max_tokens:
            continue
        known = label_key in keys

        # LayoutUnit offsets are RAW. Everything below is normalised space.
        vs_norm, ve_norm = doc.to_norm_span(*unit.value_span)
        m = rules.value_only.match(norm, vs_norm, ve_norm)
        if m is None:
            continue
        if not known:
            if not rules.unknown_label_requires_measurement:
                continue
            # An unknown label is a lab name only if its value is a measurement:
            # a number that either fills the whole value or is followed by a unit.
            tail = rules.unit.match(norm, m.end(), ve_norm)
            reach = tail.end() if tail else m.end()
            if norm[reach:ve_norm].strip():
                continue

        ls_norm, le_norm = doc.to_norm_span(*unit.label_span)
        _emit(doc, ls_norm, le_norm, NAME_TYPE, known_score if known else unknown_score, out)
        _emit(doc, m.start(), m.end(), VALUE_TYPE, value_score, out)
        cursor = m.end()
        nxt = rules.continuation.match(norm, cursor, ve_norm)
        while nxt is not None:
            _emit(doc, nxt.start("val"), nxt.end("val"), VALUE_TYPE, value_score, out)
            cursor = nxt.end("val")
            nxt = rules.continuation.match(norm, cursor, ve_norm)


# ───────────────────────────────── entry point ────────────────────────────────
def spans(
    doc: Document,
    view: TokenView | None = None,
    units: tuple[LayoutUnit, ...] = (),
    rules: LabRules | None = None,
) -> list[Span]:
    """Lab names and lab results in `doc`, on `doc.raw`, non-overlapping.

    Applies no threshold. Emits no assertions — the two lab types may not carry
    one, and that constraint is worth 11.59 points.
    """
    view = view if view is not None else tokenize(doc)
    r = rules or default_lab_rules()

    out: list[Span] = []
    _lexicon_lane(doc, view, r, out)
    _abbreviation_lane(doc, r, out)
    _kv_lane(doc, view, units, r, out)
    return _resolve(out)


def _resolve(found: list[Span]) -> list[Span]:
    """Leftmost-longest sweep. 0/7435 gold spans are nested, so neither are ours.

    Ties break on `(start, -length, type, score)` — deterministic, because two
    runs of the same commit that disagree are two different submissions.
    """
    found.sort(key=lambda s: (s.start, -s.length, s.argmax_type(), -s.score))
    out: list[Span] = []
    reach = -1
    for span in found:
        if span.start < reach:
            continue
        out.append(span)
        reach = span.end
    return out
