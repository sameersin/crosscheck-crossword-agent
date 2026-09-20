# Internal implementation contract

Shared models are in `src/crossword_agent/models.py`; root owns this file.

## Domain and search (solver agent owns)

`domain.py`: dataclass `Entry(id: str, number: int, direction: str, row: int, col: int, length: int, cells: tuple[tuple[int,int],...], clue: str)`; `parse_entries(puzzle: Puzzle) -> list[Entry]` derives standard row-major numbering and checks exact clue mapping; raise `PuzzleValidationError(ValueError)` for structural errors. Runs >=2 supported; every open cell must belong to an entry. `render_grid(puzzle, assignments: dict[str,str]) -> list[str]`; `validate_assignments(puzzle, assignments) -> list[str]`; `entry_pattern(puzzle, entry, assignments=None) -> str` using '.' unknown, supplied letters plus compatible tentative letters. `normalize_answer(text: str) -> str`.

`search.py`: `SearchResult` dataclass fields `assignments: dict[str,str]`, `complete: bool`, `nodes: int`, `exhausted: bool`, `blocked_entries: list[str]`, `score: float`. `solve_constraints(puzzle: Puzzle, candidates: dict[str,list[Candidate]], *, max_nodes: int=100000, deadline: float|None=None) -> SearchResult`; deadline is time.monotonic absolute. Return best consistent partial assignment on infeasibility/budget. Never modify supplied letters. Reconsider previous guesses on every call. Search ranks candidates and entries; report limit honestly. Agent owns domain/search and their tests only.

## Provider/controller (root owns)

Provider protocol `generate(entries: list[Entry], *, patterns: dict[str,str], previous: dict[str,list[str]], limit: int, timeout: float) -> GenerationBatch`; `GenerationBatch.candidates` mapping, `.usage` Usage. Provider raises sanitized `ProviderError` with retryable bool. `CrosswordAgent(provider, model="...").solve(puzzle, options=None, on_event=None, cancel_event=None) -> SolveResult`. Event callbacks receive AgentEvent. Provider text/image JSON schema validated. Every actual attempt counted; bounded transport retries in controller.

## API (root owns) and browser (frontend agent owns static/)

GET `/api/config` -> `{provider_ready:bool, model:str, limits:{max_image_bytes:int}, version:str}`.
GET `/api/samples` -> `{samples:[{id,title,rows,cols,description}]}`. GET `/api/samples/{id}` -> Puzzle.
POST `/api/validate` with Puzzle -> `{puzzle: Puzzle, entries:[{id,number,direction,row,col,length,cells,clue}]}`; validation errors 422 `{detail:...}`.
POST `/api/solve` with SolveRequest -> 202 `{job_id:str}`. GET `/api/jobs/{job_id}` -> `{job_id,status:'queued'|'running'|'completed'|'failed'|'cancelled',events:AgentEvent[],result:SolveResult|null,error:str|null}`. POST `/api/jobs/{id}/cancel` requests cancellation.
POST `/api/extract` multipart `file` image -> `{puzzle:Puzzle,warnings:list[str]}`. Always preview/edit/validate extraction before solve. PNG/JPEG/WebP, <=10MB. No uploads retained.
GET `/api/evaluation` -> saved public evaluation summary JSON (or `{available:false}`).
Serve static/index.html at `/`, CSS/JS under `/static/`. No external CDN needed. Frontend root owns no API files. Provide responsive polished accessible app with grid/clue highlight, actual event timeline, JSON upload, image extraction preview editor, candidate/result inspection, download result, evaluation + architecture explanations. Never claim accuracy without reference. Escape untrusted text.

## Evaluation (evaluation agent owns)

Data: `data/puzzles/*.json` only Puzzle inputs; `data/solutions/*.json` keys `{puzzle_id,grid:[solved rows]}`; `data/manifest.json` provenance/split/difficulty metadata. APIs must never serve solution keys to solver. Build 6-10 small original fixtures incl blocked rectangular examples and 5x5 word squares; document these as authored smoke benchmark, not public heldout production benchmark. Validate clues/keys carefully. `evaluation.py` evaluates real outputs vs separate keys, baseline first-choice vs search vs full agent (same initial candidates for paired comparison when feasible), metrics letter/entry/puzzle accuracy, completion, violations, candidate recall, tokens/time. CLI root will wire; export simple `evaluate_result(puzzle, reference_grid, result) -> dict` and `run_evaluation(...)` if feasible agree root. Tests verify blanks denominator and conflicts not correct. Do not fake live metrics. Write docs/EVALUATION.md with methodology; docs/DEMO_SCRIPT.md <=60s. Evaluation report generated under artifacts/evaluation/ by live run later.
