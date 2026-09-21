# How evaluation works

The main question is **whether the returned letters match a separate answer key**. A grid can be completely filled, have no crossing conflicts, and still answer a clue incorrectly. The solver reports `complete_consistent`; only the evaluator, which has an answer key, can establish exact correctness on a benchmark puzzle.

The browser also supports interactive evaluation of saved runs. You can create a key by reviewing a copy of the solved grid, importing JSON, or transcribing a solved image. This uses the same deterministic scoring function as the benchmark. Human-approved copies are labelled with their provenance; approval does not establish independent ground truth. See [INTERACTIVE_EVALUATION.md](INTERACTIVE_EVALUATION.md) for the complete workflow and trust boundaries.

## Included data and honest scope

`data/manifest.json` records the provenance, split, shape, and difficulty label for every fixture. The ten fixtures are locally authored assessment examples: four development puzzles and six test puzzles. These are **smoke tests, not a representative newspaper-crossword benchmark**. We make no claim that common word-square arrangements are new or unknown to the model.

The suite contains 3×3 asymmetric and word-square examples, 4×4 and 5×5 word squares, a fully checked asymmetric blocked 4×4, supplied letters, and sparse blocked 5×5, 5×7, and 7×7 grids. Word squares repeat answers across directions; sparse crosses have many unchecked letters. Both make the suite easier and less representative. Difficulty has not been independently calibrated. Cryptic clues, rebus cells, and languages other than English are outside the initial scope.

- `data/puzzles/` holds only grids, metadata, and clues that a solver can see.
- `data/solutions/` holds separately loaded reference grids. The evaluator never supplies these to a model or to search.
- Development fixtures are available for prompt/debug iteration. The test fixtures are reserved for the final comparison; they are only held out from local development, not guaranteed absent from model training.

The evaluator validates reference dimensions, block positions, full letter coverage, matching puzzle IDs, and agreement with supplied letters before making any paid model calls. A broken key is an evaluation error, not a failed puzzle.

## Three paired comparisons

For each puzzle, the runner requests a candidate list for every clue exactly once, respecting the configured batch size. All three arms reuse these same initial responses after identical normalization and hard-input filtering.

| Arm | What it does | What it tests |
| --- | --- | --- |
| `baseline_first_choice` | Takes the highest-scored initial candidate independently for every clue. Conflicting letters are displayed as blanks. | How well clue generation works without crossing search. |
| `baseline_search` | Runs one bounded constraint search on the initial candidates. | The benefit of combining answers using crossing rules. |
| `agent` | Starts with those candidates, searches, then requests targeted repairs if necessary. | Whether adaptive regeneration improves over the initial candidate pool. |

This is a paired architecture comparison, **not** a claim that all three arms consume the same total tokens. The full agent may use additional calls. The first-choice baseline deliberately gets the same multi-candidate response as search, so it is not a measurement of a cheaper single-answer prompt. The search and agent receive the same model, initial responses, search-node setting, and initial total time budget. For the agent, initial generation time and calls are deducted from the remaining budget. Each arm's reported elapsed time includes that shared generation time plus its own work.

Reported per-arm token/call usage includes the shared initial generation. These are the attributed costs of running that arm; **do not add the three arms' costs to estimate the actual bill for the benchmark run**, because the initial calls were made only once. Provider token counts are recorded when returned. Failed requests still count as attempted calls. Dollar cost stays `null` unless explicit price configuration provides a basis for estimating it; no price is invented.

## Metrics

All accuracy/coverage values in the JSON report are fractions between 0 and 1.

Numeric crossword inputs declare `answer_type: "digits"` and use one digit per cell. For these puzzles, `cell_accuracy` is the clearer metric name; it is identical to the retained `letter_accuracy` field for backward compatibility. Likewise, `unknown_cell_accuracy` aliases `unknown_letter_accuracy`. A `0` is an ordinary filled digit, never a blank. Numeric candidate normalization preserves signs, decimal points, and internal spaces so `-10` or `1.0` cannot silently become the valid answer `10`. Reference keys and candidate recall use the puzzle's declared answer type.

| Metric | Definition |
| --- | --- |
| Letter accuracy | Correct open cells ÷ all open cells; blanks count as incorrect. Black cells are excluded. |
| Unknown-letter accuracy | Correct cells that were initially blank ÷ all initially blank cells. This prevents supplied letters from inflating the apparent amount solved. |
| Answer accuracy | Entirely correct across/down entries ÷ all entries. A single wrong or blank letter makes an entry incorrect. |
| Exact-puzzle accuracy | Puzzles with every letter correct and no structural/assignment violations ÷ all evaluated puzzles. |
| Completion | Filled open cells ÷ all open cells, regardless of whether their letters are right. |
| Complete-consistent rate | Puzzles whose grids are filled and independently pass hard checks ÷ all puzzles. This is not correctness. |
| Constraint violations | Independently observed length, character, supplied-letter, crossing, grid, or assignment/display errors. This is a count of diagnostics, not a calibrated severity score. |
| Candidate recall | Entries whose correct answer occurs somewhere in their candidate pool ÷ all entries. The agent's pool includes later candidates. |
| Runtime and usage | Wall-clock seconds, attempted model calls, prompt/completion/total tokens, and optional explicitly priced estimated cost. |

Letter/answer/candidate-recall summaries use **micro averages**: add their numerators and denominators across puzzles. Exact-puzzle accuracy is a fraction of puzzles. Runtime is the mean per puzzle. All attempted puzzles remain in denominators, including provider errors and budget exhaustion.

The evaluator independently reconstructs hard checks. It does not trust a result's `status`, `filled_cells`, or reported violation list. Conflicting assignments cannot receive credit merely because the displayed grid happens to show the correct side of a crossing. Detailed per-entry success flags, candidate hits, errors, outputs, model ID, budget settings, and generation timestamps are retained in the saved report.

## Run it

After installing the project and configuring `.env` as described in the README:

```powershell
crossword evaluate --split dev --seconds 180 --rounds 4
crossword evaluate --split test --seconds 180 --rounds 4
```

The runner writes `artifacts/evaluation/dev.json` or `test.json`, plus `report.json` containing the latest run. The browser reads the saved report. The model and live performance are not inferred from unit tests. Unit tests use a fake provider solely to verify metric arithmetic, geometry, error handling, and paired reuse without spending tokens.

```powershell
python -m pytest tests/test_evaluation.py -q
```

## What stronger evaluation would add

1. Assemble a larger rights-cleared collection of ordinary crosswords across sizes, clue styles, and publishers. Freeze the development/test split before tuning. Record source and date.
2. Add newly authored puzzles with independent human verification. This reduces, but does not prove the absence of, training-data overlap. Include substantially harder and larger puzzles.
3. Repeat each configuration with recorded settings and report variability, failure rates, and uncertainty rather than only a single best run. Compare both equal-budget conditions and quality-versus-cost curves.
4. Label failure causes: wrong extraction, missing correct candidate, wrong ranking, search budget, ambiguous clue, provider failure, or retry that did not improve the domain. Candidate recall helps separate generation failures from search failures.
5. Evaluate images separately using exact grid/block recovery, clue-text recovery, numbering/entry mapping, and fraction requiring human correction. Compare solving the verified JSON against solving its extracted counterpart. Screenshot upload always requires a preview because extraction errors should not silently become crossword failures.

This separation makes interview claims precise: the tests establish program behavior; live saved reports establish performance on the stated small suite; neither establishes general production crossword accuracy.

Geometry regressions in `tests/test_vision.py` generate portable dense, blocked, sparse, supplied-character, and decorative-shape images. Three additional tests compare the user's local pets, cocoa, and math worksheets with independent visual transcriptions; these tests skip when those local files are unavailable. All three local images passed the geometry comparison in the September 21 validation run. This verifies their cell masks, not general OCR accuracy or complete clue extraction. Saved actual extraction/solving case studies and their limitations are documented separately in `artifacts/user-puzzles/RESULTS.md`; they are development reproductions, not additions to the held-out smoke split.

## Controlled robustness checks

The live smoke suite can be solved correctly on the first pass, so a perfect result on it does not establish that regeneration improves model performance. A separate script exercises failure-handling mechanisms deliberately:

```powershell
python scripts/run_robustness.py
```

It writes `artifacts/evaluation/robustness.json`, separately from the live model report. Four checks with explicit pass/fail predicates cover missing candidates supplied on a later request, a high-scored wrong answer rejected by crossing search, a call limit returning a consistent partial result, and a fully consistent wrong fill rejected by reference evaluation. Actual controller events, candidate requests, and final outputs are preserved.

**These are deterministic mechanism checks, not LLM accuracy results.** The fake provider deliberately knows the development fixture answers through the harness and returns predefined candidate lists. There are no network calls; its `model_calls` usage values count simulated provider invocations. This demonstrates that the code can recover from the specified injected failures, without claiming that the live model naturally made or recovered from those mistakes.
