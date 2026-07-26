"""Deterministic retrieve-then-rerank providers used by v2.

The competition repository has no labelled training set and v2 must still run
offline.  This module therefore implements a deliberately small lexical
retriever: token overlap supplies recall, character similarity handles spelling
variation, and a deterministic reranker turns the top-k pool into calibrated
scores.  The provider boundary is intentionally compatible with a future
embedding or LLM implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .kb.store import KnowledgeBase
from .normalize import nodiac, norm_text

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TOKEN_SYNONYMS = {"dãn": "giãn"}

# Abbreviations observed in the corpus.  Expanding before retrieval is safer
# than adding short aliases to the global gazetteer, where they would match in
# unrelated contexts.
_ABBREVIATIONS = {
    "g6pd": ("glucose", "6", "phosphate", "dehydrogenase"),
    "copd": ("bệnh", "phổi", "tắc", "nghẽn", "mạn", "tính"),
    "gerd": ("trào", "ngược", "dạ", "dày", "thực", "quản"),
}


def _tokens(value: str, *, fold_diacritics: bool = False) -> tuple[str, ...]:
    base = norm_text(value)
    if fold_diacritics:
        base = nodiac(base)
    out: list[str] = []
    for token in _TOKEN_RE.findall(base):
        token = _TOKEN_SYNONYMS.get(token, token)
        out.extend(_ABBREVIATIONS.get(token, (token,)))
    return tuple(out)


@dataclass(frozen=True)
class RankedCode:
    code: str
    score: float
    alias: str
    token_score: float
    char_score: float


class IcdRetriever:
    """Top-k lexical ICD retrieval followed by a precision-oriented rerank."""

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self._records: list[tuple[str, str, frozenset[str], frozenset[str]]] = []
        self._by_token: dict[str, set[int]] = {}
        for row in kb.icd_aliases:
            if int(row.get("risk_short", 0)):
                continue
            alias = row["alias_norm"]
            toks = frozenset(_tokens(alias))
            folded = frozenset(_tokens(alias, fold_diacritics=True))
            if not folded:
                continue
            idx = len(self._records)
            self._records.append((alias, row["code"], toks, folded))
            for tok in folded:
                self._by_token.setdefault(tok, set()).add(idx)

    def retrieve(self, mention: str, *, top_k: int = 5) -> list[RankedCode]:
        qnorm = nodiac(norm_text(mention))
        qtoks = frozenset(_tokens(mention))
        qfolded = frozenset(_tokens(mention, fold_diacritics=True))
        raw_tokens = frozenset(_TOKEN_RE.findall(qnorm))
        expanded_abbreviations = [
            frozenset(expansion)
            for token, expansion in _ABBREVIATIONS.items()
            if token in raw_tokens
        ]
        if not qnorm or not qtoks:
            return []

        pool: set[int] = set()
        for tok in qfolded:
            pool.update(self._by_token.get(tok, ()))
        if not pool:
            return []

        by_code: dict[str, RankedCode] = {}
        for idx in pool:
            alias, code, atoks, afolded = self._records[idx]
            exact_inter = len(qtoks & atoks)
            folded_inter = len(qfolded & afolded)
            if not folded_inter:
                continue
            exact_score = 2.0 * exact_inter / (len(qtoks) + len(atoks))
            folded_score = 2.0 * folded_inter / (len(qfolded) + len(afolded))
            token_score = 0.8 * exact_score + 0.2 * folded_score
            alias_folded = nodiac(alias)
            char_score = SequenceMatcher(None, qnorm, alias_folded).ratio()
            containment = exact_inter / min(len(qtoks), len(atoks))
            score = 0.55 * token_score + 0.30 * char_score + 0.15 * containment
            has_expansion = expanded_abbreviations and any(
                expansion <= atoks for expansion in expanded_abbreviations
            )
            if has_expansion:
                score += 0.12
            if len(qtoks) == 1 and qnorm != alias_folded:
                score *= 0.65
            # A candidate that adds unseen qualifiers (for example
            # "bẩm sinh") is dangerous under Jaccard: it is a more specific
            # code than the mention supports.
            extra_penalty = 0.02 if has_expansion else 0.08
            score -= min(0.16, extra_penalty * len(atoks - qtoks))
            score = max(0.0, min(score, 1.0))
            ranked = RankedCode(
                code=code,
                score=round(score, 6),
                alias=alias,
                token_score=round(token_score, 6),
                char_score=round(char_score, 6),
            )
            old = by_code.get(code)
            if old is None or ranked.score > old.score:
                by_code[code] = ranked

        return sorted(
            by_code.values(), key=lambda x: (-x.score, x.code)
        )[:top_k]
