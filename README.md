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

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

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
