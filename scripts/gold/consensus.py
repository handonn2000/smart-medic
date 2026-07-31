"""Weak-supervision label model for building a reference set with no ground truth.

The competition ships no labelled data, so every reference this project measures
against is inferred. `data/proxy_gold_test/` was one LLM pass over 20 documents,
and that origin is its weakness: a single annotator's systematic blind spots are
invisible, because there is nothing to compare against.

The standard answer in weak supervision (Ratner et al., Snorkel, 2016-2020) is
to run several *independent* labelling functions and model their agreement,
rather than trusting any one of them. Agreement between annotators that fail
differently is evidence; agreement with yourself is not.

## What this module does

Three prompts written from different framings — clinician, NER engineer,
test-set builder biased toward recall — annotate the same document. Each is a
labelling function. For every candidate span this module then computes:

    votes      how many annotators proposed this exact (start, end)
    type_agree whether they agreed on the label
    n_types    how many distinct labels were proposed

and assigns a confidence tier. The tiers are not a smoothed score, because a
span either goes into the reference set or it does not, and a 0.63 confidence is
not actionable:

    UNANIMOUS   3/3 annotators, same type   -> reference-grade
    MAJORITY    2/3, same type              -> reference-grade
    SPLIT       >=2 annotators, types differ-> needs adjudication
    SINGLETON   1/3                         -> recall pool only

## Why the tiers matter more than a single number

A reference set has two jobs and they pull apart. Measuring PRECISION needs
spans that are certainly entities — use UNANIMOUS + MAJORITY. Measuring RECALL
needs every entity that plausibly exists — use all four tiers, and read the
result as a lower bound on what the system misses.

Using one pooled set for both is what makes an inferred reference misleading:
singletons drag precision down while their absence inflates recall.

## Boundary disagreement

Annotators frequently agree that something is an entity and disagree where it
ends ("đau bụng" vs "đau bụng vùng hạ sườn phải"). Exact-offset voting scores
that as two singletons, which is wrong — it is one entity with an uncertain
boundary. `cluster_overlapping()` groups spans that overlap at all, so the
cluster can carry the disagreement explicitly instead of hiding it as two weak
votes.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

TIERS = ("UNANIMOUS", "MAJORITY", "SPLIT", "SINGLETON")


def vote(annotations: dict[str, list[dict]]) -> list[dict]:
    """Combine per-annotator span lists for ONE document into tiered candidates.

    `annotations` maps annotator id -> list of {text, type, position}. Returns
    one record per distinct (start, end), carrying the vote count, the proposed
    types, and a tier.
    """
    by_span: dict[tuple[int, int], dict[str, str]] = defaultdict(dict)
    text_of: dict[tuple[int, int], str] = {}
    for who, spans in annotations.items():
        for s in spans:
            key = (s["position"][0], s["position"][1])
            by_span[key][who] = s["type"]
            text_of[key] = s["text"]

    n_annot = len(annotations)
    out = []
    for (start, end), votes in sorted(by_span.items()):
        types = Counter(votes.values())
        top_type, top_n = types.most_common(1)[0]
        n_votes = len(votes)
        if n_votes == n_annot and len(types) == 1:
            tier = "UNANIMOUS"
        elif len(types) > 1 and n_votes >= 2:
            tier = "SPLIT"
        elif n_votes >= 2:
            tier = "MAJORITY"
        else:
            tier = "SINGLETON"
        out.append(
            {
                "text": text_of[(start, end)],
                "position": [start, end],
                "type": top_type,
                "tier": tier,
                "votes": n_votes,
                "n_annotators": n_annot,
                "type_votes": dict(types),
                "voters": sorted(votes),
            }
        )
    return out


def cluster_overlapping(candidates: list[dict]) -> list[list[dict]]:
    """Group candidates whose character ranges overlap at all.

    Exact-offset voting cannot tell "two annotators disagree about where this
    entity ends" from "two annotators found two different weak entities". A
    cluster with several members and only singleton votes inside it is the
    former, and should be adjudicated on boundary rather than discarded.
    """
    clusters: list[list[dict]] = []
    for cand in sorted(candidates, key=lambda c: (c["position"][0], c["position"][1])):
        if clusters and cand["position"][0] < max(
            m["position"][1] for m in clusters[-1]
        ):
            clusters[-1].append(cand)
        else:
            clusters.append([cand])
    return clusters


def pairwise_agreement(annotations: dict[str, list[dict]]) -> dict:
    """Span-level F1 between every pair of annotators, plus type agreement.

    This is the number that says whether the reference set can be trusted at
    all. Two annotators agreeing at F1 0.85 means the task is well-defined and
    their consensus is meaningful; F1 0.45 means they are measuring different
    things and no amount of voting repairs that.
    """
    ids = sorted(annotations)
    sets = {
        i: {(s["position"][0], s["position"][1]): s["type"] for s in annotations[i]}
        for i in ids
    }
    pairs = {}
    for a_i in range(len(ids)):
        for b_i in range(a_i + 1, len(ids)):
            a, b = ids[a_i], ids[b_i]
            sa, sb = set(sets[a]), set(sets[b])
            inter = sa & sb
            p = len(inter) / len(sb) if sb else 0.0
            r = len(inter) / len(sa) if sa else 0.0
            f1 = 2 * p * r / (p + r) if (p + r) else 0.0
            same_type = sum(1 for k in inter if sets[a][k] == sets[b][k])
            pairs[f"{a}-{b}"] = {
                "span_f1": round(f1, 4),
                "shared_spans": len(inter),
                "type_agreement": round(same_type / len(inter), 4) if inter else None,
            }
    return pairs


def summarise(per_doc: dict[str, list[dict]]) -> dict:
    tiers = Counter(c["tier"] for v in per_doc.values() for c in v)
    total = sum(tiers.values())
    return {
        "documents": len(per_doc),
        "candidates": total,
        "by_tier": dict(tiers),
        "reference_grade": tiers["UNANIMOUS"] + tiers["MAJORITY"],
        "needs_adjudication": tiers["SPLIT"],
    }


def write(per_doc: dict[str, list[dict]], out_dir: str | Path) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for doc_id, cands in per_doc.items():
        with (out / f"{doc_id}.json").open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(cands, fh, ensure_ascii=False, indent=1)
        n += len(cands)
    return n
