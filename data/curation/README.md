# Medication curation layers

This directory separates immutable inputs, reproducible model proposals, and
human-adjudicated labels:

- `bronze/<snapshot>/MANIFEST.json`: hashes of the original source documents.
- `silver/<run>/`: generated medication mentions, groups, provenance, parsed
  attributes, and RxNorm candidate details. Never edit these files manually.
- `gold/<version>/medication_annotations.csv`: reviewer decisions. The
  generator refuses to overwrite a changed Gold file.

Clinical context and Gold labels are ignored by Git by default. Handle them
according to the source data agreement; do not publish them accidentally.

Generate the initial all-medication pack:

```sh
PYTHONPATH=src python3 -m smart_medic.review_pack \
  --input data/test \
  --explain data/output/explain.json \
  --kb data/kb \
  --root data/curation \
  --scope all
```

Allowed Gold decisions are `accept`, `replace`, `not_drug`,
`insufficient_evidence`, and `span_error`. An unresolved mask must remain
`insufficient_evidence` unless the reviewer has a direct external identity
anchor; treatment plausibility alone is not evidence.
