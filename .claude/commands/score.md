---
description: Validate offsets/schema, then score data/output under all three metric readings
argument-hint: "[--gold DIR] [--pred DIR] [--cand-formula official|plain]"
allowed-tools: Bash(python3 -m pytest*), Bash(PYTHONPATH=src python3 -m smart_medic.scoring*)
---

Score the current predictions and report what actually moved.

## 1. Integrity gate — never skip this

!`cd "$(git rev-parse --show-toplevel)" && python3 -m pytest tests/test_offsets.py -q 2>&1 | tail -15`

If this fails, **stop and report the failure**. A score computed on drifted
offsets is meaningless. `test_silver_offsets` failing only affects training
data; `test_output_offsets_and_schema` or `test_test_corpus_unmodified` failing
is a hard blocker.

## 2. Score

!`cd "$(git rev-parse --show-toplevel)" && PYTHONPATH=src python3 -m smart_medic.scoring --pred data/output $ARGUMENTS 2>&1`

## 3. How to read it

Report concisely, in this order:

1. **The primary number** — `penalised / greedy_iou`. That is the only reading
   that penalises over- and under-generation monotonically. Quote it as `/100`
   so it is comparable to the public leaderboard.

2. **Ceiling context.** A *perfect* prediction scores about **69/100**, not 100,
   because the official candidates denominator carries a `+1` that caps that
   term near 0.23. So `text` and `assertions` are ~87% of the reachable score
   and `candidates` is ~9 points. If someone proposes spending a day on code
   linking, weigh it against that, not against the nominal 0.4 weight.

3. **Cross-check the readings.** If a change improved `matched` but hurt
   `penalised`, it is metric gaming — almost certainly the system dropped
   predictions. Say so plainly. If it improved `penalised` but hurt `docbag`,
   the system is probably over-generating.

4. **Point at the next fix, not at the score.** Use the diagnostics:
   - a dominant `boundary_errors` mode (e.g. `right-extended`) is usually a
     one-line post-processing fix and the cheapest points on the board
   - `type_confusions` are double-penalised — they cost a spurious *and* a
     missing entity across all three terms
   - assertion `fp` greatly exceeding `fn` means the rules are firing on
     hypothetical/educational context; tighten the veto rather than the model

5. **Noise floor.** With a dev set under ~60 documents, treat any delta below
   **0.010** in `final_score` as noise. Do not report it as an improvement.

If `--gold` was not supplied, only the structural summary is available: say so,
report the entity/type/span distribution, and note that scoring needs a
hand-labelled gold directory.
