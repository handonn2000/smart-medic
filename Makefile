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
.PHONY: help setup gate index run score submit test clean

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
# before everything. test_silver_offsets FAILS by design: 165 real violations in
# the silver corpus, filtered at load in io/corpus.py.
gate:
	$(PY) -m pytest tests/test_offsets.py -q -k "not silver"

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

clean:
	rm -rf .pytest_cache $(PRED_GOLD)
	find src scripts tests -name __pycache__ -type d -prune -exec rm -rf {} +
