import json
from pathlib import Path

import pytest

from crossword_agent.domain import parse_entries, render_grid, validate_assignments
from crossword_agent.evaluation import (
    aggregate_metrics,
    evaluate_result,
    first_choice_result,
    run_evaluation,
    validate_reference,
)
from crossword_agent.models import Candidate, Puzzle, SolveOptions, SolveResult, Usage
from crossword_agent.providers.base import GenerationBatch, ProviderError

DATA = Path(__file__).resolve().parents[1] / "data"
MANIFEST = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def load_fixture(ident="dev-mixed-3"):
    puzzle = Puzzle.model_validate_json(
        (DATA / "puzzles" / f"{ident}.json").read_text(encoding="utf-8")
    )
    reference = json.loads((DATA / "solutions" / f"{ident}.json").read_text(encoding="utf-8"))[
        "grid"
    ]
    answers = {
        entry.id: "".join(reference[r][c] for r, c in entry.cells)
        for entry in parse_entries(puzzle)
    }
    return puzzle, reference, answers


def result_for(puzzle, assignments, grid=None):
    rendered = grid if grid is not None else render_grid(puzzle, assignments)
    return SolveResult(
        puzzle_id=puzzle.id,
        status="complete_consistent",  # Intentionally untrusted by the evaluator.
        grid=rendered,
        assignments=assignments,
        unresolved_entries=[],
        constraint_violations=[],
        filled_cells=999,  # The evaluator must calculate, not copy, this number.
        total_cells=999,
        elapsed_seconds=2,
        rounds=1,
        search_nodes=3,
        stop_reason="test",
        usage=Usage(model_calls=1, prompt_tokens=10, completion_tokens=20, total_tokens=30),
        candidates={key: [Candidate(answer=answer)] for key, answer in assignments.items()},
    )


@pytest.mark.parametrize("item", MANIFEST["puzzles"], ids=lambda item: item["id"])
def test_every_fixture_has_valid_geometry_and_consistent_reference(item):
    puzzle, reference, answers = load_fixture(item["id"])
    validate_reference(puzzle, reference)
    assert validate_assignments(puzzle, answers) == []
    assert render_grid(puzzle, answers) == reference
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, answers))
    assert metrics["letter_accuracy"] == metrics["answer_accuracy"] == 1
    assert metrics["exact_puzzle"]
    # The provider-visible input is a strict Puzzle with no key fields.
    assert "solution" not in puzzle.model_dump()


def test_blanks_count_as_wrong_and_reported_completion_is_not_trusted():
    puzzle, reference, _ = load_fixture()
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, {"1A": "CAT"}))
    assert metrics["total_cells"] == 9
    assert metrics["correct_cells"] == 3
    assert metrics["letter_accuracy"] == pytest.approx(1 / 3)
    assert metrics["answer_accuracy"] == pytest.approx(1 / 6)
    assert metrics["completion"] == pytest.approx(1 / 3)
    assert not metrics["exact_puzzle"]
    assert not metrics["complete_consistent"]


def test_conflicting_assignments_cannot_get_credit_from_a_correct_displayed_grid():
    puzzle, reference, answers = load_fixture()
    answers["1D"] = "BAR"  # First cell conflicts with CAT even if display says CAT.
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, answers, grid=reference))
    assert metrics["correct_cells"] == 8
    assert metrics["correct_entries"] == 4
    assert metrics["constraint_violation_count"] > 0
    assert not metrics["exact_puzzle"]


def test_complete_crossing_consistent_wrong_answers_are_not_correct():
    puzzle, reference, _ = load_fixture()
    wrong_grid = ["DOG", "ORE", "GET"]
    wrong = {
        entry.id: "".join(wrong_grid[r][c] for r, c in entry.cells)
        for entry in parse_entries(puzzle)
    }
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, wrong))
    assert metrics["complete_consistent"]
    assert metrics["completion"] == 1
    assert metrics["constraint_violation_count"] == 0
    assert metrics["letter_accuracy"] < 1
    assert not metrics["exact_puzzle"]


@pytest.mark.parametrize(
    "bad",
    [
        ["CAT"],
        ["CAT", "AP", "RYE"],
        ["CAT", "A.E", "RYE"],
        ["CAT", "APE", "R#E"],
        ["cat", "APE", "RYE"],
    ],
)
def test_malformed_reference_is_rejected(bad):
    puzzle, _, _ = load_fixture()
    with pytest.raises(ValueError):
        evaluate_result(puzzle, bad, result_for(puzzle, {}))


def test_reference_cannot_change_blocks_or_supplied_letters():
    blocked, reference, _ = load_fixture("test-captain-5x7")
    with pytest.raises(ValueError, match="black squares"):
        validate_reference(blocked, ["AAAWWWW", *reference[1:]])
    fixed, reference, _ = load_fixture("test-fixed-4")
    with pytest.raises(ValueError, match="supplied letter"):
        validate_reference(fixed, ["NOSE", *reference[1:]])


def test_malformed_result_grid_is_scored_as_a_failure_without_crashing():
    puzzle, reference, _ = load_fixture()
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, {}, grid=["CAT"]))
    assert metrics["letter_accuracy"] == pytest.approx(1 / 3)
    assert metrics["constraint_violation_count"] > 0
    assert not metrics["exact_puzzle"]


def test_supplied_letters_are_reported_separately_from_newly_solved_cells():
    puzzle, reference, _ = load_fixture("test-fixed-4")
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, {}))
    assert metrics["fixed_cells"] == 3
    assert metrics["letter_accuracy"] == 3 / 16
    assert metrics["unknown_letter_accuracy"] == 0


def test_candidate_recall_uses_all_candidates_and_all_clues():
    puzzle, reference, answers = load_fixture()
    result = result_for(puzzle, {})
    result.candidates = {"1A": [Candidate(answer="DOG"), Candidate(answer=answers["1A"])]}
    metrics = evaluate_result(puzzle, reference, result)
    assert metrics["candidate_hits"] == 1
    assert metrics["candidate_recall"] == pytest.approx(1 / 6)


def test_first_choice_exposes_conflicts_instead_of_overwriting_letters():
    puzzle, reference, answers = load_fixture()
    candidates = {key: [Candidate(answer=answer)] for key, answer in answers.items()}
    candidates["1D"] = [Candidate(answer="BAR", score=0.9), Candidate(answer="CAR", score=0.1)]
    result = first_choice_result(puzzle, candidates)
    assert result.grid[0][0] == "."
    assert result.constraint_violations
    assert not evaluate_result(puzzle, reference, result)["exact_puzzle"]


def test_aggregation_uses_micro_accuracy_and_keeps_unknown_price_unknown():
    puzzle, reference, answers = load_fixture()
    first = evaluate_result(puzzle, reference, result_for(puzzle, answers))
    bigger, bigger_reference, _ = load_fixture("test-ball-4")
    second = evaluate_result(bigger, bigger_reference, result_for(bigger, {}))
    summary = aggregate_metrics([first, second])
    assert summary["letter_accuracy"] == 9 / 25
    assert summary["answer_accuracy"] == 6 / 14
    assert summary["exact_puzzle_accuracy"] == 0.5
    assert summary["usage"]["total_tokens"] == 60
    assert summary["usage"]["estimated_cost_usd"] is None
    with pytest.raises(ValueError):
        aggregate_metrics([])


def one_fixture_dataset(tmp_path):
    puzzle, reference, answers = load_fixture()
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "puzzle.json").write_text(puzzle.model_dump_json(), encoding="utf-8")
    (dataset / "key.json").write_text(
        json.dumps({"puzzle_id": puzzle.id, "grid": reference}), encoding="utf-8"
    )
    (dataset / "manifest.json").write_text(
        json.dumps(
            {
                "name": "test-only",
                "limitations": ["test-only"],
                "puzzles": [
                    {
                        "id": puzzle.id,
                        "split": "test",
                        "input": "puzzle.json",
                        "solution": "key.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return dataset, answers


def test_runner_reuses_one_real_generation_for_three_paired_arms(tmp_path):
    dataset, answers = one_fixture_dataset(tmp_path)

    class RecordedProvider:
        calls = 0

        def generate(self, entries, *, patterns, previous, limit, timeout):
            self.calls += 1
            assert all(pattern == "..." for pattern in patterns.values())
            candidates = {
                entry.id: [Candidate(answer=answers[entry.id], score=0.8)] for entry in entries
            }
            candidates["1A"].insert(0, Candidate(answer="DOG", score=0.9))
            return GenerationBatch(
                candidates, Usage(model_calls=1, total_tokens=42, estimated_cost_usd=0.01)
            )

    provider = RecordedProvider()
    output = tmp_path / "output"
    report = run_evaluation(provider, "fake-test-model", data_dir=dataset, output_dir=output)
    assert provider.calls == 1
    assert report["summary"]["baseline_first_choice"]["letter_accuracy"] < 1
    assert report["summary"]["baseline_search"]["letter_accuracy"] == 1
    assert report["summary"]["agent"]["letter_accuracy"] == 1
    for metrics in report["summary"].values():
        assert metrics["usage"]["model_calls"] == 1
        assert metrics["usage"]["estimated_cost_usd"] == 0.01
    assert json.loads((output / "test.json").read_text(encoding="utf-8"))["available"]


def test_runner_keeps_provider_failures_in_denominator(tmp_path):
    dataset, _ = one_fixture_dataset(tmp_path)

    class FailedProvider:
        def generate(self, *args, **kwargs):
            raise ProviderError("Test provider unavailable.")

    report = run_evaluation(
        FailedProvider(),
        "fake-test-model",
        data_dir=dataset,
        output_dir=tmp_path / "output",
        options=SolveOptions(max_calls=1),
    )
    assert report["dataset"]["puzzle_count"] == 1
    assert report["puzzles"][0]["initial_generation_errors"]
    for metrics in report["summary"].values():
        assert metrics["letter_accuracy"] == 0
        assert metrics["usage"]["model_calls"] == 1


def numeric_fixture():
    puzzle = Puzzle(
        id="numeric-metric-check",
        answer_type="digits",
        grid=["..", ".."],
        clues={
            "across": {"1": "Ten", "3": "Two, padded to two cells"},
            "down": {"1": "Ten", "2": "Two, padded to two cells"},
        },
    )
    reference = ["10", "02"]
    answers = {
        entry.id: "".join(reference[r][c] for r, c in entry.cells)
        for entry in parse_entries(puzzle)
    }
    return puzzle, reference, answers


def test_numeric_zero_cells_count_as_filled_and_correct():
    puzzle, reference, answers = numeric_fixture()
    candidates = {ident: [Candidate(answer=answer)] for ident, answer in answers.items()}
    result = first_choice_result(puzzle, candidates)
    metrics = evaluate_result(puzzle, reference, result)
    assert result.filled_cells == 4
    assert metrics["filled_cells"] == metrics["correct_cells"] == 4
    assert metrics["cell_accuracy"] == metrics["letter_accuracy"] == 1
    assert metrics["unknown_cell_accuracy"] == 1
    assert metrics["candidate_recall"] == 1
    assert metrics["exact_puzzle"]
    summary = aggregate_metrics([metrics])
    assert summary["cell_accuracy"] == summary["letter_accuracy"] == 1


@pytest.mark.parametrize("invalid", ["-10", "1.0", "+10", "1 0"])
def test_digit_candidate_punctuation_is_not_removed_for_recall_or_baselines(invalid):
    puzzle, reference, _ = numeric_fixture()
    result = first_choice_result(puzzle, {"1A": [Candidate(answer=invalid)]})
    assert result.assignments["1A"] == invalid
    assert result.grid == ["..", ".."]
    assert result.filled_cells == 0
    metrics = evaluate_result(puzzle, reference, result)
    assert metrics["candidate_recall"] == 0
    assert metrics["cell_accuracy"] == 0
    assert metrics["constraint_violation_count"] > 0


def test_numeric_fixed_zero_and_invalid_key_are_handled_without_truthiness_errors():
    puzzle, reference, _ = numeric_fixture()
    puzzle = puzzle.model_copy(update={"grid": [".0", ".."]})
    metrics = evaluate_result(puzzle, reference, result_for(puzzle, {}))
    assert metrics["fixed_cells"] == metrics["correct_cells"] == metrics["filled_cells"] == 1
    assert metrics["cell_accuracy"] == 0.25
    assert metrics["unknown_cell_accuracy"] == 0
    with pytest.raises(ValueError, match="digit"):
        validate_reference(puzzle, ["A0", "02"])
