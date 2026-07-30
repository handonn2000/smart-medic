# smart-medic — the five commands. Everything else is a script you call directly.
#
# PYTHONPATH=src is mandatory on every `python3 -m smart_medic.…` line: the package
# lives under src/ and is not installed in editable mode by default.

PY      ?= python3
export PYTHONPATH := src

GOLD_TXT := data/generated_medical_records/restyled/text
GOLD     := data/generated_medical_records/restyled/annotations_gold
PRED_GOLD := runs/_pred_gold

.DEFAULT_GOAL := help
.PHONY: help setup gate index run score submit test verify-repro clean

help:
	@echo "make setup    install dependencies"
	@echo "make gate     integrity gate — offsets + data/test unmodified (RUN THIS FIRST)"
	@echo "make index    build the KB indexes"
	@echo "make run      data/test -> data/output          (the submission)"
	@echo "make score    run on gold and score it          (the measurement)"
	@echo "make submit   output.zip + runs/<ts>_<sha>/manifest.json"
	@echo "make test     full test suite"

setup:
	$(PY) -m pip install -e '.[dev]'

# A score computed on drifted offsets is worse than no score, so this gate comes
# before everything. The whole file runs now: test_silver_offsets used to fail by
# design on the 165 known lab-assertion violations, but ADR 0004 puts the remedy
# in io/corpus.py at load time, so the test now asserts there (see
# test_loader_clears_illegal_lab_assertions) and the offset half stays strict.
gate:
	$(PY) -m pytest tests/test_offsets.py tests/test_reproducibility.py -q

index:
	$(PY) -c "import sys; sys.path.insert(0,'scripts'); import kb_sources as k; \
	  k.require(k.ICD10_VI, k.ICD10CM_EN, k.RXNCONSO, k.RXNREL, k.RXNSTY, k.RXNATOMARCHIVE); \
	  print('KB files present')"
	$(PY) scripts/annotation_qa/kb.py build
	$(PY) -c "import sys; sys.path.insert(0,'src'); from smart_medic import validate; \
	  c=validate.load_code_index(); print(f'code index: {len(c.icd)} ICD + {len(c.rxcui)} RxCUI')"

run: gate
	@test -f src/smart_medic/cli.py || { echo "cli.py not built yet (P1+). Start from .claude/prompts/p1_prompt.md"; exit 1; }
	$(PY) -m smart_medic.cli run --input data/test --output data/output

score: gate
	@test -f src/smart_medic/cli.py || { echo "cli.py not built yet (P1+)"; exit 1; }
	$(PY) -m smart_medic.cli run --input $(GOLD_TXT) --output $(PRED_GOLD)
	$(PY) -m smart_medic.eval.scoring --pred $(PRED_GOLD) --gold $(GOLD)

submit: gate
	$(PY) scripts/submit/package_submission.py
	unzip -l output.zip

test:
	$(PY) -m pytest tests/ -q

# The organisers re-run this source on an interpreter we do not choose. This
# proves two of them agree byte-for-byte, which is the claim ADR 0005 makes and
# nothing was checking. Set ALT_PY to any second interpreter >= 3.11.
ALT_PY ?= python3.14
verify-repro:
	@command -v $(ALT_PY) >/dev/null || { \
	  echo "ALT_PY=$(ALT_PY) not found — set it to a second interpreter >= 3.11"; exit 1; }
	@echo "primary : $$($(PY) -V 2>&1)"
	@echo "alternate: $$($(ALT_PY) -V 2>&1)"
	@rm -rf /tmp/_repro_a /tmp/_repro_b
	$(PY)     -m smart_medic.cli run --input data/test --output /tmp/_repro_a --quiet
	$(ALT_PY) -m smart_medic.cli run --input data/test --output /tmp/_repro_b --quiet
	@diff -r /tmp/_repro_a /tmp/_repro_b \
	  && echo "IDENTICAL — $$(ls /tmp/_repro_a | wc -l | tr -d ' ') files match byte-for-byte" \
	  || { echo "DIVERGED — the archive is not reproducible across interpreters"; exit 1; }

clean:
	rm -rf .pytest_cache $(PRED_GOLD)
	find src scripts tests -name __pycache__ -type d -prune -exec rm -rf {} +
