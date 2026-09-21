# Actual user-image verification

The latest saved runs match all three independent references. These are **development case studies on reported failures**, not a held-out benchmark. Actual GLM-5.3-Flash image extraction used detected cell geometry, and reference answers stayed separate from model inputs. The original extraction outputs were reused for the latest solving runs.

| Image | Grid / entries | Correct entries | Correct cells | Hard violations | Extraction calls / time | Latest solve calls / time |
| --- | --- | --- | --- | --- | --- | --- |
| Pets | 8×11 / 7 | 7/7 | 28/28 | 0 | 1 / 5.530s | 3 / 3.328s |
| Cocoa | 11×16 / 12 | 12/12 | 64/64 | 0 | 1 / 7.390s | 2 / 6.813s |
| Math | 10×10 / 48 | 48/48 | 68/68 | 0 | 1 / 8.330s | 0 / 0.015s |

All three extracted cell masks, clue-number/length mappings, and clue meanings matched the independent visual transcriptions. The clue comparison permits typographic differences in punctuation, blank underscores, and equivalent Unicode minus signs.

Pets answers were manually derived from the visible clues and checked against every crossing. Math answers were independently recomputed from all 48 printed integer expressions and then checked against crossings. Neither reference is presented as an official publisher key.

For cocoa, the [publisher answer key, page 2](https://www.word-game-world.com/support-files/cocoa-crossword.pdf#page=2) confirms **NESQUIK** for 6 Down. The first saved run instead selected **NESTLES**: it filled every cell consistently, but matched only **11/12 entries and 60/64 cells**. Both candidates fit the seven-cell slot and its single checked letter, so crossing checks cannot settle that clue. The first output and its verification are preserved in `cocoa.first-run.result.json` and `cocoa.first-run.verification.json`.

The latest cocoa run selects NESQUIK and matches the complete reference. Its trace includes the new independent-review step, but NESQUIK was **already its initial candidate**. Review added HERSHEY as another candidate while preserving NESQUIK. This trace therefore does not demonstrate review correcting the earlier NESTLES error; it demonstrates a successful later run with different initial model output. A larger paired evaluation would be needed to measure the review step's benefit.

Provider-call counts include recorded attempts, including schema/transport retries. Math used deterministic arithmetic after the real image-extraction call; its configured solver-model label does not mean a model was invoked during arithmetic solving. Extraction plus latest-solving stage sums are 8.858s, 14.203s, and 8.345s respectively. They exclude human review and time between stages. Attribution includes the reused extraction call once per case; these counts are not the total bill for all debugging runs. Dollar costs remain unknown without explicit prices.

The cocoa extraction warning claiming no printed clue numbers is inaccurate: the numbers are visible and the extracted mapping matches them. Raw model warnings are retained separately from verified geometry and clue checks.

Each current `.verification.json` records entry-level comparisons, reference provenance, usage, stage durations, independent geometry checks, and extraction warnings. `verify_saved_runs.py` reproduces these checks locally without making model calls. Verification does not alter extracted puzzles or solver results.
