# Smart Medic

**Ontological Reasoning in Medical Knowledge Retrieval** — an AI system that reads free-form Vietnamese clinical text (doctor's notes, discharge papers, lab reports, EHR excerpts) and:

1. **Detects & normalizes medical concepts** — mapping natural-language mentions to standard codes (ICD-10 for diseases, RxNorm for medications).
2. **Performs ontological reasoning** — inferring the contextual relationship between concepts within a passage (negation, family history, past history).

Built for **Viettel AI Race 2026 — Vòng 1**. See [`docs/PRD.html`](docs/PRD.html) for the full problem statement.

## Problem summary

**Input:** a free-form medical text passage containing multiple concepts of different types.

**Output:** a JSON list of detected concepts, each a dictionary with:

| Field | Meaning |
|---|---|
| `text` | The exact phrase identified as a medical concept |
| `position` | `[start, end]` character offsets in the input |
| `type` | One of the 5 concept types below |
| `assertions` | Contextual flags (only for `CHẨN_ĐOÁN`, `THUỐC`, `TRIỆU_CHỨNG`), up to 3: `isNegated`, `isFamily`, `isHistorical` |
| `candidates` | Predicted standard codes (only for `CHẨN_ĐOÁN` → ICD-10, `THUỐC` → RxNorm) |

**Concept types:** `TRIỆU_CHỨNG` (symptom) · `TÊN_XÉT_NGHIỆM` (lab test name) · `KẾT_QUẢ_XÉT_NGHIỆM` (lab result) · `CHẨN_ĐOÁN` (diagnosis) · `THUỐC` (medication)

## Project structure

The inference pipeline is organised into **stacked layers**. A layer may only import from
layers strictly below it — that rule is what lets several people (or agents) work in
parallel without collisions. **Every layer has its own `README.md`** describing what it
owns, its input/output contract, and its invariants; start with
[`src/smart_medic/README.md`](src/smart_medic/README.md) for the layer map.

| # | Layer | Owns |
|---|---|---|
| L0 | [`configs/`](configs) · [`resources/`](resources) | Tunable parameters and hand-written knowledge (YAML) |
| L1 | [`src/smart_medic/io/`](src/smart_medic/io) | Offset-preserving `Document` — gates every point |
| L2 | [`src/smart_medic/layout/`](src/smart_medic/layout) | Deterministic document structure (regex, no model) |
| L3 | [`src/smart_medic/extract/`](src/smart_medic/extract) | Span + type detection — the largest workstream |
| L4 | [`src/smart_medic/assertion/`](src/smart_medic/assertion) · [`linking/`](src/smart_medic/linking) | Context flags · ICD-10 / RxNorm codes |
| L5 | [`src/smart_medic/decision/`](src/smart_medic/decision) | The **only** place a threshold lives |
| L6 | [`src/smart_medic/validate/`](src/smart_medic/validate) | Hard gate before anything is written |
| L7 | [`src/smart_medic/eval/`](src/smart_medic/eval) | Scorer and diagnostics — off the inference path |

```
smart-medic/
├── configs/                 # L0 · thresholds, model pins, metric config (human-owned)
├── resources/               # L0 · hand-written YAML: negation cues, section titles, lab patterns
├── src/smart_medic/
│   ├── io/                  # L1 · Document(raw) — immutable, byte-exact offsets
│   ├── layout/              # L2 · line classes, outline tree, key:value splitting
│   ├── extract/             # L3 · recall-floor lane (rules) + model lane, graph merge
│   ├── assertion/           # L4 · scope graph → isNegated / isHistorical / isFamily
│   ├── linking/             # L4 · ICD-10 + RxNorm retrieval, edge verification
│   ├── decision/            # L5 · calibration, emit threshold, candidate selection
│   ├── validate/            # L6 · schema + offset gate, JSON serialisation
│   ├── eval/scoring.py      # L7 · internal scorer (3 readings × 4 alignment modes)
│   ├── pipeline.py          #      orchestrator
│   └── cli.py               #      python -m smart_medic {run,index,submit}
├── scripts/                 # build-time ONLY — the only place API calls are allowed
│   ├── data_gen/            #   gen_sample_data.py — training-data generator (see below)
│   ├── annotation_qa/       #   gold-annotation quality checks
│   ├── analysis/            #   measure_data.py — reproduces every measured number
│   └── submit/              #   package_submission.py
├── notebooks/
│   └── runbook.ipynb    # the linear path from a clean repo to output.zip (8 cells)
├── runs/                    # immutable run records: manifest + output + score
├── models/                  # trained model weights / checkpoints
├── tests/                   # offsets, scorer, API-leak guards, layer boundaries
├── docs/
│   ├── PRD.html             # Full problem statement / requirements doc
│   ├── decisions/           # ADRs — irreversible decisions
│   ├── reports/             # plan-v4.html is the current plan of record
│   └── references/          # Background papers (neurosymbolic AI, ontology engineering)
└── data/
    ├── knowledge_base/      # Reference vocabularies (ICD-10, RxNorm)
    │   ├── ICD10.csv        # ICD-10 disease codes (5.2 MB, 73K+ concepts)
    │   ├── RXNCONSO.RRF     # RxNorm concept names (replaces the organisers' RXNORM.csv)
    │   ├── RXNREL.RRF       # RxNorm relations — brand→ingredient mapping
    │   ├── RXNSTY.RRF       # semantic types · RXNATOMARCHIVE.RRF — retired-code remap
    │   ├── icd10cm-codes-2027.txt    # English ICD-10-CM labels, joined BY CODE to enrich ICD10.csv
    │   └── brand_to_ingredient.json  # Cached brand→ingredient map (~96k brands)
    ├── external/
    │   └── en_notes/        # mtsamples_filtered.jsonl — 457 English notes, source for `translate`
    ├── test/                # Competition test set (100 files: 1.txt … 100.txt)
    ├── output/              # Predicted output (output.zip → *.json), one per input record
    └── generated_medical_records/   # Generated training data (~543 notes total)
        ├── synthetic/       # 194 notes — Written by an LLM around code-sampled entities
        │   ├── intermediate/    # entity_bundles.jsonl, composed_texts.jsonl, prompts.jsonl
        │   ├── text/            # synthetic_NNNN.txt — clean text
        │   └── annotations/     # synthetic_NNNN.json — NER labels
        ├── translated/      # 187 notes — Translated from real English mtsamples notes
        │   ├── intermediate/    # translation_process.jsonl, translation_prompts.jsonl
        │   ├── text/            # mtsamples_<specialty>_NNNN.txt
        │   └── annotations/     # mtsamples_<specialty>_NNNN.json
        └── restyled/        # 162 notes — Translated notes rewritten into test-set genres
            ├── intermediate/    # restyle_process.jsonl, restyle_prompts.jsonl
            ├── text/            # mtsamples_<specialty>_NNNN_<genre>.txt
            └── annotations/     # mtsamples_<specialty>_NNNN_<genre>.json
```

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run inference over `data/test/` and write predictions to `data/output/`:

```bash
python -m smart_medic.cli run --input data/test --output data/output
```

(The pipeline entry point is not implemented yet — see
[`docs/reports/plan-v4.html`](docs/reports/plan-v4.html) tab 04 for the phase plan.)

**Or run the whole thing end to end:** [`notebooks/runbook.ipynb`](notebooks/runbook.ipynb) is
the linear path from a clean checkout to `output.zip` — integrity gate, KB indexes, inference,
scoring, packaging, reproducibility rehearsal. Its last cell self-checks that the notebook still
matches the repo, and it is re-run after every phase.

Score predictions against a gold directory:

```bash
PYTHONPATH=src python3 -m smart_medic.eval.scoring --pred data/output --gold <gold_dir>
```

## Generating training data

`scripts/data_gen/gen_sample_data.py` builds labelled Vietnamese clinical notes from two
independent sources. Both guarantee **exact character offsets by construction**: an
LLM wraps every entity in `〔 〕` markers, and offsets are computed at the moment the
markers are stripped — so a label can never drift out of alignment with its text.

**A. Synthetic** — code samples an entity bundle (matching distributions measured on
gold), then an LLM writes a note around it:

```bash
python scripts/data_gen/gen_sample_data.py compose --n 200 --use-api
python scripts/data_gen/gen_sample_data.py emit
```

**B. Translated** — real English notes from mtsamples, translated to Vietnamese with
entities marked inline, then linked to ICD-10 / RxNorm codes via a gazetteer built
from the competition tables:

```bash
python scripts/data_gen/gen_sample_data.py translate --n 100 --use-api --model gpt-4o
```

**C. Restyled** — rewrites the translated notes into the genre mix actually found in
the competition test set, keeping the `〔 〕` markers so offsets stay exact. Measured on
`data/test`: 45% bulleted outline, 17% clinical prose, 15% patient-education article,
14% patient↔doctor Q&A, 9% hard-wrapped handwritten note. Translation alone produces
100% clinical prose, i.e. it matches only ~17% of the test distribution:

```bash
python scripts/data_gen/gen_sample_data.py restyle --use-api --model gpt-4o
```

**Drug codes — ingredient, not brand.** `RXNCONSO.RRF` (names
only) resolves a brand name to its *brand* CUI: `Lipitor → 153165`. But competition gold
uses *ingredient* CUIs exclusively — measured on 20 dev-gold files, 16/16 coded drug
spans are `tty=IN`, e.g. `levothyroxine → 10582`. The two are linked only by the
`tradename_of` relation in `RXNREL.RRF`, which ships with the **full** RxNorm release,
not RXNCONSO. When `data/knowledge_base/RXNREL.RRF` is present the
script builds that map on first run (cached to `brand_to_ingredient.json`, ~96k brands)
and emits ingredient codes; without it, brand codes are used unchanged. Combination
brands map to all their ingredients (`Augmentin → 48203, 723`).

**Check any or all of them** (reports offset errors, code coverage, and how the output
compares against the competition test set):

```bash
python scripts/data_gen/gen_sample_data.py verify
```

Both `compose` and `translate` need `OPENAI_API_KEY` when run with `--use-api`. Without
it they write prompts to `intermediate/` instead, so you can call any model yourself and
load the results back with `--composed FILE` / `--translated FILE`. Set `OPENAI_BASE_URL`
for an OpenAI-compatible endpoint (Azure, vLLM, OpenRouter).

Translating 100 notes costs roughly $5–10 on gpt-4o. Start with `--n 5` to sanity-check
translation quality before committing to a full run.

## Data

- `data/knowledge_base/ICD10.csv` — ICD-10 disease codes (5.2 MB, 73K+ concepts) used for diagnosis candidate mapping.
- `data/knowledge_base/RXNCONSO.RRF` — RxNorm concept names (656k rows over 6 source vocabularies). Read via `scripts/kb_sources.py`.
- `data/knowledge_base/RXNREL.RRF` — RxNorm relations, used for brand→ingredient mapping.
- `data/knowledge_base/brand_to_ingredient.json` — Cached brand→ingredient map built from RXNREL.RRF (~96k brands).
- `data/test/*.txt` — 100 free-form clinical text records (competition test set: 1.txt … 100.txt).
- `data/output/*.json` — one prediction file per input record, matching `test/N.txt` → `output/N.json`.
- `data/generated_medical_records/` — ~543 generated training notes (194 synthetic + 187 translated + 162 restyled).

## Submission requirements (Vòng 1)

- Predictions submitted as `output.zip` containing `output/1.json … output/100.json`.
- Top ~15 teams must submit full source code (data processing, training, inference), the data used, model weights, and a setup README — reproducibility is required or the team is disqualified.

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party reference data (e.g. ICD-10 codes) retains its original licensing terms and is included here for research/competition use only.
