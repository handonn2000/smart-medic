"""Measurements that need no reference labels at all.

Every number this project trusts comes from one of two places: the leaderboard
(five submissions, each costing an attempt) or an inferred reference set (one
LLM pass, unvalidated). Both are scarce or suspect. These checks are neither —
they are properties of the output alone, or of the output against a controlled
perturbation of the input, so they can run on every build for free.

None of them measures accuracy. What they measure is whether the system is
*self-consistent*, and inconsistency is a strict lower bound on error: a
pipeline that labels the same string two different ways in the same document is
wrong at least once, and you learn that without knowing which way is right.

## 1. Self-consistency (`self_consistency`)

Same surface form, same document, different label — or labelled here and
skipped there. Both are errors by construction. Measured on the shipped E build
this catches real defects that the reference set also flags, at zero cost.

## 2. Metamorphic invariance (`metamorphic_swap`)

From metamorphic testing (Chen et al. 1998), the standard tool when an oracle is
unavailable. Take a real sentence, substitute one entity for another of the same
class drawn from the knowledge base, and the label structure must not change:
swapping "amlodipine" for "metformin" keeps a THUỐC span at that position. A
prediction that changes anything except the swapped span has revealed a
brittleness, and no reference set was needed to see it.

This is also the sound version of the "generate text from labels" idea. Pure
label-to-text generation is a closed loop: the labels come from ICD-10 and
RxNorm, so the generated text can only contain phrasings those catalogues
already know. Measured against the real test set, the project's own 162-document
synthetic corpus covers 24.7% of the surface forms that actually appear — the
remaining 75% are how Vietnamese patients and clinicians write, which no
catalogue contains. Swapping entities *inside real sentences* keeps the real
phrasing and gets an exact label for the swapped span.

## 3. Cross-lane agreement (`lane_agreement`)

Where two independent extractors fire on the same span, agreement is weak
evidence of correctness and disagreement is a guaranteed error in one of them.
Free to compute during a run, and it localises the defect to a lane.

## 4. Density profiling (`density_outliers`)

Documents whose output density sits far from the corpus median are worth
inspecting — usually a genre the extractor handles badly, not a genuinely
sparse document.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter, defaultdict


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s).lower().strip())


def self_consistency(doc_text: str, records: list[dict]) -> dict:
    """Contradictions inside one document. Every hit is an error, no oracle needed."""
    by_surface: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        by_surface[_norm(r["text"])][r["type"]] += 1

    type_conflicts = {s: dict(c) for s, c in by_surface.items() if len(c) > 1}

    coverage_gaps = []
    lowered = _norm(doc_text)
    for surface, counter in by_surface.items():
        if len(surface) < 4:
            continue  # a 3-character string matches inside too many words
        occurrences = len(re.findall(re.escape(surface), lowered))
        labelled = sum(counter.values())
        if occurrences > labelled:
            coverage_gaps.append(
                {"surface": surface, "labelled": labelled, "occurrences": occurrences}
            )

    return {
        "type_conflicts": type_conflicts,
        "n_type_conflicts": len(type_conflicts),
        "coverage_gaps": sorted(
            coverage_gaps, key=lambda g: g["labelled"] - g["occurrences"]
        ),
        "n_coverage_gaps": len(coverage_gaps),
    }


def swappable(doc_text: str, span: dict) -> bool:
    """Is this span safe to substitute?

    Two traps, both found by running the swap and reading the failures:

    * The span must not be part of a longer name. `data/test/95.txt` has
      "- mucinex d" — "Mucinex D" is a real product — and the extractor takes
      only "mucinex". Substituting those 7 characters yields
      "thuốc chống dị ứng d", and the pipeline then correctly labels the whole
      thing. That is the TEST being wrong, not the system, and without this
      guard it reads as a false positive.
    * The span must sit on word boundaries, or the substitution splices into a
      neighbouring token.
    """
    start, end = span["position"]
    if start > 0 and doc_text[start - 1].isalnum():
        return False
    if end < len(doc_text) and doc_text[end].isalnum():
        return False
    line_end = doc_text.find("\n", end)
    line_end = len(doc_text) if line_end < 0 else line_end
    tail = doc_text[end:line_end].strip()
    # A one- or two-character alphanumeric tail on the same line is usually the
    # rest of a product name: "Mucinex D", "Tylenol PM", "Augmentin 625".
    return not (tail and len(tail) <= 2 and tail.isalnum())


def metamorphic_swap(doc_text: str, span: dict, replacement: str) -> tuple[str, dict]:
    """Substitute one entity, return the mutated text and the expected span.

    The expected label is exact by construction: same type, same start offset,
    end shifted by the length difference. Any deviation in the prediction is a
    defect, and the surrounding sentence is still real Vietnamese.
    """
    start, end = span["position"]
    mutated = doc_text[:start] + replacement + doc_text[end:]
    expected = {
        "text": replacement,
        "type": span["type"],
        "position": [start, start + len(replacement)],
    }
    return mutated, expected


def check_swap(predicted: list[dict], expected: dict, original: list[dict]) -> dict:
    """Did the swap change only what it should have?

    Three failure modes, each independently informative: the swapped entity was
    missed, its type changed, or spans elsewhere in the document moved.
    """
    hit = next(
        (
            p
            for p in predicted
            if p["position"][0] == expected["position"][0]
            and p["position"][1] == expected["position"][1]
        ),
        None,
    )
    shift = len(expected["text"]) - (
        original[0]["position"][1] - original[0]["position"][0]
        if original
        else len(expected["text"])
    )

    before = {
        (r["position"][0], r["type"])
        for r in original
        if r["position"][1] <= expected["position"][0]
    }
    after = {
        (p["position"][0], p["type"])
        for p in predicted
        if p["position"][1] <= expected["position"][0]
    }
    return {
        "swapped_found": hit is not None,
        "type_preserved": bool(hit and hit["type"] == expected["type"]),
        "prefix_stable": before == after,
        "collateral": sorted(before ^ after)[:5],
    }


def lane_agreement(spans: list) -> dict:
    """Where two lanes propose the same offsets, do they agree on type?"""
    by_offset: dict[tuple[int, int], dict[str, str]] = defaultdict(dict)
    for s in spans:
        by_offset[(s.start, s.end)][s.source] = s.argmax_type()
    both = {k: v for k, v in by_offset.items() if len(v) > 1}
    disagree = {k: v for k, v in both.items() if len(set(v.values())) > 1}
    return {
        "spans_with_multiple_lanes": len(both),
        "lane_disagreements": len(disagree),
        "examples": [
            {"offsets": list(k), "by_lane": v} for k, v in list(disagree.items())[:10]
        ],
    }


def density_outliers(per_doc_counts: dict[str, int], per_doc_chars: dict[str, int],
                     z: float = 2.0) -> list[dict]:
    """Documents whose output density is far from the corpus median."""
    dens = {
        k: 1000 * per_doc_counts[k] / per_doc_chars[k]
        for k in per_doc_counts
        if per_doc_chars.get(k)
    }
    if len(dens) < 4:
        return []
    values = list(dens.values())
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values]) or 1e-9
    return sorted(
        (
            {"doc": k, "density": round(v, 2), "robust_z": round((v - med) / (1.4826 * mad), 2)}
            for k, v in dens.items()
            if abs(v - med) / (1.4826 * mad) > z
        ),
        key=lambda d: -abs(d["robust_z"]),
    )
