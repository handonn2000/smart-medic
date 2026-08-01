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
│   ├── prepare_training_data.py     # Annotation JSON → BIO file for train.py
│   ├── annotate.py                  # Hand-annotation workflow for the dev set
│   ├── evaluate.py                  # Internal scorer: WER + Jaccard (competition metric)
│   ├── measure_normalizer.py        # Diagnoses the code-assignment half of the score
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
            ├── intermediate/     # restyle_process.jsonl, restyle_prompts.jsonl
            ├── text/             # mtsamples_<specialty>_NNNN_<genre>.txt
            ├── annotations/      # mtsamples_<specialty>_NNNN_<genre>.json
            └── annotations_gold/ # Reviewed labels — the set worth training on
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

**Data format:** CoNLL / BIO style — one token per line as `token<space>label`, with a **blank line between samples**. The label is taken from the end of the line, so a token may itself contain spaces (`tê bì B-TRIEU_CHUNG`), which is what word segmentation produces for Vietnamese compounds. Labels use the BIO scheme (`B-XXX`, `I-XXX`, `O`) over the types listed in `src/labels.py`. Example:

```text
đau B-TRIEU_CHUNG
khớp I-TRIEU_CHUNG
gối I-TRIEU_CHUNG
. O
Celecoxib B-THUOC
400mg I-THUOC
```

### Building the BIO file from annotations

`scripts/prepare_training_data.py` turns generated records (`text/*.txt` plus
competition-format `annotations_gold/*.json`) into that format. It segments with the same
`segment_document` that `src/inference.py` uses, so training and prediction cut words
identically, and it normalises tokens to NFC because PhoBERT's vocabulary is NFC while a
quarter of the corpus is NFD on purpose.

```bash
# restyled + batch2 gold → data/train_generated.txt
python scripts/prepare_training_data.py

# Or pick sources explicitly
python scripts/prepare_training_data.py \
    --source data/generated_medical_records/restyled \
    --source data/generated_medical_records/batch2

# Hold out 24 records so there is something honest to score against later
python scripts/prepare_training_data.py --holdout 24

# Also fold in the small hand-written set (its unscored labels become O, reported)
python scripts/prepare_training_data.py --append data/train.txt
```

BIO over words can only give each word one label, so where the segmenter glues two
adjacent concepts into a single word — most often a test name running into its result,
`...nước tiểu dương tính` — the word goes to whichever concept overlaps it more and the
other is dropped. On the restyled gold that costs 76 of 7,435 concepts, and 217 more grow
by a few characters. `--audit-out` writes what a model that fit the data perfectly would
predict, so that ceiling can be measured rather than assumed:

```bash
python scripts/prepare_training_data.py --audit-out data/audit_ceiling
python scripts/evaluate.py --pred data/audit_ceiling \
    --gold data/generated_medical_records/restyled/annotations_gold \
    --text-dir data/generated_medical_records/restyled/text
```

That currently reports 99% concept recall with no wrong-type predictions and
`text_score` 0.972 — the upper bound this training set allows. Ignore its
`candidates_score`: the audit emits no codes because the normalizer is not involved.

### Running the training

```bash
python src/train.py --data data/train_generated.txt --from-scratch -e 6
```

`--from-scratch` is required the first time after `KẾT_QUẢ_XÉT_NGHIỆM` was added to
`src/labels.py`: the classifier and CRF are sized by the label count, so older checkpoints
no longer load. Training without `--data` still uses `data/train.txt`.

### Measuring what the training produced

Train on everything and there is no number to compare against — `--holdout N` exists so
that changes can be judged instead of guessed at. It reserves N annotated records, keeps
them out of the BIO file, and writes them as a ready-to-score split in `data/holdout/`
(`text/` and `gold/`), so the whole loop is four commands:

```bash
python scripts/prepare_training_data.py --holdout 24
python src/train.py --data data/train_generated.txt --from-scratch -e 6
python src/test.py -d data/holdout/text -o data/holdout/pred
python scripts/evaluate.py --pred data/holdout/pred --gold data/holdout/gold \
    --text-dir data/holdout/text
```

The split is stratified by presentation style rather than drawn uniformly, because
`hoi_dap` is only 12 of the 175 generated records while it is 42% of `data/test` — a
uniform draw of 24 would usually contain none of it and still report a healthy-looking
average. Two records of a style is thin, so read the per-style rows as indicative and the
overall score as the real number. Re-running with a different `--holdout` or `--seed`
clears records left behind by the previous split; without that, the scorer would quietly
grade files that had just been trained on.

Sanity checks worth knowing: scoring `data/holdout/gold` against itself returns exactly
1.0000 on all three components, and no word unique to a held-out record appears anywhere in
the BIO file.

On completion it prints the checkpoint location and writes weights to:

```
models/pho_bert_crf_medical.pth
```

Key hyperparameters (edit at the top of `src/train.py`): `MODEL_NAME`, `MAX_LEN`, `BATCH_SIZE`, `EPOCHS`, `LR`. The first run downloads the pretrained PhoBERT weights from the Hugging Face Hub (internet required).

## Testing / Inference

`src/test.py` runs the trained model on a single input and prints the predicted concepts as JSON, or on a whole folder of records and writes one JSON file per record.

```bash
# Inline text
python src/test.py -t "Bệnh nhân nam 55 tuổi, bị đau khớp gối phải" --model models/pho_bert_crf_medical.pth

# From a file
python src/test.py -f data/training/input1.txt --model models/pho_bert_crf_medical.pth

# Every record in a folder: data/test/7.txt → data/output/7.json
python src/test.py -d data/test -o data/output --model models/pho_bert_crf_medical.pth
```

Arguments:

- `-t <input_text>` — pass the input text directly (mutually exclusive with `-f` and `-d`).
- `-f <input_file>` — read the input text from a file.
- `-d <input_dir>` — predict every `.txt` in the folder, writing `<stem>.json` per record instead of printing.
- `-o <output_dir>` — where `-d` writes (default: `data/output`, the layout `output.zip` expects).
- `--model <path>` — path to the trained weights (default: `pho_bert_crf_medical.pth` in the current directory, so pass `models/pho_bert_crf_medical.pth` after training).

Folder mode loads the model once, keeps going when a single record fails (exiting non-zero afterwards), and warns about two things that quietly ruin a submission: a concept whose `text` is not the slice sitting at its own `position`, and leftover `.json` files in the output folder that no longer correspond to any input record.

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
that gold leaves empty, and codes absent from `ICD10_VN.csv` / `RXNORM.csv`. The likeliest
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

### Measuring the code assignment

`candidates` carries 0.4 of the final score and is currently the weakest part of the
pipeline, so it has its own diagnostic. `scripts/measure_normalizer.py` runs
`MedicalNormalizer` over every gold span that has a code and separates the failure modes,
because they need different fixes:

```bash
python scripts/measure_normalizer.py
python scripts/measure_normalizer.py --gold data/dev/gold
```

For each coded type it reports whether the gold code is in the loaded table at all, what rank
the fuzzy search gives it, whether the cutoff then throws it away, a sweep of mean Jaccard
over `top_k` × cutoff, the ceiling reachable by re-ranking alone, and examples of spans whose
gold code never surfaces. It drives the real methods and asserts that its own replication of
them agrees, so it cannot quietly measure something other than what ships.

What it found on the generated gold (1,456 diagnosis codes, 980 drug codes) — this is where
the constants at the top of `src/normalizer.py` come from:

- **One code beats three.** Gold carries exactly one code for 1,456/1,536 diagnoses and
  814/952 drugs, and Jaccard divides by the union, so three codes containing the right one
  still scores 1/3. Hence `DEFAULT_TOP_K = 1`.
- **The old cutoffs discarded correct answers.** 41.6% of the correct ICD codes and 23.2% of
  the correct RxNorm codes that the search did surface scored under the old `> 65` / `> 70`
  gates. Now 60 and 55. With `top_k`, that moves diagnoses 0.146 → 0.196 and drugs
  0.287 → 0.312.
- **Drugs fail on hierarchy, not on text.** The median score of a correct drug code is 100,
  an exact name match. Gold maps a brand to its ingredient (Lasix → `4603` furosemide) while
  the lookup returns the brand it matched (`202991`). Resolving brand and product rows to
  their ingredient is the biggest remaining lever — but the PRD sample uses dose-specific SCD
  codes instead, so settle which granularity the real gold wants before building it.
- **Diagnoses fail on retrieval.** `token_sort_ratio` compares whole strings, so a short span
  sitting inside a long official name loses on length alone: "Rung nhĩ" against `I48` "Rung
  nhĩ và cuồng nhĩ" loses to `K03.1` "Mòn răng". The gold code reaches the top 10 for only
  30.1% of spans and perfect re-ranking of those ten would still cap at 0.337, so the scorer
  itself has to change — containment-aware matching, abbreviation expansion (`HA` → huyết
  áp), and collapsing the newlines that appear in spans crossing a line break.

The gold used here is the generated corpus, whose codes an LLM chose rather than a coder, so
trust the comparisons between configurations more than the absolute values.

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

- `data/knowledge_base/ICD10_VN.csv` — ICD-10 disease codes used for diagnosis candidate
  mapping: the Ministry of Health 2020 list, 12,218 leaf codes in `MÃ BỆNH` with Vietnamese
  names in `TÊN BỆNH`. Its `DISEASE NAME` (English) column is locally misaligned — `I10`
  carries `I09.8`'s English text — so nothing reads it. The older `ICD10.csv` is still in
  the folder and all three readers still parse it, since they detect the header row and
  match column names rather than counting title rows.
- `data/input/*.txt` — 100 free-form clinical text records (competition test set).
- `data/output/*.json` — one prediction file per input record, matching `input/N.txt` → `output/N.json`.

## Submission requirements (Vòng 1)

- Predictions submitted as `output.zip` containing `output/1.json … output/100.json`.
- Top ~15 teams must submit full source code (data processing, training, inference), the data used, model weights, and a setup README — reproducibility is required or the team is disqualified.

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party reference data (e.g. ICD-10 codes) retains its original licensing terms and is included here for research/competition use only.
