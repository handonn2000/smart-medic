# Reviewed Vietnamese drug aliases

Place licensed, reviewer-approved Vietnamese product mappings here. Public
availability on a website is not automatically permission to scrape or
redistribute the data; record the actual source, release, and license for each
row.

Copy `drug_aliases.template.csv` to a local file, populate it, and pass it only
to the opt-in v4 pipeline:

```sh
PYTHONPATH=src python3 -m smart_medic.infer \
  --extractor v4 \
  --rxnorm-specificity strict \
  --drug-aliases data/sources/dav/drug_aliases.csv
```

Only rows whose `review_status` is exactly `approved` are loaded. `rxcui` and
`tty` must exist and agree with the pinned runtime RxNorm KB. Duplicate aliases
that still identify multiple compatible RxCUIs abstain rather than guessing.

`evidence_level` must be one of `ingredient`, `brand`, or `product`. In strict
mode only SCD/SBD rows can be emitted; IN/BN rows require hierarchical mode.
