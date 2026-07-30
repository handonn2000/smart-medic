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
│   ├── model.py             # PhoBERT + CRF model definition
│   ├── dataset.py           # BIO dataset loader with subword label alignment
│   ├── train.py             # Training entry point → models/pho_bert_crf_medical.pth
│   ├── inference.py         # MedicalExtractor (extraction + normalization)
│   ├── test.py              # CLI to run the model on text/file (-t / -f)
│   ├── labels.py            # BIO labels + mapping to the five scored output types
│   ├── tokenization.py      # Offset-preserving segmentation (`python src/tokenization.py` self-tests it)
│   ├── assertions.py        # isNegated / isFamily / isHistorical detection
│   └── normalizer.py        # RxNorm / ICD-10 candidate mapping
├── models/                  # Trained model weights / checkpoints
├── scripts/
│   ├── gen_sample_data.py           # Training-data generator (see below)
│   ├── annotate.py                  # Hand-annotation workflow for the dev set
│   ├── evaluate.py                  # Internal scorer: WER + Jaccard (competition metric)
│   └── migrate_to_new_structure.py  # One-off: old data layout → new
└── data/
    ├── knowledge_base/      # Reference vocabularies (ICD-10, RxNorm)
    ├── dev/                 # Hand-annotated dev set
    │   ├── marked/          # Working copies with 〔TYPE|text〕 markers
    │   └── gold/            # Compiled gold annotations (N.json)
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

Requires **Python 3.8+**. Create and activate a virtual environment, then install the dependencies from `requirements.txt`.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Linux / macOS:**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> Using `python -m pip` (instead of a bare `pip`) guarantees the packages install into the interpreter you're actually running.

Notes on specific dependencies:

- **`pytorch-crf`** — installed via `pip install pytorch-crf` but **imported as `torchcrf`** in code. Do **not** install the similarly named `TorchCRF`/`torchcrf` package; it has a different, incompatible API (missing `batch_first`) and will clash on case-insensitive filesystems like Windows.
- **`torch`** — `requirements.txt` installs the default build, which is CPU-only on Linux/Windows. If you have an NVIDIA GPU, install the CUDA build instead (see the per-OS notes below).

### Per-environment setup (team)

The steps above are enough to run everything on CPU. For GPU acceleration, adjust the PyTorch install per machine. Always check the [official PyTorch selector](https://pytorch.org/get-started/locally/) for the command matching your exact CUDA version.

**macOS (Apple Silicon or Intel):**

- The default `pip install torch` is correct — there is no CUDA on macOS.
- On Apple Silicon, the scripts automatically use the GPU via the **MPS** backend when available (device priority is CUDA → MPS → CPU). No configuration needed; Intel Macs fall back to CPU.

**Linux / Ubuntu:**

- No GPU → the default install is fine.
- NVIDIA GPU → install the CUDA build (example for CUDA 12.1), then continue with `requirements.txt`:

```bash
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
```

**Windows + NVIDIA GPU:**

- Install the CUDA build first, then the rest of the requirements:

```powershell
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt
```

- Verify the GPU is visible to PyTorch (should print `True`):

```powershell
python -c "import torch; print(torch.cuda.is_available())"
```

`train.py` and `inference.py` automatically use the GPU when `torch.cuda.is_available()` is `True`, so no code change is needed once the CUDA build is installed.

## Training

Train the PhoBERT + CRF sequence labeler on the annotated data in `data/train.txt`.

**Data format (`data/train.txt`):** CoNLL / BIO style — one token per line as `token<space>label`, with a **blank line between samples**. Tokens must not contain spaces. Labels use the BIO scheme (`B-XXX`, `I-XXX`, `O`) over these types: `THUOC`, `TRIEU_CHUNG`, `BENH`, `XET_NGHIEM`, `BENH_NHAN`. Example:

```text
đau B-TRIEU_CHUNG
khớp I-TRIEU_CHUNG
gối I-TRIEU_CHUNG
. O
Celecoxib B-THUOC
400mg I-THUOC
```

Run training (works from the project root or from `src/` — paths are resolved automatically):

```bash
python src/train.py
```

On completion it prints the checkpoint location and writes weights to:

```
models/pho_bert_crf_medical.pth
```

Key hyperparameters (edit at the top of `src/train.py`): `MODEL_NAME`, `MAX_LEN`, `BATCH_SIZE`, `EPOCHS`, `LR`. The first run downloads the pretrained PhoBERT weights from the Hugging Face Hub (internet required).

## Testing / Inference

`src/test.py` runs the trained model on a single input and prints the predicted concepts as JSON.

```bash
# Inline text
python src/test.py -t "Bệnh nhân nam 55 tuổi, bị đau khớp gối phải" --model models/pho_bert_crf_medical.pth

# From a file
python src/test.py -f data/training/input1.txt --model models/pho_bert_crf_medical.pth
```

Arguments:

- `-t <input_text>` — pass the input text directly (mutually exclusive with `-f`).
- `-f <input_file>` — read the input text from a file.
- `--model <path>` — path to the trained weights (default: `pho_bert_crf_medical.pth` in the current directory, so pass `models/pho_bert_crf_medical.pth` after training).

Example output:

```json
[
  {
    "text": "đau khớp gối phải",
    "type": "TRIỆU_CHỨNG",
    "candidates": [],
    "assertions": [],
    "position": [26, 43]
  }
]
```

`position` is a half-open character range into the input exactly as given, so
`text == raw_input[position[0]:position[1]]` always holds — `src/tokenization.py` derives
spans from the raw string rather than from the segmenter's output, which is what makes
repeated mentions ("táo bón" twice in one note) land on their own offsets. Inputs longer
than PhoBERT's 256-token limit are labelled in consecutive batches split at sentence
boundaries instead of being truncated, so concepts late in a long note are still found.

## Building a dev set

Nothing can be measured without gold annotations, and the competition supplies none.
`scripts/annotate.py` supports hand-annotating a sample of `data/test` into gold files.
You mark concepts inline with `〔 〕` markers instead of typing `position` offsets by
hand, and the tool computes offsets while stripping the markers — the same trick
`gen_sample_data.py` uses to keep generated offsets exact.

```bash
python scripts/annotate.py skeleton --n 15   # copy 15 test files into data/dev/marked/
python scripts/annotate.py status            # how far along the annotation is
python scripts/annotate.py compile           # markers → data/dev/gold/*.json
```

Annotate by wrapping each concept, leaving the surrounding text untouched:

```text
〔LOẠI|text〕                        a span with no code and no assertion
〔LOẠI|text|code〕                   with a standard code (CHẨN_ĐOÁN and THUỐC only)
〔LOẠI|text|code1,code2|isNegated〕  several codes, plus an assertion
```

Type shorthands are `DX`, `SYM`, `DRUG`, `TEST`, `RES`, matching the marker aliases in
`gen_sample_data.py`; full type names work too. Fields after the text are order-free —
anything that names an assertion is read as one, everything else as a code.

`compile` only writes a gold file when the marker-stripped text is character-identical
to the original `data/test/N.txt`, so an accidental edit to the prose can never silently
shift offsets. It also rejects unknown type names, misspelled assertions, codes on types
that gold leaves empty, and codes absent from `ICD10.csv` / `RXNORM.csv`. The likeliest
confusing failure has its own message: 20 of the 100 test files are in Unicode NFD form,
and an editor that saves them back as NFC changes the string length and shifts every
offset in the file.

`skeleton` samples with quotas so the dev set contains the two traps measured on the
test set (30% of files have a drug name masked with `***`, 20% are NFD), and it never
overwrites an existing file in `data/dev/marked/`. It deliberately does **not** pre-fill
spans from the model: a dev set exists to catch the model's mistakes, and pre-filling
turns annotation into confirmation of whatever the model already predicted.

## Scoring predictions

`scripts/evaluate.py` scores a directory of predictions against a directory of gold
annotations using the competition metric (see [`docs/PRD.html`](docs/PRD.html) §6):

```text
final_score = 0.3·text_score + 0.3·assertions_score + 0.4·candidates_score
```

`text_score` is `1 − WER` on the `text` field, `assertions_score` and `candidates_score`
are Jaccard similarities on the two set-valued fields. The first two are plain per-file
means; `candidates_score` is a **weighted** mean whose per-file weight is
`Σ_k (len(gold_candidates(k)) + 1)`, so files with more concepts and more gold codes
count for more.

```bash
# Score data/output/*.json against the hand-annotated dev set
python scripts/evaluate.py --pred data/output --gold data/dev/gold --text-dir data/test

# Show the 10 worst files
python scripts/evaluate.py --pred data/output --gold data/dev/gold --per-file 10

# Verify the scorer itself against six hand-computed cases
python scripts/evaluate.py --self-test
```

Files are paired by name (`gold/7.json` ↔ `pred/7.json`); a missing prediction file is
scored as an empty prediction. If `--gold` points at a `.../annotations` directory the
sibling `.../text` directory is used for the offset check automatically.

Beyond the score, the report breaks results down per concept type and counts **wrong-type
predictions** — spans that overlap a gold span but carry a different `type`. Those are the
most expensive errors: the concept is counted twice (once as a spurious prediction, once as
a missed gold concept) and scores zero on all three metrics both times, so a wrong type
costs about twice as much as not predicting the span at all.

The metric is stated per sample and never defines how predicted concepts are paired with
gold ones, so the scorer assumes **same type + overlapping character span**, matched
greedily by decreasing overlap. Two smaller assumptions (per-concept averaging, and `k`
ranging over all concepts rather than only codeable ones) are documented in the script's
docstring; `--candidates-scope codeable` shows how sensitive the score is to the latter.
Treat the numbers as a **relative** indicator for comparing model versions on a fixed gold
set, not as the organizers' score.

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
