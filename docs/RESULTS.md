# Measured verification results

These are observed development results, not predicted performance or a claim about all crosswords. Full candidate lists, per-puzzle metrics, usage and controller events are stored in the linked JSON reports.

## Live model evaluation

Provider: Nebius Token Factory, `https://api.tokenfactory.us-north1.nebius.com/v1/`.
Model: `zai-org/GLM-5.3-Flash`.

| Test split (6 authored puzzles) | First-choice baseline | Constraint search | Full agent |
|---|---:|---:|---:|
| Correct letters | 108 / 108 | 108 / 108 | 108 / 108 |
| Correct entries | 40 / 40 | 40 / 40 | 40 / 40 |
| Exact puzzles | 6 / 6 | 6 / 6 | 6 / 6 |
| Constraint violations | 0 | 0 | 0 |
| Model calls attributed to each arm | 6 | 6 | 6 |
| Average runtime | 1.35 s | 1.35 s | 1.35 s |

The arms share their initial model responses; these are **six actual calls**, not eighteen. No repair calls were needed on this test run. Its 2,887 prompt tokens and 1,055 completion tokens totaled 3,942 tokens. Dollar cost is not asserted because provider prices were not configured.

The separate four-puzzle development smoke run also matched all 51 letters and 24 entries. Development scores are not additional held-out evidence.

**Interpretation:** the pipeline works on these small authored fixtures, but all three arms tie. This run does not establish that the full agent outperforms simple clue answering. Several fixtures are word squares or sparse crosses, and the suite is too small/easy to support broad accuracy claims. See [EVALUATION.md](EVALUATION.md) for the next evaluation design.

- [Test report](../artifacts/evaluation/test.json)
- [Development report](../artifacts/evaluation-dev/dev.json)
- [Dataset provenance and limitations](../data/manifest.json)

## Image input

A generated **input-only** PNG of the original 4x4 development puzzle was sent to the actual configured model through the image extraction HTTP endpoint. Its grid and across/down clue text matched the input exactly, and the extracted representation passed structural validation. The subsequent HTTP solve matched the separate reference grid.

This is a clean screenshot smoke check, not evidence of accuracy on arbitrary camera photos, skew, blur, handwritten letters, or complex layouts. Those remain distinct evaluation cases.

- [Input image](../data/images/sample-crossword.png)
- [Extraction response](../artifacts/verification/image-extraction.json)
- [Image-to-solve verification](../artifacts/verification/image-to-solve.json)

## Controlled mechanism checks

The regression suite uses scripted providers and independently checked candidate sets to exercise missing candidates, crossing conflicts, backtracking, fixed letters, provider failures, budgets, cancellation and invalid input. These deterministic checks establish implementation behavior; they are **not** live language-model accuracy measurements.

The independent evaluator also rejects a completely filled and structurally consistent grid when its letters disagree with the answer key.

All four [controlled robustness scenarios](../artifacts/evaluation/robustness.json) passed: missing candidates trigger repair; a high-scoring crossing conflict is rejected; exhausted calls return partial output; and a full but wrong grid fails reference scoring. These used zero network calls. Reproduce with `uv run python scripts/run_robustness.py`.

## Reproducibility

Run `uv run pytest -q` for offline checks and `uv run crossword evaluate --split test` for a new paid model run. Results may change with model sampling or provider updates. The checked-in report contains its generation timestamp and options. Keep original reports when comparing later changes; do not substitute a rerun without documenting it.
