# Use Crosscheck

## Solve a puzzle

1. Start the app using [Setup](SETUP.md) and open the local address.
2. In **Workspace**, choose an authored sample or a saved image case. Saved cases show historical results until you start a new solve.
3. Alternatively, upload puzzle JSON or an image containing the grid and all clues. For images, inspect the transcription, edit errors and validate before accepting it.
4. Adjust the time, rounds, candidates and model-call limits if needed. Click **Solve**.
5. Follow the activity log, inspect answers/candidates, and download the result JSON. **Stop solve** requests cooperative cancellation; an in-flight model request may need to return or time out first.

`Complete and consistent` means the grid obeys structural rules. It does not prove every clue answer is right.

## JSON input

```json
{
  "id": "mini",
  "title": "A tiny example",
  "grid": ["...", "...", "..."],
  "clues": {
    "across": {"1": "Feline", "4": "Large primate", "5": "Bread grain"},
    "down": {"1": "Road vehicle", "2": "Savings yield, briefly", "3": "Golf ball support"}
  }
}
```

- `.` is empty; `#` is a block or absent worksheet cell.
- A–Z are supplied letters and cannot change.
- Set `"answer_type": "digits"` for numeric puzzles; supplied digits, including zero, remain fixed.
- Code derives standard row-major clue numbers and crossings. Each entry of at least two cells needs one clue. Grids must be rectangular, 2–25 cells per side.

Cryptic-specific logic, rebus cells, non-English alphabets and arbitrary custom numbering are outside the supported scope. For sparse worksheets, background positions are `#`.

The result JSON contains the filled `grid`, `assignments` such as `1A`/`1D`, unresolved entries, structural violations, candidates, time, calls/tokens and an event trace. Possible result statuses include `complete_consistent`, `partial`, `cancelled` and `provider_error`.

## Evaluate an attempt

Think of the saved attempt as a student's submitted test and the answer key as the teacher's marking sheet. Editing the marking sheet never changes the submission.

1. Choose **Evaluate this run**, or open **Evaluation** and choose an original attempt.
2. Supply a key in one of three ways: correct the copied grid, upload/drop/paste JSON, or upload/paste a solved answer image.
3. Review every answer, including unchanged letters. Image output is only a draft. Italic peach cells show changes from the agent's original answers.
4. Confirm the key belongs to the selected puzzle and that you checked every answer against a trusted source.
5. Click **Approve key & evaluate**. Download the report or inspect differences and history.

You do not need an answer image if you can provide a correct key manually or as JSON. A publisher key or independent human solution is stronger evidence than agreeing with an agent-generated copy.

A key JSON contains `reference_grid`, an array of fully filled row strings with `#` in the original block positions. Downloaded keys include the puzzle ID and fingerprint to help prevent accidental mismatches. Incomplete keys cannot receive a full-puzzle accuracy score.

The chart shows whole-answer accuracy per attempt. Repeated attempts are separate bars. Ungraded runs have no accuracy score; the perfect-run summary counts only graded attempts and shows its denominator.

For example, 60 correct letters out of 64 means **93.75% cell accuracy**. Eleven correct words out of twelve means **91.67% answer accuracy**. All 64 squares filled means **100% completion**, even when some are wrong. This is not an exact puzzle.

See [the evaluation guide](INTERACTIVE_EVALUATION.md) for key provenance, image extraction and metric details.

## Command line

```shell
uv run --frozen crossword solve data/puzzles/dev-mixed-3.json --output artifacts/my-result.json
```

This makes real model requests. Use `--seconds` and `--rounds` to bound the run, or `uv run --frozen crossword --help` to see available commands. The dashboard is the image-import and interactive key-review interface.
