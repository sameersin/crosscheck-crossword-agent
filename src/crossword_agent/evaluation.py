"""Reference-based evaluation. Answer keys are never passed to a solver or provider.

The authored smoke suite supports paired ablations: all three arms share the
same initial model responses, while only the full agent can request more.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from .domain import is_valid_answer, normalize_answer, parse_entries, validate_assignments
from .models import Candidate, Puzzle, SolveOptions, SolveResult, Usage


def validate_reference(puzzle: Puzzle, reference_grid: list[str]) -> None:
    """Reject malformed or incompatible keys instead of silently scoring them."""
    parse_entries(puzzle)
    if len(reference_grid) != len(puzzle.grid):
        raise ValueError("Reference grid height does not match puzzle.")
    for row, reference in zip(puzzle.grid, reference_grid, strict=True):
        if not isinstance(reference, str) or len(reference) != len(row):
            raise ValueError("Reference grid width does not match puzzle.")
        for supplied, expected in zip(row, reference, strict=True):
            if supplied == "#":
                if expected != "#":
                    raise ValueError("Reference black squares do not match puzzle.")
            elif not is_valid_answer(expected, puzzle.answer_type):
                label = "digit" if puzzle.answer_type == "digits" else "uppercase letter"
                raise ValueError(f"Every open reference cell must contain one {label}.")
            elif supplied != "." and supplied != expected:
                raise ValueError("Reference solution disagrees with a supplied letter or digit.")


def _reference_answers(puzzle: Puzzle, grid: list[str]) -> dict[str, str]:
    return {
        entry.id: "".join(grid[row][col] for row, col in entry.cells)
        for entry in parse_entries(puzzle)
    }


def evaluate_result(
    puzzle: Puzzle, reference_grid: list[str], result: SolveResult
) -> dict[str, Any]:
    """Score a result independently of its reported completion/violation fields.

    Blank cells are wrong. Contradictory assignments cannot earn credit through
    whichever letter happens to be displayed. Completion measures coverage, not
    correctness. All accuracy values are fractions in [0, 1].
    """
    validate_reference(puzzle, reference_grid)
    entries = parse_entries(puzzle)
    references = _reference_answers(puzzle, reference_grid)
    violations = list(validate_assignments(puzzle, result.assignments))
    if result.puzzle_id != puzzle.id:
        violations.append("Result puzzle_id does not match the evaluated puzzle.")
    height, width = len(puzzle.grid), len(puzzle.grid[0])
    if len(result.grid) != height or any(len(row) != width for row in result.grid):
        violations.append("Result grid dimensions do not match puzzle.")

    def displayed(row: int, col: int) -> str:
        if row >= len(result.grid) or col >= len(result.grid[row]):
            return "."
        return result.grid[row][col]

    claimed: dict[tuple[int, int], set[str]] = {}
    invalid_cells: set[tuple[int, int]] = set()
    for entry in entries:
        answer = result.assignments.get(entry.id)
        if answer is None:
            continue
        if len(answer) != entry.length or not is_valid_answer(answer, entry.answer_type):
            invalid_cells.update(entry.cells)
            violations.append(f"{entry.id} has a malformed output assignment.")
            continue
        for (row, col), letter in zip(entry.cells, answer, strict=True):
            claimed.setdefault((row, col), set()).add(letter)
            if displayed(row, col) != letter:
                invalid_cells.add((row, col))
                violations.append(f"Displayed cell ({row}, {col}) disagrees with {entry.id}.")
    for cell, letters in claimed.items():
        if len(letters) > 1:
            invalid_cells.add(cell)

    total_cells = correct_cells = filled_cells = fixed_cells = correct_unknown_cells = 0
    for row in range(height):
        for col in range(width):
            supplied, actual = puzzle.grid[row][col], displayed(row, col)
            if supplied == "#":
                if actual != "#":
                    violations.append(f"Result changes black square ({row}, {col}).")
                continue
            total_cells += 1
            if supplied != ".":
                fixed_cells += 1
                if actual != supplied:
                    violations.append(f"Result changes supplied character ({row}, {col}).")
                    invalid_cells.add((row, col))
            if len(actual) == 1 and is_valid_answer(actual, puzzle.answer_type):
                filled_cells += 1
            elif actual != ".":
                violations.append(f"Invalid result cell ({row}, {col}).")
            if actual == reference_grid[row][col] and (row, col) not in invalid_cells:
                correct_cells += 1
                if supplied == ".":
                    correct_unknown_cells += 1

    correct_entries = filled_entries = candidate_hits = 0
    details = []
    for entry in entries:
        actual = "".join(displayed(row, col) for row, col in entry.cells)
        filled = is_valid_answer(actual, entry.answer_type)
        correct = actual == references[entry.id] and not any(
            cell in invalid_cells for cell in entry.cells
        )
        hit = any(
            normalize_answer(candidate.answer, entry.answer_type) == references[entry.id]
            for candidate in result.candidates.get(entry.id, [])
        )
        correct_entries += int(correct)
        filled_entries += int(filled)
        candidate_hits += int(hit)
        details.append(
            {"entry_id": entry.id, "answer": actual, "correct": correct, "candidate_hit": hit}
        )

    violations = list(dict.fromkeys(violations))
    unknown_cells = total_cells - fixed_cells
    return {
        "puzzle_id": puzzle.id,
        "answer_type": puzzle.answer_type,
        "status": result.status,
        "correct_cells": correct_cells,
        "total_cells": total_cells,
        "letter_accuracy": correct_cells / total_cells,
        "cell_accuracy": correct_cells / total_cells,
        "correct_unknown_cells": correct_unknown_cells,
        "unknown_cells": unknown_cells,
        "unknown_letter_accuracy": correct_unknown_cells / unknown_cells if unknown_cells else None,
        "unknown_cell_accuracy": correct_unknown_cells / unknown_cells if unknown_cells else None,
        "fixed_cells": fixed_cells,
        "correct_entries": correct_entries,
        "total_entries": len(entries),
        "answer_accuracy": correct_entries / len(entries),
        "exact_puzzle": correct_cells == total_cells and not violations,
        "filled_cells": filled_cells,
        "completion": filled_cells / total_cells,
        "filled_entries": filled_entries,
        "entry_completion": filled_entries / len(entries),
        "complete_consistent": filled_cells == total_cells and not violations,
        "constraint_violation_count": len(violations),
        "constraint_violations": violations,
        "candidate_hits": candidate_hits,
        "candidate_recall": candidate_hits / len(entries),
        "elapsed_seconds": result.elapsed_seconds,
        "search_nodes": result.search_nodes,
        "rounds": result.rounds,
        "usage": result.usage.model_dump(),
        "entries": details,
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Micro letter/answer accuracy; macro exact-puzzle rate and mean runtime."""
    if not rows:
        raise ValueError("Cannot aggregate an empty evaluation split.")
    cell_total = sum(row["total_cells"] for row in rows)
    entry_total = sum(row["total_entries"] for row in rows)
    unknown_total = sum(row["unknown_cells"] for row in rows)
    costs = [row["usage"].get("estimated_cost_usd") for row in rows]
    usage = {
        key: sum(row["usage"].get(key, 0) for row in rows)
        for key in ("model_calls", "prompt_tokens", "completion_tokens", "total_tokens")
    }
    usage["estimated_cost_usd"] = sum(costs) if all(cost is not None for cost in costs) else None
    return {
        "puzzle_count": len(rows),
        "correct_cells": sum(row["correct_cells"] for row in rows),
        "total_cells": cell_total,
        "letter_accuracy": sum(row["correct_cells"] for row in rows) / cell_total,
        "cell_accuracy": sum(row["correct_cells"] for row in rows) / cell_total,
        "correct_entries": sum(row["correct_entries"] for row in rows),
        "total_entries": entry_total,
        "answer_accuracy": sum(row["correct_entries"] for row in rows) / entry_total,
        "unknown_letter_accuracy": sum(row["correct_unknown_cells"] for row in rows) / unknown_total
        if unknown_total
        else None,
        "unknown_cell_accuracy": sum(row["correct_unknown_cells"] for row in rows) / unknown_total
        if unknown_total
        else None,
        "exact_puzzle_accuracy": mean(int(row["exact_puzzle"]) for row in rows),
        "exact_puzzles": sum(int(row["exact_puzzle"]) for row in rows),
        "completion": sum(row["filled_cells"] for row in rows) / cell_total,
        "complete_consistent_rate": mean(int(row["complete_consistent"]) for row in rows),
        "constraint_violation_count": sum(row["constraint_violation_count"] for row in rows),
        "candidate_recall": sum(row["candidate_hits"] for row in rows) / entry_total,
        "mean_elapsed_seconds": mean(row["elapsed_seconds"] for row in rows),
        "usage": usage,
    }


def _conflict_aware_grid(puzzle: Puzzle, assignments: dict[str, str]) -> list[str]:
    claims: dict[tuple[int, int], set[str]] = {}
    for entry in parse_entries(puzzle):
        answer = assignments.get(entry.id)
        if (
            answer is None
            or len(answer) != entry.length
            or not is_valid_answer(answer, entry.answer_type)
        ):
            continue
        for cell, char in zip(entry.cells, answer, strict=True):
            claims.setdefault(cell, set()).add(char)
    grid = [list(row) for row in puzzle.grid]
    for (row, col), letters in claims.items():
        if puzzle.grid[row][col] != ".":
            continue
        grid[row][col] = next(iter(letters)) if len(letters) == 1 else "."
    return ["".join(row) for row in grid]


def first_choice_result(
    puzzle: Puzzle,
    candidates: dict[str, list[Candidate]],
    *,
    usage: Usage | None = None,
    elapsed_seconds: float = 0,
    model: str = "",
) -> SolveResult:
    """Choose each clue's top-scored response independently; expose conflicts."""
    assignments = {}
    entries = parse_entries(puzzle)
    for entry in entries:
        choices = candidates.get(entry.id, [])
        if choices:
            assignments[entry.id] = normalize_answer(
                max(choices, key=lambda item: item.score).answer, entry.answer_type
            )
    grid = _conflict_aware_grid(puzzle, assignments)
    violations = validate_assignments(puzzle, assignments)
    complete = all("." not in row for row in grid) and not violations
    return SolveResult(
        puzzle_id=puzzle.id,
        status="complete_consistent" if complete else "partial",
        grid=grid,
        assignments=assignments,
        unresolved_entries=[entry.id for entry in entries if entry.id not in assignments],
        constraint_violations=violations,
        filled_cells=sum(is_valid_answer(char, puzzle.answer_type) for row in grid for char in row),
        total_cells=sum(char != "#" for row in puzzle.grid for char in row),
        elapsed_seconds=elapsed_seconds,
        rounds=1,
        search_nodes=0,
        stop_reason="Independent highest-scored candidate for each clue; no crossing search.",
        usage=usage or Usage(),
        candidates=candidates,
        initial_candidates=candidates,
        model=model,
    )


def _add_usage(left: Usage, right: Usage) -> Usage:
    cost = None
    if right.estimated_cost_usd is not None and (
        left.model_calls == 0 or left.estimated_cost_usd is not None
    ):
        cost = (left.estimated_cost_usd or 0) + right.estimated_cost_usd
    return Usage(
        model_calls=left.model_calls + right.model_calls,
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
        estimated_cost_usd=cost,
    )


def run_evaluation(
    provider: Any,
    model: str,
    *,
    data_dir: Path,
    output_dir: Path,
    split: str = "test",
    options: SolveOptions | None = None,
) -> dict[str, Any]:
    """Run real paired ablations and atomically save a reproducible report.

    All fixtures stay in the denominator, including provider failures. Initial
    responses are reused across arms; full-agent retries consume its own budget.
    """
    from .agent import CrosswordAgent, merge_candidates
    from .domain import entry_pattern, render_grid
    from .providers.base import ProviderError
    from .search import solve_constraints

    options = options or SolveOptions()
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    selected = [item for item in manifest["puzzles"] if split == "all" or item["split"] == split]
    if not selected:
        raise ValueError(f"No puzzles found for split {split!r}.")
    # Validate the entire selected dataset before spending tokens.
    fixtures = []
    for item in selected:
        puzzle = Puzzle.model_validate_json((data_dir / item["input"]).read_text(encoding="utf-8"))
        key = json.loads((data_dir / item["solution"]).read_text(encoding="utf-8"))
        if key["puzzle_id"] != puzzle.id or item["id"] != puzzle.id:
            raise ValueError("Manifest, puzzle, and reference IDs must agree.")
        validate_reference(puzzle, key["grid"])
        fixtures.append((puzzle, key["grid"]))
    report: dict[str, Any] = {
        "available": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "model": model,
        "dataset": {
            "name": manifest["name"],
            "split": split,
            "puzzle_count": len(fixtures),
            "limitations": manifest["limitations"],
        },
        "options": options.model_dump(),
        "comparison": "Paired initial candidates reused in all arms. Full agent may spend extra calls on retries. No token price assumed.",
        "summary": {},
        "puzzles": [],
    }
    for puzzle, reference in fixtures:
        entries = parse_entries(puzzle)
        initial: dict[str, list[Candidate]] = {}
        usage = Usage()
        errors = []
        start = time.monotonic()
        for offset in range(0, len(entries), options.batch_size):
            remaining = options.max_seconds - (time.monotonic() - start)
            if remaining <= 0 or usage.model_calls >= options.max_calls:
                errors.append("Initial candidate generation reached its time or call budget.")
                break
            batch_entries = entries[offset : offset + options.batch_size]
            try:
                batch = provider.generate(
                    batch_entries,
                    patterns={entry.id: entry_pattern(puzzle, entry) for entry in batch_entries},
                    previous={},
                    limit=options.candidates_per_clue,
                    timeout=remaining,
                )
                merge_candidates(puzzle, batch_entries, initial, batch.candidates)
                usage = _add_usage(usage, batch.usage)
            except ProviderError as exc:
                usage = _add_usage(usage, getattr(exc, "usage", None) or Usage(model_calls=1))
                errors.append(str(exc))
                break
        generation_seconds = time.monotonic() - start
        first = first_choice_result(
            puzzle, initial, usage=usage, elapsed_seconds=generation_seconds, model=model
        )
        search_start = time.monotonic()
        searched = solve_constraints(
            puzzle,
            initial,
            max_nodes=options.max_search_nodes,
            deadline=search_start + max(0, options.max_seconds - generation_seconds),
        )
        searched_grid = render_grid(puzzle, searched.assignments)
        search_result = first.model_copy(
            update={
                "status": "complete_consistent" if searched.complete else "partial",
                "grid": searched_grid,
                "assignments": searched.assignments,
                "unresolved_entries": [
                    entry.id for entry in entries if entry.id not in searched.assignments
                ],
                "constraint_violations": validate_assignments(puzzle, searched.assignments),
                "filled_cells": sum(
                    is_valid_answer(char, puzzle.answer_type)
                    for row in searched_grid
                    for char in row
                ),
                "elapsed_seconds": generation_seconds + time.monotonic() - search_start,
                "search_nodes": searched.nodes,
                "stop_reason": "One constraint search using the shared initial candidates.",
            }
        )
        remaining_seconds = options.max_seconds - generation_seconds
        if remaining_seconds < 5:
            agent_result = search_result.model_copy(
                update={
                    "stop_reason": "Total evaluation time budget exhausted after initial generation; no agent retries."
                }
            )
        else:
            remaining_options = options.model_copy(update={"max_seconds": remaining_seconds})
            agent_result = CrosswordAgent(provider, model=model).solve(
                puzzle, remaining_options, initial_candidates=initial, initial_usage=usage
            )
            agent_result = agent_result.model_copy(
                update={"elapsed_seconds": agent_result.elapsed_seconds + generation_seconds}
            )
        arms = {
            "baseline_first_choice": first,
            "baseline_search": search_result,
            "agent": agent_result,
        }
        report["puzzles"].append(
            {
                "puzzle_id": puzzle.id,
                "title": puzzle.title,
                "initial_generation_seconds": generation_seconds,
                "initial_generation_errors": errors,
                "metrics": {
                    name: evaluate_result(puzzle, reference, result)
                    for name, result in arms.items()
                },
                "results": {name: result.model_dump() for name, result in arms.items()},
            }
        )
    for arm in ("baseline_first_choice", "baseline_search", "agent"):
        report["summary"][arm] = aggregate_metrics(
            [item["metrics"][arm] for item in report["puzzles"]]
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2) + "\n"
    for filename in (f"{split}.json", "report.json"):
        temporary = output_dir / f".{filename}.tmp"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(output_dir / filename)
    return report
