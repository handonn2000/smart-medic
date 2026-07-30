"""L3 · lane R · Aho–Corasick over the gazetteer. No model, no checkpoint.

This is the only recall in the project that does not depend on a trained
checkpoint, which is why it ships before any model lane: if the clock runs out,
this *is* the submission.

Reads `data/artifacts/gazetteer.json`, built by `scripts/build_gazetteer.py` from
`ICD10.csv` (Vietnamese, irreplaceable) + RxNorm IN/PIN/MIN + surface forms mined
from the synthetic and translated silver corpora. `linking/` reads the same
artifact at P5 — build once, two readers. `src/` never imports `scripts/`; the
JSON file is the whole interface.

## The three traps this module is written around

**Nesting.** A substring matcher finds "viêm" inside "viêm phổi" and emits both.
0/7435 gold spans are nested, so nesting is a schema violation, not a style
choice. Resolution is leftmost-longest: candidates are sorted by
`(start, -length)` and swept, so at every position the longest name wins and
nothing overlaps. `validate/schema.py` re-checks this on the written JSON, but by
then it is too late to keep the *right* span — so it is decided here.

**Offsets.** Matching runs on `doc.normalized` (tokenised) and every result goes
through `TokenView.raw_span()`. A gazetteer index that leaks into the output
un-mapped shifts spans by up to 143 characters and raises nothing at all.

**Over-generation.** The gazetteer holds tens of thousands of names, many of them
ordinary Vietnamese words. +10% spurious spans costs 6.10 points, so a hit is not
free: each one is scored by how much evidence it carries (how many tokens, which
source), and `decision/emit.py` applies the gate. This module still applies NO
threshold — it returns every candidate with its score.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..io.config import ConfigError, load_pipeline, load_yaml, repo_root, require
from ..io.document import Document
from ..io.labels import TYPES
from ..layout.lines import split_lines
from ..layout.outline import SectionNode, build_outline
from .spans import Span, TokenView, tokenize, tokenize_key

__all__ = [
    "Gazetteer",
    "GazetteerEntry",
    "load_gazetteer",
    "load_section_prior",
    "section_titles",
    "spans",
    "SOURCE",
]

SOURCE = "aho"

#: `resources/section_type_prior.yaml` — P(type | section header), measured on
#: silver. Read here rather than in `configs/pipeline.yaml` because it is a RULE
#: table, not a threshold (see that file's header for the leakage argument).
_SECTION_PRIOR = "section_type_prior.yaml"

#: How many entries to name in a "gazetteer looks wrong" message. Not a threshold.
_MAX_LISTED = 5


@dataclass(frozen=True)
class GazetteerEntry:
    """One name from the index, already tokenised the document's way."""

    key: tuple[str, ...]
    type_dist: dict[str, float]
    codes: tuple[str, ...]
    source: str

    @property
    def n_tokens(self) -> int:
        return len(self.key)

    @property
    def n_chars(self) -> int:
        return sum(len(t) for t in self.key)


# ──────────────────────────────── the automaton ────────────────────────────────
class TokenAutomaton:
    """Aho–Corasick whose alphabet is tokens, not characters.

    `goto` is a list of dicts keyed by token string. `terminal[s]` holds the
    payload indices of keys ending at state `s`; `dict_link[s]` is the nearest
    proper suffix state that is terminal, so `matches_ending_at()` reports every
    key ending at a position, not just the longest. The longest is what usually
    wins, but the *shorter* one has to stay reachable: when the long name fails a
    phrase-continuity check the short one is the correct fallback.
    """

    __slots__ = ("goto", "fail", "terminal", "dict_link", "n_keys")

    def __init__(self) -> None:
        self.goto: list[dict[str, int]] = [{}]
        self.fail: list[int] = [0]
        self.terminal: list[tuple[int, ...]] = [()]
        self.dict_link: list[int] = [0]
        self.n_keys = 0

    def add(self, key: tuple[str, ...], payload: int) -> None:
        state = 0
        for tok in key:
            nxt = self.goto[state].get(tok)
            if nxt is None:
                nxt = len(self.goto)
                self.goto[state][tok] = nxt
                self.goto.append({})
                self.fail.append(0)
                self.terminal.append(())
                self.dict_link.append(0)
            state = nxt
        self.terminal[state] = self.terminal[state] + (payload,)
        self.n_keys += 1

    def finalise(self) -> None:
        """BFS the failure links, then compress the terminal-suffix chain."""
        queue: deque[int] = deque()
        for nxt in self.goto[0].values():
            self.fail[nxt] = 0
            queue.append(nxt)

        while queue:
            state = queue.popleft()
            f = self.fail[state]
            self.dict_link[state] = f if self.terminal[f] else self.dict_link[f]
            for tok, nxt in self.goto[state].items():
                probe = f
                while probe and tok not in self.goto[probe]:
                    probe = self.fail[probe]
                # `nxt` has depth >= 2 and every candidate here has depth <= 1,
                # so this can never make a state its own failure link.
                self.fail[nxt] = self.goto[probe].get(tok, 0)
                queue.append(nxt)

    def step(self, state: int, tok: str) -> int:
        while state and tok not in self.goto[state]:
            state = self.fail[state]
        return self.goto[state].get(tok, 0)

    def matches_ending_at(self, state: int):
        """Yield payload indices of every key ending at `state`, longest first."""
        node = state
        while node:
            for payload in self.terminal[node]:
                yield payload
            node = self.dict_link[node]

    def __len__(self) -> int:
        return len(self.goto)


# ──────────────────────────────── the gazetteer ────────────────────────────────
@dataclass(frozen=True)
class Gazetteer:
    entries: tuple[GazetteerEntry, ...]
    automaton: TokenAutomaton
    version: int
    counts: dict

    def summary(self) -> str:
        by_source: dict[str, int] = {}
        for e in self.entries:
            by_source[e.source] = by_source.get(e.source, 0) + 1
        detail = " · ".join(f"{k} {v}" for k, v in sorted(by_source.items()))
        return (
            f"gazetteer v{self.version}: {len(self.entries)} keys "
            f"({detail}) · {len(self.automaton)} states"
        )


def _artifact_path() -> Path:
    cfg = require(load_pipeline(), "extract.recall_floor.aho")
    return repo_root() / require(cfg, "gazetteer")


def _rules() -> dict:
    return require(load_pipeline(), "extract.recall_floor.aho")


@lru_cache(maxsize=1)
def load_gazetteer(path: str | None = None) -> Gazetteer:
    """Load and compile the index. Raises rather than degrading to no gazetteer.

    A matcher that silently finds nothing because its index is missing scores the
    same as a matcher that is broken, and looks the same in the logs. So an absent
    artifact is a loud error with the command that rebuilds it.
    """
    cfg = _rules()
    p = Path(path) if path else _artifact_path()
    if not p.exists():
        raise ConfigError(
            f"missing gazetteer artifact {p}\n"
            f"  rebuild it with:  python3 scripts/build_gazetteer.py --out {p}\n"
            f"  (build-time step; `src/` never imports `scripts/`)"
        )

    blob = json.loads(p.read_text(encoding="utf-8"))
    min_chars = int(require(cfg, "min_key_chars"))
    max_tokens = int(require(cfg, "max_key_tokens"))

    merged: dict[tuple[str, ...], GazetteerEntry] = {}
    bad: list[str] = []
    for raw in blob.get("entries", ()):
        key = tokenize_key(raw["k"])
        if not key or sum(len(t) for t in key) < min_chars or len(key) > max_tokens:
            continue
        dist = {k: float(v) for k, v in raw.get("t", {}).items() if k in TYPES}
        if not dist:
            if len(bad) < _MAX_LISTED:
                bad.append(f"{raw['k']!r} has no valid type: {raw.get('t')}")
            continue
        codes = tuple(str(c) for c in raw.get("c", ()))
        source = str(raw.get("s", "unknown"))

        # Two artifact keys can tokenise to the same tuple ("H&H" and "H H").
        # Merge instead of letting whichever came last win: a silent overwrite
        # here loses codes that P5 needs.
        prior = merged.get(key)
        if prior is None:
            merged[key] = GazetteerEntry(key, dist, codes, source)
        else:
            merged[key] = GazetteerEntry(
                key,
                _blend(prior.type_dist, dist),
                tuple(dict.fromkeys(prior.codes + codes)),
                prior.source if prior.source <= source else source,
            )

    if not merged:
        raise ConfigError(
            f"{p}: gazetteer compiled to 0 usable keys "
            f"(min_key_chars={min_chars}, max_key_tokens={max_tokens})"
            + ("\n  sample rejects: " + "; ".join(bad) if bad else "")
        )

    entries = tuple(merged[k] for k in sorted(merged))
    automaton = TokenAutomaton()
    for i, entry in enumerate(entries):
        automaton.add(entry.key, i)
    automaton.finalise()
    return Gazetteer(
        entries=entries,
        automaton=automaton,
        version=int(blob.get("version", 0)),
        counts=blob.get("counts", {}),
    )


def _blend(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    out = {k: (a.get(k, 0.0) + b.get(k, 0.0)) / 2 for k in set(a) | set(b)}
    total = sum(out.values()) or 1.0
    return {k: out[k] / total for k in sorted(out)}


# ─────────────────────────── section-conditioned prior ───────────────────────
_WS = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    """The prior's lookup key. NFC first: 41/162 gold files are not in NFC, and
    without this `khám thực thể` splits into two titles that each fall under
    `min_support` and neither fires."""
    return _WS.sub(" ", unicodedata.normalize("NFC", title)).strip().lower()


@lru_cache(maxsize=1)
def load_section_prior(path: str | None = None) -> tuple[dict[str, dict[str, float]], tuple[str, ...]]:
    """Returns (title -> P(type|title), support). Empty when the file is absent.

    Absent is a legitimate state, unlike a missing gazetteer: with no prior every
    span keeps the gazetteer's context-free distribution, which is exactly the
    behaviour before this table existed. So this degrades, and says so, instead
    of raising.
    """
    p = Path(path) if path else repo_root() / "resources" / _SECTION_PRIOR
    if not p.exists():
        return {}, ()
    cfg = load_yaml(p)
    support = tuple(cfg.get("support") or ())
    table = {
        _norm_title(title): {t: float(v) for t, v in dist.items() if t in support}
        for title, dist in (cfg.get("prior") or {}).items()
    }
    return {k: v for k, v in table.items() if v}, support


def section_titles(doc: Document, lines=None) -> list[tuple[int, int, str]]:
    """(start, end, normalised title) for every section, deepest last.

    Deepest last is what lets the lookup take the LAST match for an offset and
    get the innermost enclosing section without sorting by level again.
    """
    root = build_outline(lines if lines is not None else split_lines(doc), len(doc.raw))
    nodes: list[SectionNode] = sorted(root.walk(), key=lambda n: n.level)
    return [(n.start, n.end, _norm_title(n.title)) for n in nodes]


def _apply_section_prior(
    dist: dict[str, float],
    title: str,
    table: dict[str, dict[str, float]],
    support: tuple[str, ...],
) -> dict[str, float]:
    """Bayes multiply, renormalised WITHIN the prior's support only.

    Mass outside `support` is untouched, so this can never push a span towards or
    away from a lab type — it only redistributes the probability the gazetteer
    had already split between symptom and diagnosis. A span with no mass in the
    support comes back unchanged, and so does one in an unlisted section.
    """
    prior = table.get(title)
    if not prior:
        return dist
    inside = {t: dist[t] for t in support if t in dist}
    mass = sum(inside.values())
    if mass <= 0.0:
        return dist
    weighted = {t: p * prior.get(t, 0.0) for t, p in inside.items()}
    total = sum(weighted.values())
    if total <= 0.0:
        return dist
    out = dict(dist)
    for t, w in weighted.items():
        out[t] = mass * w / total
    return out


# ────────────────────────────────── matching ──────────────────────────────────
@lru_cache(maxsize=1)
def _filler() -> re.Pattern:
    """What may sit between two tokens of one name. A rule, so it is in YAML."""
    return re.compile(require(_rules(), "phrase_filler"))


def _score(entry: GazetteerEntry, cfg: dict) -> float:
    """P(this hit is an entity), from evidence only — never a threshold.

    A one-token ICD name is usually an ordinary Vietnamese word and is the main
    source of spurious spans; a multi-token name, or a form actually observed in
    the annotated corpora, carries far more evidence. The numbers are in
    `configs/pipeline.yaml` so they can be retuned without touching this file.
    """
    base = require(cfg, "source_score")
    score = float(base.get(entry.source, require(cfg, "source_score_default")))
    if entry.n_tokens > 1:
        score += float(require(cfg, "multi_token_bonus"))
    return min(1.0, max(0.0, score))


def spans(
    doc: Document,
    view: TokenView | None = None,
    gazetteer: Gazetteer | None = None,
    lines=None,
) -> list[Span]:
    """Every gazetteer hit in `doc`, leftmost-longest, non-overlapping.

    Returns spans on `doc.raw`. Applies no threshold — `decision/emit.py` does.

    `lines` is passed through to the section prior only, so a caller that already
    split the document does not pay for it twice. The outline is rebuilt here when
    it is omitted, which keeps this callable with `(doc, view)` as before.
    """
    view = view if view is not None else tokenize(doc)
    gaz = gazetteer if gazetteer is not None else load_gazetteer()
    cfg = _rules()
    filler = _filler()
    prior_table, prior_support = load_section_prior()
    sections = section_titles(doc, lines) if prior_table else []

    # ── collect candidates ────────────────────────────────────────────────────
    candidates: list[tuple[int, int, GazetteerEntry]] = []
    state = 0
    for end_i, tok in enumerate(view.texts):
        state = gaz.automaton.step(state, tok)
        for payload in gaz.automaton.matches_ending_at(state):
            entry = gaz.entries[payload]
            start_i = end_i - entry.n_tokens + 1
            if start_i < 0:
                continue
            if not view.spans_one_phrase(start_i, end_i, filler):
                continue
            candidates.append((start_i, end_i, entry))

    # ── leftmost-longest sweep: 0 nested, 0 overlapping ───────────────────────
    # Sort by start, then longest first, then by key so two runs of the same code
    # never disagree. A non-deterministic tie-break would make two builds of the
    # same commit produce different submissions.
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0]), c[2].key))
    out: list[Span] = []
    next_free = 0
    for start_i, end_i, entry in candidates:
        if start_i < next_free:
            continue
        start, end = view.raw_span(start_i, end_i)
        dist = dict(entry.type_dist)
        if prior_table:
            # deepest enclosing section: `sections` is level-sorted, so the last
            # one containing `start` is the innermost
            title = ""
            for s_start, s_end, s_title in sections:
                if s_start <= start < s_end:
                    title = s_title
            dist = _apply_section_prior(dist, title, prior_table, prior_support)
        out.append(
            Span(
                start=start,
                end=end,
                type_dist=dist,
                score=_score(entry, cfg),
                source=SOURCE,
                codes=entry.codes,
            )
        )
        next_free = end_i + 1
    return out
