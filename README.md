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
│   └── normalizer.py        # RxNorm / ICD-10 candidate mapping
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
    "position": [26, 42]
  }
]
```

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
