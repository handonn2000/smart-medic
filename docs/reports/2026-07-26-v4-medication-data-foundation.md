# V4 medication and data foundation

Date: 2026-07-26  
Branch: `codex/v4-medication-data`

## Objective

Start the next score-improvement cycle without changing the submitted v3.3
path. V4.0 targets the measured medication-normalization gap and creates a
real human-review data loop before introducing dense models.

## Implemented

1. `--extractor v4` is explicit and opt-in; the CLI default remains v3.
2. `V4MedicationExtractor` delegates to the unchanged v3 RxNorm extractor.
3. `--rxnorm-specificity strict` preserves SCD/SBD behavior.
4. `--rxnorm-specificity hierarchical` adds only exact, unique, current IN/BN
   backoff for plaintext `rxnorm_anchor_only` mentions.
5. Hierarchical codes are not allowed to support masked-drug propagation.
6. Optional reviewed drug aliases are loaded from an external checksummed CSV,
   validated against the pinned RxNorm KB, and traced to their source row.
7. A deterministic medication attribute parser records strength, unit, form,
   route, frequency, quantity, and mask status.
8. `review_pack.py` creates a minimal Bronze/Silver/Gold workflow and refuses
   to overwrite changed Gold annotations.

## Measured corpus delta

| Measurement | v3.3 / v4 strict | v4 hierarchical |
|---|---:|---:|
| Documents | 100 | 100 |
| Mentions | 1,585 | 1,585 |
| Mentions with candidates | 434 | 578 |
| Medication backoffs | 0 | 144 |
| Backoff TTY | — | 82 IN + 62 BN |
| Unresolved masks | 98 | 98 |
| Numeric output SHA-256 | `253026321c4b116ac81047dcf2ba66ed922fbc87282d9b4b3b6fe9d6a993fc24` | `1df707fec68afae13647609b443d097400c7202bcf677d5bd9586965c6894a3c` |
| ZIP SHA-256 | `bd91d7a2d5ef7d26f7144b61cd65b7ce1b5987bdda6d216cc0966f5d2b7020da` | `48a8cb7805be1df0a19823e10ea785c6df2c79d64ea45c319acf1ec3f5c4a85a` |

Strict output is byte-identical to the frozen v3.3 submission. Hierarchical
mode changes exactly 144 records, and only their `candidates` field; spans,
types, assertions, ordering, and every other record remain identical.

## Review pack

The initial all-medication pack contains:

- 256 occurrences in 166 groups;
- 144 plaintext-unlinked mentions;
- 98 unresolved masks;
- 11 high-confidence linked mentions;
- 2 low-confidence linked mentions;
- 1 multi-candidate mention.

Generated clinical context and annotations are ignored by Git. Contracts and
placeholders live under `data/curation/`; the actual local files are:

```text
data/curation/bronze/competition_test_v1/MANIFEST.json
data/curation/silver/v3_3_medications/
data/curation/gold/medications_v0/medication_annotations.csv
```

## Commands

```sh
# Rebuild the review pack
PYTHONPATH=src python3 -m smart_medic.review_pack \
  --input data/test --explain data/output/explain.json \
  --kb data/kb --root data/curation --scope all

# Rebuild controlled submission candidates
python3 scripts/build_v4_medication_variants.py

# Verification
python3 -m unittest discover -s tests -v
python3 scripts/clean_smoke.py
```

## Submission decision

Do not submit the hierarchical artifact solely because it fills 144 empty
candidate lists. Ingredient and Brand Name concepts are scientifically valid
RxNorm concepts, but the private Gold may require only SCD/SBD products. First
review the 48 unique plaintext anchors in the Gold template and confirm the
organizer's accepted RxNorm specificity. The strict artifact is only a
compatibility control because it is byte-identical to v3.3.

The next implementation after review is DAV-backed brand/product enrichment
with strength/form evidence, followed by a strict SCD/SBD-only artifact. Dense
retrieval and contextual reranking remain v4.1 work.
