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

```
smart-medic/
├── docs/
│   ├── PRD.html             # Full problem statement / requirements doc
│   ├── reports/             # Write-ups, experiment reports
│   └── references/          # Background papers (neurosymbolic AI, ontology engineering)
├── src/
│   └── smart_medic/         # Source code (data processing, training, inference)
├── models/                  # Trained model weights / checkpoints
├── scripts/
│   ├── gen_sample_data.py           # Training-data generator (see below)
│   └── migrate_to_new_structure.py  # One-off: old data layout → new
└── data/
    ├── knowledge_base/      # Reference vocabularies (ICD-10, RxNorm)
    ├── external/
    │   └── en_notes/        # mtsamples_filtered.jsonl — 457 English notes, source for `translate`
    ├── input/               # Input text records (test.zip → input/*.txt)
    ├── output/              # Predicted output (output.zip → *.json), one per input record
    └── generated_medical_records/   # Generated training data
        ├── synthetic/       # Written by an LLM around code-sampled entities
        │   ├── intermediate/    # entity_bundles.jsonl, composed_texts.jsonl, prompts.jsonl
        │   ├── text/            # synthetic_NNNN.txt — clean text
        │   └── annotations/     # synthetic_NNNN.json — NER labels
        ├── translated/      # Translated from real English mtsamples notes
        │   ├── intermediate/    # translation_process.jsonl, translation_prompts.jsonl
        │   ├── text/            # mtsamples_<specialty>_NNNN.txt
        │   └── annotations/     # mtsamples_<specialty>_NNNN.json
        └── restyled/        # Translated notes rewritten into test-set genres
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

Run inference over `data/input/` and write predictions to `data/output/`:

```bash
python -m smart_medic.infer --input data/input --output data/output
```

(Adjust the command above once the pipeline entry point is implemented in `src/smart_medic/`.)

## Generating training data

`scripts/gen_sample_data.py` builds labelled Vietnamese clinical notes from two
independent sources. Both guarantee **exact character offsets by construction**: an
LLM wraps every entity in `〔 〕` markers, and offsets are computed at the moment the
markers are stripped — so a label can never drift out of alignment with its text.

**A. Synthetic** — code samples an entity bundle (matching distributions measured on
gold), then an LLM writes a note around it:

```bash
python scripts/gen_sample_data.py compose --n 200 --use-api
python scripts/gen_sample_data.py emit
```

**B. Translated** — real English notes from mtsamples, translated to Vietnamese with
entities marked inline, then linked to ICD-10 / RxNorm codes via a gazetteer built
from the competition tables:

```bash
python scripts/gen_sample_data.py translate --n 100 --use-api --model gpt-4o
```

**C. Restyled** — rewrites the translated notes into the genre mix actually found in
the competition test set, keeping the `〔 〕` markers so offsets stay exact. Measured on
`data/test`: 45% bulleted outline, 17% clinical prose, 15% patient-education article,
14% patient↔doctor Q&A, 9% hard-wrapped handwritten note. Translation alone produces
100% clinical prose, i.e. it matches only ~17% of the test distribution:

```bash
python scripts/gen_sample_data.py restyle --use-api --model gpt-4o
```

**Drug codes — ingredient, not brand.** `RXNORM.csv` (which is just RXNCONSO, names
only) resolves a brand name to its *brand* CUI: `Lipitor → 153165`. But competition gold
uses *ingredient* CUIs exclusively — measured on 20 dev-gold files, 16/16 coded drug
spans are `tty=IN`, e.g. `levothyroxine → 10582`. The two are linked only by the
`tradename_of` relation in `RXNREL.RRF`, which ships with the **full** RxNorm release,
not the CSV. When `data/knowledge_base/RxNorm_full_*/rrf/RXNREL.RRF` is present the
script builds that map on first run (cached to `brand_to_ingredient.json`, ~96k brands)
and emits ingredient codes; without it, brand codes are used unchanged. Combination
brands map to all their ingredients (`Augmentin → 48203, 723`).

**Check any or all of them** (reports offset errors, code coverage, and how the output
compares against the competition test set):

```bash
python scripts/gen_sample_data.py verify
```

Both `compose` and `translate` need `OPENAI_API_KEY` when run with `--use-api`. Without
it they write prompts to `intermediate/` instead, so you can call any model yourself and
load the results back with `--composed FILE` / `--translated FILE`. Set `OPENAI_BASE_URL`
for an OpenAI-compatible endpoint (Azure, vLLM, OpenRouter).

Translating 100 notes costs roughly $5–10 on gpt-4o. Start with `--n 5` to sanity-check
translation quality before committing to a full run.

## Data

- `data/knowledge_base/ICD10.csv` — ICD-10 disease codes used for diagnosis candidate mapping.
- `data/input/*.txt` — 100 free-form clinical text records (competition test set).
- `data/output/*.json` — one prediction file per input record, matching `input/N.txt` → `output/N.json`.

## Submission requirements (Vòng 1)

- Predictions submitted as `output.zip` containing `output/1.json … output/100.json`.
- Top ~15 teams must submit full source code (data processing, training, inference), the data used, model weights, and a setup README — reproducibility is required or the team is disqualified.

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party reference data (e.g. ICD-10 codes) retains its original licensing terms and is included here for research/competition use only.
