"""Run scripted failure injections without credentials or network calls.

These are deterministic checks of search/controller/evaluator mechanisms, not
measurements of LLM accuracy. The fake provider deliberately knows fixture keys.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crossword_agent.agent import CrosswordAgent
from crossword_agent.domain import Entry, parse_entries, validate_assignments
from crossword_agent.evaluation import evaluate_result, first_choice_result, validate_reference
from crossword_agent.models import Candidate, Puzzle, SolveOptions, Usage
from crossword_agent.providers.base import GenerationBatch

ROOT = Path(__file__).resolve().parents[1]
MODEL = "scripted-fake-provider-not-an-llm"


@dataclass
class ScriptedProvider:
    """Supply predefined candidate lists and record actual controller requests."""

    responses: list[dict[str, list[Candidate]]]
    requests: list[dict[str, Any]] = field(default_factory=list)

    def generate(
        self,
        entries: list[Entry],
        *,
        patterns: dict[str, str],
        previous: dict[str, list[str]],
        limit: int,
        timeout: float,
    ) -> GenerationBatch:
        response_index = min(len(self.requests), len(self.responses) - 1)
        response = self.responses[response_index]
        candidates = {entry.id: response.get(entry.id, [])[:limit] for entry in entries}
        self.requests.append(
            {
                "call": len(self.requests) + 1,
                "entry_ids": [entry.id for entry in entries],
                "patterns": patterns,
                "previous": previous,
                "returned_candidates": {
                    key: [candidate.model_dump() for candidate in values]
                    for key, values in candidates.items()
                },
            }
        )
        # These count fake-provider invocations, not actual paid model requests.
        return GenerationBatch(candidates, Usage(model_calls=1))


def load_fixture() -> tuple[Puzzle, list[str], dict[str, list[Candidate]]]:
    ident = "dev-mixed-3"
    puzzle = Puzzle.model_validate_json(
        (ROOT / "data" / "puzzles" / f"{ident}.json").read_text(encoding="utf-8")
    )
    key = json.loads((ROOT / "data" / "solutions" / f"{ident}.json").read_text(encoding="utf-8"))
    reference = key["grid"]
    validate_reference(puzzle, reference)
    candidates = {
        entry.id: [
            Candidate(answer="".join(reference[row][col] for row, col in entry.cells), score=0.8)
        ]
        for entry in parse_entries(puzzle)
    }
    return puzzle, reference, candidates


def run_checks() -> dict[str, Any]:
    puzzle, reference, correct = load_fixture()
    cases = []
    options = SolveOptions(max_rounds=3, max_calls=3, max_seconds=10)

    # Omit two intersecting entries so the first search leaves a visible blank.
    missing = {key: list(values) for key, values in correct.items()}
    missing["1A"] = []
    missing["1D"] = []
    provider = ScriptedProvider([missing, correct])
    result = CrosswordAgent(provider, model=MODEL).solve(puzzle, options)
    metrics = evaluate_result(puzzle, reference, result)
    searches = [event for event in result.events if event.kind == "search_complete"]
    checks = {
        "first_search_is_incomplete": bool(searches)
        and len(searches[0].data["assignments"]) < len(correct),
        "repair_event_occurred": any(event.kind == "repair" for event in result.events),
        "second_request_contains_missing_entries": len(provider.requests) == 2
        and {"1A", "1D"}.issubset(provider.requests[1]["entry_ids"]),
        "final_status_is_complete": result.status == "complete_consistent",
        "final_grid_matches_reference": metrics["exact_puzzle"],
        "missing_answer_was_added": not result.initial_candidates.get("1A")
        and any(candidate.answer == "CAT" for candidate in result.candidates.get("1A", [])),
    }
    cases.append(
        {
            "id": "missing_candidates_regenerated",
            "description": "The fake provider initially omits 1A and 1D, then supplies reference answers when the real controller asks again.",
            "injection": "Correct candidates deliberately withheld from the first scripted response.",
            "passed": all(checks.values()),
            "checks": checks,
            "provider_requests": provider.requests,
            "metrics": metrics,
            "result": result.model_dump(),
        }
    )

    misleading = {key: list(values) for key, values in correct.items()}
    misleading["1A"] = [Candidate(answer="DOG", score=0.99), Candidate(answer="CAT", score=0.8)]
    baseline = first_choice_result(puzzle, misleading, model=MODEL)
    baseline_metrics = evaluate_result(puzzle, reference, baseline)
    provider = ScriptedProvider([misleading])
    result = CrosswordAgent(provider, model=MODEL).solve(puzzle, options)
    metrics = evaluate_result(puzzle, reference, result)
    checks = {
        "independent_first_choice_is_wrong": not baseline_metrics["exact_puzzle"],
        "search_selects_lower_scored_compatible_answer": result.assignments.get("1A") == "CAT",
        "only_one_scripted_generation": len(provider.requests) == 1,
        "no_regeneration_needed": not any(event.kind == "repair" for event in result.events),
        "final_grid_matches_reference": metrics["exact_puzzle"],
    }
    cases.append(
        {
            "id": "high_score_wrong_candidate_rejected",
            "description": "DOG is deliberately ranked above CAT for 1A. Its letters conflict with the other scripted answers; constraint search chooses CAT.",
            "injection": "Wrong but valid-length candidate assigned the highest uncalibrated model score.",
            "passed": all(checks.values()),
            "checks": checks,
            "provider_requests": provider.requests,
            "baseline_metrics": baseline_metrics,
            "metrics": metrics,
            "result": result.model_dump(),
        }
    )

    provider = ScriptedProvider([missing, correct])
    result = CrosswordAgent(provider, model=MODEL).solve(
        puzzle, options.model_copy(update={"max_calls": 1})
    )
    metrics = evaluate_result(puzzle, reference, result)
    checks = {
        "no_call_beyond_budget": len(provider.requests) == 1 and result.usage.model_calls == 1,
        "status_is_partial": result.status == "partial",
        "stop_reason_is_call_budget": result.stop_reason == "call_budget",
        "usable_partial_assignments_retained": 0 < len(result.assignments) < len(correct),
        "partial_grid_has_a_blank": any("." in row for row in result.grid),
        "partial_assignments_are_consistent": not validate_assignments(puzzle, result.assignments),
    }
    cases.append(
        {
            "id": "budget_exhaustion_returns_partial",
            "description": "The same candidate omissions are used, but a one-call budget prevents the second scripted response from being requested.",
            "injection": "One-call limit with an incomplete candidate pool.",
            "passed": all(checks.values()),
            "checks": checks,
            "provider_requests": provider.requests,
            "metrics": metrics,
            "result": result.model_dump(),
        }
    )

    wrong_grid = ["DOG", "ORE", "GET"]
    wrong = {
        entry.id: [
            Candidate(answer="".join(wrong_grid[row][col] for row, col in entry.cells), score=0.99)
        ]
        for entry in parse_entries(puzzle)
    }
    provider = ScriptedProvider([wrong])
    result = CrosswordAgent(provider, model=MODEL).solve(puzzle, options)
    metrics = evaluate_result(puzzle, reference, result)
    checks = {
        "controller_reports_only_consistency": result.status == "complete_consistent",
        "grid_is_fully_filled": metrics["completion"] == 1,
        "grid_has_no_hard_constraint_violations": metrics["constraint_violation_count"] == 0,
        "reference_evaluation_detects_incorrect_letters": metrics["letter_accuracy"] < 1,
        "reference_evaluation_rejects_exact_correctness": not metrics["exact_puzzle"],
    }
    cases.append(
        {
            "id": "consistent_wrong_fill_detected",
            "description": "The fake provider returns a completely crossing-compatible but clue-inappropriate fill. The independent answer key exposes the error.",
            "injection": "A wrong full grid converted to internally consistent candidates.",
            "passed": all(checks.values()),
            "checks": checks,
            "provider_requests": provider.requests,
            "metrics": metrics,
            "result": result.model_dump(),
        }
    )

    return {
        "kind": "deterministic_mechanism_checks",
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": MODEL,
        "actual_network_calls": 0,
        "fixture": puzzle.id,
        "limitations": [
            "These scripted failure injections are not measurements of LLM performance.",
            "The fake provider intentionally reads answers through the harness and supplies predefined candidates.",
            "Usage.model_calls counts simulated provider invocations; tokens and dollar costs are not measured here.",
            "Controller events and search outputs are produced by the actual implementation during this run.",
        ],
        "all_cases_passed": all(case["passed"] for case in cases),
        "case_count": len(cases),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts" / "evaluation" / "robustness.json"
    )
    args = parser.parse_args()
    report = run_checks()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for case in report["cases"]:
        print(f"{'PASS' if case['passed'] else 'FAIL'} {case['id']}")
    print(f"Saved {args.output}. Scripted checks only; zero network calls.")
    return 0 if report["all_cases_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
