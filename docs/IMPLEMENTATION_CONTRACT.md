# Interface contracts

This is the current component/API map. Interactive request schemas are available at **http://127.0.0.1:8000/docs** while the server is running; the generated OpenAPI document is at `/openapi.json`.

## Domain contracts

- `Puzzle` in `models.py`: ID, title, rectangular grid, across/down clues and optional `answer_type` (`letters` or `digits`).
- `parse_entries` in `domain.py`: derive row-major numbering, entry positions, lengths and crossings; reject invalid topology or clue mappings.
- `SolveOptions`: bounded rounds, calls, time, candidates and search work.
- `CrosswordAgent.solve`: returns `SolveResult` with grid, assignments, candidates, usage and events, including partial/error/cancelled outcomes.
- `evaluate_result` in `evaluation.py`: compare a result with a separately supplied reference.
- `EvaluationStore`: preserve original snapshots, version approved keys and retain reference-image extraction records separately.

The model does not control grid topology or bypass the constraints. Reference answers are evaluation inputs only.

## HTTP endpoints

| Method and path | Purpose |
|---|---|
| `GET /health`, `/api/health` | Version and model metadata |
| `GET /api/config` | Safe public settings; never the API key |
| `GET /api/samples` | Authored input catalog |
| `GET /api/samples/{puzzle_id}` | One authored puzzle input |
| `GET /api/user-puzzles` | Saved development case catalog |
| `GET /api/user-puzzles/{puzzle_id}` | Saved input/result and development verification |
| `POST /api/validate` | Validate a `Puzzle`; return normalized puzzle and entries |
| `POST /api/solve` | Submit `{puzzle, options}`; return HTTP 202 and `job_id` |
| `GET /api/jobs/{job_id}` | Job status, trace and result/error |
| `POST /api/jobs/{job_id}/cancel` | Request cooperative cancellation |
| `POST /api/extract` | Multipart `file`; return a draft puzzle transcription |
| `GET /api/runs` | Paginated durable history (`limit`, `offset`) |
| `GET /api/runs/{run_id}` | Original snapshot and reference/evaluation history |
| `POST /api/runs/{run_id}/reference-image` | Multipart `file`; return an unapproved draft key |
| `POST /api/runs/{run_id}/evaluate` | Grade the stored original against an explicitly approved key |
| `GET /api/evaluation` | Separately labelled historical benchmark report |

Validation errors use HTTP 422, missing records 404, capacity limits 429, missing provider configuration 503, and handled provider failures 502 for image endpoints. Solve-provider failures appear in job/result status.

## Reference approval

The grading request requires `reference_grid`, `source` and boolean `approved: true`. Optional `puzzle_id` and `puzzle_fingerprint` prevent accidental mismatches when supplied. `source_note` stores provenance. Supported sources are `human_reviewed_agent_copy`, `human_entered`, `uploaded_json`, `publisher_key` and `uploaded_image`.

The server validates shape, blocks, givens and completeness, and scores its own stored original result. A client cannot submit a replacement original result to improve the score. An approved reference is a user's reviewed key, not automatic proof of independent ground truth.

See [the user guide](USER_GUIDE.md) for examples and [the architecture](ARCHITECTURE.md) for module ownership.
