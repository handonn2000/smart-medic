# V4 research directions — where the missing 78 points actually are

**Date:** 26/07/2026
**Branch:** `feature/solution_v3`
**Baseline measured:** v3.3 artifact (1,585 mentions, 434 with candidates)
**Leaderboard reference:** 21.5450 (latest submission; docs record v3.1 = 19.4812, so 21.5450 is read here as v3.2)

> **Read this section order.** §1 is a measurement-driven diagnosis. §2–§4 are the
> requested literature/architecture/data research, but every item is ranked
> against §1 — a technique that improves something already near ceiling is listed
> as low priority no matter how good the paper is.

---

## 1. Diagnosis: the bottleneck is mention **recall**, not candidate precision

### 1.1 The score is ~21.5/100, i.e. `final_score ≈ 0.2155`

Three components with a safe-default design should not produce 0.2155. If
assertions default to empty and ~80% of gold assertions are empty, the
assertions component alone should contribute ≈ 0.3 × 0.8 = 0.24 — more than the
entire observed score. Something is multiplying *every* component down.

That something is the unmatched-mention penalty. Under the scorer's own
`--unmatched zero` reading (`score.py:120-136`), every gold mention we miss and
every mention we invent enters the average as a 0 across all three components:

```
final ≈ (0.3·q_text + 0.3·q_assert + 0.4·q_cand) · M / (G + P − M)
```

where `G` = gold mentions, `P` = our mentions, `M` = matched pairs, and `q_*` is
per-matched-pair quality.

### 1.2 Calibrating the model against the real leaderboard number

Per-pair quality on the mentions we *do* emit is already high:

- `q_text ≈ 0.85` — spans are verbatim slices, `raw[start:end] == text` holds for 1,585/1,585.
- `q_assert ≈ 0.90` — empty-default is measurably the right prior.
- `q_cand ≈ 0.86` — because 1,151/1,585 mentions are symptom/lab/result types whose
  gold candidates are empty, and the type gate correctly emits `[]` for them (J = 1).

Solving for `M` at `P = 1585` and the observed 0.21545:

| assumed gold `G` | implied matched `M` | implied recall | implied precision |
|---|---:|---:|---:|
| 2,400 | 792 | 33.0% | 50.0% |
| 2,800 | 871 | **31.1%** | **55.0%** |
| 3,200 | 951 | 29.7% | 60.0% |

`G ≈ 2,800` is the PRD's own extrapolation (13.6 concepts/1,000 chars ×
203,817 chars). The model reproduces the leaderboard score at recall ≈ 31%.

**The fact that the score is this low is itself evidence** that the official
metric penalises unmatched mentions. Under `--unmatched skip`, the same output
would score roughly 0.3(0.9) + 0.3(0.9) + 0.4(0.86) ≈ 0.88 → 88. It scored 21.5.
That partially answers open question #1 to the BTC without needing their reply:
**missing and spurious mentions cost full credit.**

### 1.3 Three independent measurements confirm low recall

**(a) Concept density is 57% of the LLM pipeline's.** v3.3 produces 7.78
concepts/1,000 chars corpus-wide vs 13.6 for the earlier LLM-based run.

**(b) Head-to-head on the same 10 files** (LLM figures from PRD tab 04 §3):

| file | chars | v3.3 | LLM run |
|---:|---:|---:|---:|
| 1 | 4,481 | 42 | 57 |
| 2 | 3,740 | 22 | 46 |
| 3 | 3,724 | 31 | 34 |
| 4 | 3,676 | 63 | 64 |
| 5 | 3,420 | **13** | **41** |
| 6 | 3,218 | 18 | 56 |
| 7 | 3,208 | 18 | 32 |
| 8 | 3,110 | 25 | 49 |
| 9 | 3,013 | 16 | 41 |
| 10 | 2,957 | 40 | 51 |
| **total** | 34,547 | **288** | **471** |

**(c) Manual read of `5.txt`** — v3.3 emits 13 mentions. Concepts plainly present
and missed include `ung thư biểu mô tế bào mật`, `ung thư biểu mô tuyến`,
`vô sinh` (×2), `xét nghiệm tinh dịch đồ`, `chụp tử cung vòi trứng`,
`xét nghiệm nội tiết`, `cholangiogram`, `sinh thiết`, `nôn`, `ớn lạnh`,
`tế bào bất thường`, `tắc nghẽn`. It also emits one clear type error:
`xét nghiệm cận lâm sàng` → `CHẨN_ĐOÁN` / `Z01.7`.

### 1.4 What recall is worth

Same model, holding per-pair quality constant:

| our `P` | recall | matched `M` | final | ×100 |
|---:|---:|---:|---:|---:|
| 1,585 | 31% | 868 | 0.2145 | **21.45** ← today |
| 2,200 | 50% | 1,400 | 0.3379 | 33.79 |
| 2,600 | 65% | 1,820 | 0.4418 | 44.18 |
| 2,800 | 75% | 2,100 | 0.5214 | 52.14 |
| 2,900 | 85% | 2,380 | 0.6230 | 62.30 |

Going from 31% → 65% recall roughly **doubles** the score without improving a
single candidate mapping. No amount of linking precision work reaches this,
because linking precision only moves `q_cand` from 0.86 toward 1.0 — worth at
most 0.4 × 0.14 × (M/D) ≈ **+1.4 points**.

> **Implication for strategy.** v3.1 → v3.3 spent its budget on precision gates,
> blocklists and abstention — v3.3 deliberately *removed* 31 diagnoses and 27
> candidate codes relative to v3.2. Under this metric that work is close to
> score-neutral at best and negative at worst. The rule-first, abstain-by-default
> doctrine that was correct for v0 infrastructure is now the thing capping the score.

### 1.5 The abstention doctrine is mathematically dominated

For a matched pair with non-empty gold candidate set `G`:

- Predict `∅` → `J = |∅ ∩ G| / |∅ ∪ G| = 0`. Always exactly zero.
- Predict `{c}` → `J = 1` if `c ∈ G`, else 0. Expected value = `P(c ∈ G) ≥ 0`.

**Abstaining is weakly dominated by any guess whenever gold is non-empty.** The
PRD's "Jaccard penalises extra codes as much as missing ones" is true only for
*over*-predicting set size; it says nothing in favour of predicting the empty set.

Where abstention *is* right: when gold's candidate list is empty — which happens
when gold typed the span as `TRIỆU_CHỨNG` / `TÊN_XÉT_NGHIỆM` / `KẾT_QUẢ_XÉT_NGHIỆM`.
So the abstention decision should be conditioned on **type confidence**, not on
retrieval score. Writing `p_t` = P(gold type is mappable) and `a₁` = P(top code correct):

```
emit  iff  p_t · a₁  >  1 − p_t      ⟺  p_t > 1/(1 + a₁)
```

At a₁ ≈ 0.5 that is `p_t > 0.67`. The current code thresholds on rerank score at
0.80 (`pipeline.py:150-180`), which is the wrong axis entirely.

> **Correction, measured during implementation (26/07).** The doctrine above is
> right, but **it is worth ~0 points on the current corpus** — the predicted
> +1 to +3 in §5 does not exist yet. Instrumentation before the change showed
> `dropped_threshold = 24` was *not* 24 abstentions but ranked-tail truncation:
> **zero** mentions ever abstained on retrieval score. `IcdCueExtractor` (0.80)
> and `RxNormExtractor` (0.84) already threshold internally, so nothing below
> threshold reaches the pipeline and the 0.80 knob was inert. The chapter-R
> blocklist in `IcdCueExtractor` likewise measured **0** skips across all 100
> files.
>
> The fix is still worth shipping — it removes a latent trap — but its value is
> *contingent on Phase 3*. It only pays once recall improves and weaker
> candidates start flowing through the pipeline. Sequencing consequence: do not
> expect a leaderboard move from the decision layer alone.

### 1.6 The drug branch is 141 free candidate codes on the floor

Measured on the v3.3 artifact:

- 256 `THUỐC` mentions; 99 masked (`*****`), 157 plaintext.
- Only **14** carry any candidate. 144 plaintext mentions abstain.
- **141 of those 144 resolve to an exact, single-token alias already present in
  `data/kb/rxnorm_aliases.csv.gz`.** The remaining 3 are two-token names
  (`Insulin glargine`, `Bacillus clausii`) that a bigram lookup would catch.

| mention | KB alias hit | TTY | RXCUI |
|---|---|---|---|
| `omeprazole` | exact | IN | 7646 |
| `doxycycline` | exact | IN | 3640 |
| `vancomycin` | exact | IN | 11124 |
| `aspirin` | exact | IN | 1191 |
| `tylenol` | exact | BN | 202433 |
| `gleevec` | exact | BN | 282386 |
| `bactrim` | exact | BN | 151399 |

The cause is a policy over-generalisation. The PRD inferred "target TTY = SCD"
from 5/6 codes in the official examples being SCD — but every one of those
examples is a *full regimen* (`amlodipine 10 mg po daily`). A bare `omeprazole`
carries no strength and no dose form, so **it cannot have an SCD gold code**;
the plausible gold is the IN. The pipeline instead reads "no SCD evidence" as
"abstain", and returns `[]` — the guaranteed-zero option — for 92% of the drug
mentions it found.

The correct rule is TTY selection by evidence level, not a global SCD target:

| evidence in span | target TTY |
|---|---|
| ingredient + strength + dose form | SCD |
| brand + strength + dose form | SBD |
| brand only | BN (or the BN's SBD family if unambiguous) |
| ingredient only | IN |

### 1.7 One more cheap experiment: duplicate policy

30.4% of our mentions (482/1,585) are repeated `(text, type)` pairs within the
same file — `khó thở` ×26, `sốt` ×22, `Bệnh dại` ×17. If the gold annotates every
occurrence, these are legitimate. If it annotates a concept once per document,
they are 482 pure false positives inflating the denominator `D`. The official
example is ambiguous (it lists 18 concepts for 11 drugs, with `táo bón` appearing
twice in the input text). This is a **single-variable leaderboard experiment**
worth running once, and it costs no modelling work.

---

## 2. Scientific approaches, ranked by expected value on *this* metric

### Tier 1 — attacks recall (the 2× lever)

#### 2.1 LLM → encoder distillation with silver labels

This is the standard recipe for exactly your constraint set (zero gold labels,
runtime must be offline and reproducible), and it satisfies NFR1/NFR2 because
**the teacher runs at development time only**; what ships is the student's
weights.

- **UniversalNER** ([arXiv:2308.03279](https://arxiv.org/abs/2308.03279)) —
  targeted distillation from an LLM teacher into an open-NER student; beats
  general instruction-tuned models by >30 F1 across 43 datasets / 9 domains
  including clinical. This is the canonical reference for the recipe.
- **SHIELD** ([arXiv:2605.03301](https://arxiv.org/pdf/2605.03301)) — a 2026
  three-stage teacher→student pipeline on ~13K unlabelled clinical notes:
  refined prompts generate silver BIO annotations, a small student is trained
  with token-level cross-entropy. Closest published analogue to your situation.

Applied here: run a strong LLM over all 100 public files (plus any additional
Vietnamese clinical text you can gather) with the 5-label schema and few-shot
examples drawn from the BTC's own worked example, produce silver spans, then
fine-tune a token classifier. Per **ViMedNER**
([EAI Endorsed Trans., 2024](https://publications.eai.eu/index.php/inis/article/view/5221)),
XLM-R outperforms PhoBERT / ViDeBERTa / ViHealthBERT on Vietnamese medical NER —
and XLM-R is syllable-level, so you avoid the VnCoreNLP word-segmentation
failure mode that has bitten PhoBERT users.

#### 2.2 GLiNER-biomed — the best offline option that needs no training at all

- **GLiNER-BioMed** ([arXiv:2504.00676](https://arxiv.org/abs/2504.00676)) — a
  suite of lightweight bidirectional-encoder models for **open** biomedical NER:
  entity types are supplied as natural-language prompts at inference, so your
  five Vietnamese labels can be passed directly with no retraining. +5.96 F1 over
  baselines zero-shot; the bi-encoder variant reaches **70.39 F1 with only 10
  annotated samples**. Runs on CPU, single-file weights, no network.
- **GLiNER2** ([arXiv:2507.18546](https://arxiv.org/html/2507.18546v1)) — adds a
  schema-driven interface handling NER + classification + structured extraction
  in one pass, which maps neatly onto your span + type + assertion output.
- **Million-Label NER with GLiNER bi-encoder** ([arXiv:2602.18487](https://arxiv.org/html/2602.18487v1))
  — scales the label space, relevant if you ever want to prompt with ICD chapter
  names directly.

GLiNER-BioMed is English-trained; for Vietnamese use the multilingual GLiNER
backbones (mDeBERTa-based) or ensemble it with §2.1's distilled XLM-R. The
20-file gold dev set you already selected is *more than enough* to few-shot-tune
the bi-encoder given the 10-sample result above.

> **Why this beats writing more rules:** v3.1→v3.3 added phrase families one at a
> time and moved from 1,668 → 1,585 mentions. The long tail of Vietnamese
> clinical phrasing is not enumerable by hand; a prompted encoder generalises to
> it for free.

#### 2.3 Build the gold dev set — this is the actual blocker

The PRD already froze the right 20 files (1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16,
17, 21, 25, 26, 27, 31, 42, 54, 94 — full coverage of the 14 genre × NFD × mask
combinations, no near-duplicate leakage). It has never been annotated.

Right now the only true accuracy signal in the project is a single leaderboard
number per submission. Every technique below is unfalsifiable without this. With
~750 concepts to annotate, LLM pre-annotation + human adjudication makes this
one focused day of work, and it converts *every* subsequent change from a guess
into a measurement. **Do this before anything in Tier 2.**

### Tier 2 — attacks candidates (worth ~+1.4 to +4 points)

#### 2.4 Cross-lingual dense retrieval, fused with the existing lexical index

Your Recall@1 ≈ 51% / Recall@5 ≈ 94.9% measurement is the textbook argument for
retrieve-then-rerank, and the current pipeline only has the lexical half.

- **BioELX** ([arXiv:2605.27380](https://arxiv.org/abs/2605.27380)) — the most
  directly applicable 2026 paper. Two stages: (1) SapBERT retrieval improved by
  self-supervision on **Wikidata-derived multilingual aliases**, (2) a pretrained
  LLM ranker reading mention-in-context against candidates. Recall@1 gains:
  **+19.2 avg on XL-BEL**, +21.6 Turkish, +22.1 Korean, +30.8 Thai, +12.8
  WikiMed-DE. Vietnamese is not evaluated, but the gains are largest exactly on
  the low-resource non-Latin-adjacent languages that resemble your case, and the
  Wikidata alias trick is language-agnostic and free.
- **BeLink** ([arXiv:2605.22501](https://arxiv.org/html/2605.22501)) — generative
  re-ranking via instruction-tuned mid-size open models in both stages; the
  open-weights angle matters for your reproducibility constraint.
- **Hybrid Re-ranking for BEL using SapBERT** ([CEUR Vol-4038 paper 35](https://ceur-ws.org/Vol-4038/paper_35.pdf))
  — the BioNNE-L 2025 winner. Combines **cosine + Jaccard + Levenshtein** with
  grid-searched weights: Acc@1 0.718, Acc@5 0.802, MRR 0.750. This is the
  cheapest possible upgrade to your existing `IcdRetriever` scoring function —
  you already compute two of the three signals in `retrieval.py:124-142`.
- **Multistage biomedical concept normalization with LLMs**
  ([PMC12527512](https://pmc.ncbi.nlm.nih.gov/articles/PMC12527512/)) — two LLM
  touch points: generate alternative phrasings of the mention *before* retrieval,
  and prune candidates after. On a BM25 baseline this gave **+15.6 Fβ / +18.7 F1
  with open-source Vicuna** — i.e. an open model beat GPT-3.5 here. Your
  hand-written `_rewrite_query` rewrite table in `retrieval.py:36-54` is a
  9-entry manual version of exactly this idea.
- **Medical Entity Linking in Low-Resource Settings with Fine-Tuning-Free LLMs**
  ([SHTI251402, 2026](https://journals.sagepub.com/doi/10.3233/SHTI251402)) —
  candidate-gen Recall@5 ≈ 70%, disambiguation ≈ 80% when the code is in top-5.
  Directly matches your no-labels constraint.

Practical offline retrievers: **BGE-M3** (100+ languages, unified dense +
sparse + ColBERT scoring in one model — you can get lexical *and* dense from a
single artifact) and **multilingual-E5** ([arXiv:2402.05672](https://arxiv.org/pdf/2402.05672)).
Fuse with your existing lexical scores by Reciprocal Rank Fusion.

#### 2.5 Replace the fixed threshold with expected-Jaccard-optimal set selection

The `candidates` field is a **set-valued prediction problem under a Jaccard
utility**, which has a clean decision-theoretic solution
([Mortier et al., *Efficient set-valued prediction in multi-class classification*, DAMI 2021](https://link.springer.com/article/10.1007/s10618-021-00751-x)).

For calibrated code probabilities `p₁ ≥ p₂ ≥ …` and a singleton gold set:
`E[J(top-k)] = (Σᵢ≤ₖ pᵢ)/k`, which is maximised at **k = 1** — always.

> **Correction, measured during implementation (26/07).** Two claims in the
> paragraph above were wrong, and the code disproved them:
>
> 1. **"k = 1 always" is an artefact of assuming singleton gold.** Extending the
>    derivation to `q = P(gold = {c₁, c₂})` gives `add second ⟺ q/(1−q) > p₁ − p₂`.
>    When two codes are *tied* — an exact alias mapping to two siblings with no
>    discriminator in the text — `p₁ − p₂ = 0` and the pair wins for **any** `q > 0`.
>    That is structurally the organiser's own `K21.0`/`K21.9` case. So the 35
>    surviving two-code outputs (`K29.6/K29.7`, `E66.8/E66.9`, `I95.8/I95.9`,
>    `E78.4/E78.5` — all verified same-parent siblings) are *justified* by the
>    derivation, not overturned by it.
> 2. **The "39/420 via a hand-set margin" framing was misleading.** Only 4 of the
>    39 came from `ambiguity_margin`; the other 35 arrived through the exact-path
>    bypass, which never consulted the margin at all.
>
> What the implementation kept: `ambiguity_margin` now *means* `q/(1−q)` and
> defaults to 0.0 (require an exact tie), and a second code additionally requires
> structural ICD siblinghood. RxNorm codes have no `.`, so drugs never qualify.

Combined with §1.5, the decision layer becomes:

```
if P(gold type is mappable) < 1/(1 + a₁):   emit []
else:                                        emit argmax_S E[J(S)]   (usually |S| = 1)
```

#### 2.6 Ontology-aware reasoning — the "Ontological Reasoning" the đề bài actually names

- **OntoEL: Neuro-Symbolic Biomedical Entity Linking with Differentiable Fuzzy
  EL⊥ Reasoning** ([SIGIR 2026](https://doi.org/10.1145/3805712.3809595)) — the
  framing paper for your competition title. Its thesis: neural BEL models treat
  ontologies as **flat dictionaries and ignore the TBox** — which is precisely
  what `IcdGazetteer` + `IcdRetriever` do today. It uses the terminological
  axioms that define concept boundaries as a differentiable constraint.
- **Ontology-Constrained Neural Reasoning** ([arXiv:2604.00555](https://arxiv.org/abs/2604.00555))
  — ontology-anchored retrieval (OG-RAG) reports +55% fact recall.

A **zero-training** version you can ship immediately: ICD-10 is a tree
(chapter → 3-char → 4-char). When the reranker's top-k disagree at the leaf but
share an ancestor, emit the **lowest common ancestor** instead of a coin-flip
leaf. This converts retrieval uncertainty into a code at the granularity the
evidence supports — and directly addresses the BTC's open question #6 (does a
generic `suy tim` mention expect `I50` or `I50.9`?). Under Jaccard, a correct
`I50` scores 1 while a wrong `I50.9` scores 0.

Also unlock the structure you already built and then discarded:
`icd10_concepts` carries `chapter` and `is_symptom_chapter`. Chapter R membership
is currently used as a *blocklist*; it is better used as a **type prior** feeding
`p_t` in §1.5 — a mention whose best ICD match is in chapter R is evidence that
the gold type is `TRIỆU_CHỨNG`, which is exactly the signal the type gate needs.

#### 2.7 Graph neural networks — honest assessment: **low priority here**

The literature is real and good — hierarchical GNNs for ICD
([Nature Sci Rep 2025](https://www.nature.com/articles/s41598-025-10590-1)),
medical entity disambiguation with GNNs
([arXiv:2104.01488](https://arxiv.org/pdf/2104.01488)), multi-stage retrieve-and-rerank
for medical coding ([arXiv:2405.19093](https://arxiv.org/pdf/2405.19093)) —
but all of it is **supervised**. With zero labels and a 100-file test set, a GNN
has nothing to learn from, and its deployment cost (PyTorch + PyG in a repo that
currently has *zero* dependencies) directly attacks NFR1, your hardest constraint.

The useful 5% of this literature is the *idea* of hierarchy as a prior
(GRAM-style ancestor mixing) — which §2.6's LCA rule captures with 20 lines of
standard library code and no training.

### Tier 3 — assertions (already near ceiling; do not invest)

Assertions are 0.3 weight but `q_assert ≈ 0.90` on matched pairs already, and the
corpus evidence for empty-default is strong (isFamily ≈ 0 after fixing the
`"ông"`-inside-`"không"` substring bug). Ceiling gain ≈ 0.3 × 0.10 × (M/D)
≈ **+0.7 points**. For completeness:

- **Beyond Negation Detection** ([arXiv:2503.17425](https://arxiv.org/abs/2503.17425))
  — comprehensive assertion models covering the full spectrum, not just negation.
- **Assertion Detection using LLMs** ([PMC11908446](https://pmc.ncbi.nlm.nih.gov/articles/PMC11908446/),
  [arXiv:2401.17602](https://arxiv.org/pdf/2401.17602)) — LoRA-tuned LLM reaches
  0.962 accuracy vs GPT-4o 0.901; biggest gains on **Hypothetical +23.4%**, which
  is the failure mode your educational-genre files exhibit.

The one thing worth taking: assertions will improve *for free* as recall improves,
because more matched pairs means the same `q_assert` applies to a larger `M`.

---

## 3. Architectural approaches

### 3.1 Recommended target architecture for v4

Keep the seven-stage DAG, the `TextRef` foundation, the type gate and the
provenance discipline — all of that is sound and none of it is what is costing
points. Change what fills the stages:

```
                    ┌──────────── DEVELOPMENT TIME (not shipped) ────────────┐
                    │  LLM teacher ensemble → silver spans/types/assertions  │
                    │  + 20-file human-adjudicated GOLD DEV SET              │
                    └───────────────────────┬────────────────────────────────┘
                                            │ distil / few-shot tune
                                            ▼
  txt → TextRef → ┌─ Extract (UNION, recall-first) ──────────────────────┐
                  │  A. v3.3 rule providers      (high precision anchor) │
                  │  B. distilled XLM-R / GLiNER (long-tail recall)      │
                  └──────────────────┬───────────────────────────────────┘
                                     ▼
                            Locate  (unchanged — this layer works)
                                     ▼
                     TypeGate  → outputs p_t, a DISTRIBUTION not a label
                                     ▼
                   Assert  (ConText scope + per-entity marker classifier)
                                     ▼
    ┌──────── Link ────────────────────────────────────────────────────┐
    │ CHẨN_ĐOÁN → ICD   lexical ∪ BGE-M3 dense → RRF → hybrid rerank   │
    │                    (cosine+Jaccard+Levenshtein) → LCA collapse   │
    │ THUỐC → RxNorm    evidence-level TTY: SCD | SBD | BN | IN        │
    └──────────────────┬───────────────────────────────────────────────┘
                       ▼
        Decision layer:  argmax_S E[J(S)] ;  abstain iff p_t < 1/(1+a₁)
                       ▼
                     Emit
```

Two structural changes matter most:

1. **Extract becomes a recall-first union.** `CompositeExtractor` already unions
   providers and de-overlaps. Adding a learned provider is a provider-pattern
   addition, not a rewrite — this is the payoff of decision #2 in the system
   design.
2. **TypeGate emits a distribution, not a hard label.** Every downstream
   abstention decision needs `p_t` (§1.5). Today the type is a hard enum, so the
   information needed for the correct decision rule does not exist in the data
   contract.

### 3.2 Multi-agent / multi-model — yes, but at development time

The 2026 literature is genuinely positive:

- **Multi-Agent Open-Source LLM for Cancer Registry Extraction**
  ([ACL BioNLP 2026](https://aclanthology.org/2026.bionlp-1.43/)) — modular agents
  for structured extraction from pathology reports; weighted F1 0.71 → 0.78
  (breast), 0.56 → 0.67 (colorectal), with explicit intermediate reasoning stages
  giving traceability and error analysis. That traceability property is the same
  thing your `Provenance` dataclass exists for.
- **Configurable Clinical IE with Agentic RAG**
  ([arXiv:2606.19602](https://arxiv.org/html/2606.19602)) — "what works, what
  breaks, and why"; read this before building, it is largely a catalogue of
  failure modes.
- **Orchestrated multi-agents sustain accuracy under clinical-scale workloads**
  ([npj Health Systems, 2026](https://www.nature.com/articles/s44401-026-00077-0))
  — a lightweight orchestrator dividing work into single-tool subtasks keeps
  accuracy under concurrency.
- **MedGuards** ([arXiv:2606.25651](https://arxiv.org/pdf/2606.25651)) —
  multi-agent medical error detection/correction; the verifier-agent pattern.

**But do not put agents in the submitted runtime.** NFR1 is a hard elimination
criterion and an agent loop over an API is the least reproducible thing you could
ship. The right use is a **development-time annotation factory**:

```
Extractor agent  →  Type arbiter agent  →  Assertion agent  →  Linker agent
                              ↓
                    Verifier agent (span must be verbatim; code must exist in KB)
                              ↓
              3× self-consistency vote  →  disagreements to human queue
```

This produces silver labels at corpus scale and routes only the contested cases
to you — which is how the 20-file gold set gets built in a day rather than a week.

### 3.3 Multi-model ensembling in the shipped runtime

Legitimate and cheap: run rule providers and the distilled encoder, then union
spans and resolve conflicts deterministically (longest match wins; on ties, rule
provider wins because it carries KB provenance). Deterministic, offline, and it
strictly increases recall — which §1.4 says is the whole game.

### 3.4 Reproducibility budget

The zero-dependency stance is admirable but it is now costing more than it saves.
A realistic v4 bundle:

| component | size | dependency |
|---|---:|---|
| distilled XLM-R-base token classifier | ~1.1 GB fp32 / ~280 MB int8 | `torch` or ONNX Runtime |
| GLiNER-BioMed-bi | ~200 MB | ONNX Runtime (CPU) |
| BGE-M3 dense index over 13,189 ICD codes | ~40 MB | numpy only at query time |

Ship ONNX + `onnxruntime` and you need no PyTorch at all: one wheel, CPU-only,
deterministic, weights committed as artifacts. That is a far smaller
reproducibility risk than the PRD feared, and much smaller than the risk of
finishing outside the top 15.

---

## 4. Data sources and data architecture

### 4.1 The Vietnamese↔English bridge you are missing

The PRD's "language asymmetry" observation is right, but the pipeline never
actually builds the bridge. Two resources close it directly:

- **Meddict** — English–Vietnamese medical dictionary, **>64,000 entries**,
  VinUniversity, IP cert. 3365/2024/QTG ([project site](https://vinuni-medical-mt.github.io/),
  [meddict-vinuni.com](http://meddict-vinuni.com/)). Use it twice: (a) translate
  Vietnamese drug/ingredient mentions into English before RxNorm retrieval;
  (b) generate **Vietnamese aliases for ICD codes** whose official Vietnamese
  name is the long formal phrasing — this is the direct fix for
  `"Thiếu men G6PD"` vs `"Thiếu máu do thiếu men glucose-6-phosphate dehydrogenase [G6PD]"`.
- **MedEV** — 360K de-identified parallel En–Vi medical sentence pairs, open
  licence for research, [huggingface.co/datasets/nhuvo/MedEV](https://huggingface.co/datasets/nhuvo/MedEV)
  (Vo & Nguyen, [LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.784/);
  see also [arXiv:2509.15640](https://arxiv.org/abs/2509.15640) for prompting
  strategies on it). Use it to mine colloquial↔formal Vietnamese medical
  paraphrase pairs, and as SapBERT-style contrastive training data if you fine-tune
  an embedder.

### 4.2 Vietnamese drug data — the missing half of the RxNorm branch

**drugbank.vn** — the Ministry of Health / Drug Administration of Vietnam data
bank: **>10,000 drugs** in circulation plus ~41,000 facilities
([DAV announcement](https://dav.gov.vn/bo-y-te-cuc-quan-ly-duoc-ra-mat-ngan-hang-du-lieu-tra-cuu-thong-tin-thuoc-truc-tuyen-dau-tien-cua-viet-nam-n2562.html)).
This gives Vietnamese **brand → active ingredient → strength → dose form**, which
is exactly the join key RxNorm needs and exactly what your corpus mentions look
like. RxNorm has no Vietnamese brand coverage; this fills it.

Complementary: **RxClass / ATC** for ingredient-class fallbacks (when the corpus
says `kháng sinh nhóm *****`, an ATC class is more recoverable than an RXCUI),
and **RxMap** ([JAMIA Open 2026](https://academic.oup.com/jamiaopen/article/9/3/ooag085/8698717))
for the LLM-assisted lexical-parsing + hierarchical ingredient-level
reconciliation pattern — note it normalises to **IN/MIN**, corroborating §1.6.

### 4.3 Vietnamese medical NLP corpora for silver-label training

| resource | content | use |
|---|---|---|
| **ViMedNER** ([EAI 2024](https://publications.eai.eu/index.php/inis/article/view/5221)) | 8,000+ expert-annotated Vietnamese medical NER samples: disease, symptom, cause, diagnostic, treatment | Nearest thing to real supervision for your 5-label schema |
| **ViMQ** ([arXiv:2304.14405](https://arxiv.org/pdf/2304.14405)) | Vietnamese patient medical questions, sentence + entity level | Matches the Q&A genre — **44/100** of your corpus |
| **VietMed** ([arXiv:2404.05659](https://arxiv.org/pdf/2404.05659)) | 16h labelled medical speech transcripts; covers **all ICD-10 disease groups**, all accents | Colloquial Vietnamese disease phrasing → ICD alias mining |
| **COVID-19 Vietnamese NER**, **VLSP NER** | general/domain Vietnamese NER | Backbone pretraining / regularisation |

ViMQ in particular is under-exploited: the largest genre in your corpus is
patient↔doctor Q&A, and ViMQ is exactly that distribution with entity labels.

### 4.4 Alias expansion — a build-time change with immediate payoff

Your KB has 36,689 ICD names → 13,189 codes, and 94/100 files contain a verbatim
ICD name. The gap is entirely in the *non*-verbatim mentions. Four alias sources,
none requiring runtime dependencies, all landing in `icd10_aliases.csv.gz`:

1. **Morphological/orthographic variants** — diacritic-stripped, hyphen variants,
   abbreviation expansions. Partly done in `retrieval.py:26-33` (6 entries); this
   belongs in the KB, generated systematically, not in a query-time dict.
2. **Meddict-derived** — English ICD names (from WHO ICD-10) back-translated
   through Meddict give alternative Vietnamese renderings.
3. **LLM-generated colloquial paraphrases** — for each of the 13,189 codes, ask
   an LLM for 3–5 Vietnamese lay phrasings. Generated at build time, committed as
   a data artifact, checksummed in `MANIFEST.json`. This is the SapBERT synonym-pair
   idea applied to your specific KB, and it is the "fine-tune embedding on the
   competition's own code table" item the PRD listed as worth pursuing.
4. **Wikidata multilingual aliases** — the BioELX trick (§2.4). Wikidata has
   Vietnamese labels for many diseases with ICD-10 cross-references already
   attached; free, offline-dumpable, and self-supervising.

Alias expansion is the highest-value-per-hour item in the whole document that
does *not* require a model: it raises Recall@k on the branch that is already
94% covered by exact matching, without touching the runtime architecture.

### 4.5 Two data-architecture fixes

- **`data/knowledge_base/RXNORM.csv` is still missing from disk** — only
  `ICD10.csv` is present; the built artifacts in `data/kb/` are the only RxNorm
  source. The PRD flagged this on 25/07 and it is unresolved. Anyone rebuilding
  the KB from a clean clone cannot reproduce the RxNorm branch. This is an
  NFR1 (elimination) risk, not an accuracy risk.
- **Commit the ICD/RxNorm *version* used, and ship the bidirectional remap.**
  Already designed (§4.8 of system design) and implemented; just make sure the
  remap table itself is in the reproducible bundle.

---

## 5. Recommended sequence

| # | action | est. gain | rationale |
|---|---|---:|---|
| 1 | **Annotate the 20-file gold dev set** | enabler | Nothing below is measurable without it. ~750 concepts, LLM pre-annotation + adjudication. |
| 2 | **Emit IN/BN codes for bare drug mentions** (§1.6) | +1 to +2 | 141 codes already in the KB. One evening. Zero new dependencies. |
| 3 | **Recall-first extraction: GLiNER / distilled XLM-R as an added provider** (§2.1–2.2) | **+10 to +25** | The 2× lever. Provider-pattern addition, not a rewrite. |
| 4 | **Decision layer: expected-Jaccard set selection, abstain on type confidence** (§1.5, §2.5) | +1 to +3 | Replaces two guessed hyperparameters with a derived rule. |
| 5 | **Alias expansion into the KB** (§4.4) | +1 to +3 | Build-time only, no runtime cost. |
| 6 | **Dense retrieval + hybrid rerank + LCA collapse** (§2.4, §2.6) | +2 to +4 | Needs #1 to tune; needs an ONNX dependency. |
| 7 | **Duplicate-policy leaderboard experiment** (§1.7) | unknown, ±2 | One submission, one variable, resolves a real ambiguity. |
| 8 | Assertion model upgrade (§2.5 Tier 3) | +0.7 max | Only after everything above. |

### What to stop doing

Adding blocklists, precision gates and abstention rules. v3.3 removed 31
diagnoses and 27 candidate codes from v3.2 and the expected proxy moved −0.0010 —
the proxy could not see the difference because **the proxy has no gold and the
metric's dominant term is recall, which the proxy does not model at all.** Under
the model in §1.2, that class of change is score-neutral at best.

---

## 5b. Leaderboard feedback, 27/07 — 21.5450 → 23.5314

The v4.1 artifact (Phase 1 + Phase 2) scored **23.5314, +1.9864**. §5 predicted
+1 to +2 for that work. The prediction landed in band, which corroborates the
*structure* of the §1.2 model — but read the following carefully, because it
confirms less than it appears to.

**What can be derived.** Only `candidates_score` changed, so
`Δfinal = 0.4 · (newly correct codes) / D` with `D = G + P − M` and `P = 1585`.
We changed exactly 144 drug mentions (plus ~2 from Phase 2), and `D ≥ P` because
`G ≥ M`. Squeezing from both sides:

| quantity | bound | meaning |
|---|---|---|
| newly-correct codes | **79 … 146** | of 144 emitted IN/BN codes, ≥55% were both matched to gold *and* exactly right |
| `D` | **≤ 2,940** | hence **`G ≤ 2,940`** — a hard cap on gold size |

The ≥55% hit rate is the **first real measurement of drug-linking quality** in
this project — every prior number for that branch was an estimate.
`G ≤ 2,940` is consistent with the 2,800 density extrapolation, so that
extrapolation was not badly wrong.

**What this does NOT confirm.** Phase 1 changed no spans at all — mention count
stayed at 1,585. **The recall thesis remains untested.** Depending on the true
`D`, recall sits somewhere in **37%–84%**:

| matched `M` | D=1,732 | D=2,014 | D=2,400 | D=2,940 |
|---:|---:|---:|---:|---:|
| 800 | 84% | 65% | 50% | 37% |
| 1,200 | 89% | 74% | 60% | 47% |

That range is far too wide to act on. If recall is really 84%, Phase 3's neural
provider is close to worthless and would mostly add false positives; if it is
37%, it is worth more than everything else combined. **Only the gold dev set
separates these**, which promotes §5 item #1 from "enabler" to "the single
blocking measurement".

**What this does confirm.** Abstaining on candidates genuinely cost points,
exactly as `J(∅, G) = 0` predicts. The v3.3 doctrine that empty is safe was
wrong, and correcting it is now paid for.

- §1.2's recall/precision figures are **model-implied, not measured.** They depend
  on `G ≈ 2,800` (the PRD's density extrapolation) and on estimated `q_*` values.
  The direct measurements are §1.3(a)(b)(c) and §1.6, which are independent of
  the model and all point the same way.
- The metric-form assumption is `--unmatched zero` with greedy-IoU pairing. §1.2
  argues the leaderboard number is itself evidence for this, but it is an
  inference, not a BTC confirmation. Under `--unmatched skip` the entire
  prioritisation inverts and the current precision-first strategy would be right —
  which is why open question #1 to the BTC is still the highest-value question
  you can ask.
- Gain estimates in §5 are order-of-magnitude, derived from the same model.
  Treat them as a ranking, not as forecasts.
