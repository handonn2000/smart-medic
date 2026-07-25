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
└── data/
    ├── knowledge_base/      # Reference vocabularies (ICD-10 codes, etc.)
    ├── input/               # Input text records (test.zip → input/*.txt)
    └── output/              # Predicted output (output.zip → *.json), one per input record
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

## Data

- `data/knowledge_base/ICD10.csv` — ICD-10 disease codes used for diagnosis candidate mapping.
- `data/input/*.txt` — 100 free-form clinical text records (competition test set).
- `data/output/*.json` — one prediction file per input record, matching `input/N.txt` → `output/N.json`.

## Submission requirements (Vòng 1)

- Predictions submitted as `output.zip` containing `output/1.json … output/100.json`.
- Top ~15 teams must submit full source code (data processing, training, inference), the data used, model weights, and a setup README — reproducibility is required or the team is disqualified.

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party reference data (e.g. ICD-10 codes) retains its original licensing terms and is included here for research/competition use only.
