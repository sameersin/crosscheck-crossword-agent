from copy import deepcopy

from crossword_agent.agent import CrosswordAgent
from crossword_agent.domain import validate_assignments
from crossword_agent.models import Candidate, Clues, Puzzle, SolveOptions, Usage
from crossword_agent.providers.base import GenerationBatch


class NoModelCalls:
    def generate(self, *args, **kwargs):
        raise AssertionError("Exact arithmetic must not call the language model.")


class RecordingProvider:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def generate(self, entries, **kwargs):
        self.calls.append([entry.id for entry in entries])
        return GenerationBatch(
            {entry.id: [Candidate(answer=self.answers[entry.id])] for entry in entries},
            Usage(model_calls=1),
        )


def numeric_puzzle(*, grid=None, top="6 + 6", left="10 + 3"):
    return Puzzle(
        answer_type="digits",
        grid=grid or ["..", ".."],
        clues=Clues(across={"1": top, "3": "30 + 4"}, down={"1": left, "2": "20 + 4"}),
    )


def test_exact_arithmetic_bypasses_provider_and_reports_no_model_usage():
    result = CrosswordAgent(NoModelCalls()).solve(numeric_puzzle())
    assert result.status == "complete_consistent"
    assert result.grid == ["12", "34"]
    assert result.usage.model_calls == 0
    assert result.rounds == 1
    assert any(event.kind == "arithmetic" for event in result.events)
    assert not any(event.kind == "generating" for event in result.events)


def test_exact_domains_replace_even_highest_scoring_initial_guesses():
    guesses = {key: [Candidate(answer="00", score=1)] for key in ("1A", "1D", "2D", "3A")}
    original = deepcopy(guesses)
    result = CrosswordAgent(NoModelCalls()).solve(numeric_puzzle(), initial_candidates=guesses)
    assert result.status == "complete_consistent"
    assert result.grid == ["12", "34"]
    assert all(
        candidate.answer != "00" for values in result.candidates.values() for candidate in values
    )
    assert guesses == original


def test_inconsistent_exact_crossings_are_reported_in_first_round():
    puzzle = numeric_puzzle(left="10 + 5")
    result = CrosswordAgent(NoModelCalls()).solve(puzzle, SolveOptions(max_rounds=1))
    assert result.status == "partial"
    assert result.stop_reason == "inconsistent_arithmetic_input"
    assert result.usage.model_calls == 0
    assert result.rounds == 1
    assert result.assignments
    assert not validate_assignments(puzzle, result.assignments)
    warnings = [event for event in result.events if event.kind == "input_warning"]
    assert any("crossing conflict" in issue for issue in warnings[0].data["issues"])


def test_given_digit_conflict_preserves_given_and_never_asks_model_to_change_math():
    puzzle = numeric_puzzle(grid=["9.", ".."])
    result = CrosswordAgent(NoModelCalls()).solve(puzzle)
    assert result.status == "partial"
    assert result.stop_reason == "inconsistent_arithmetic_input"
    assert result.grid[0][0] == "9"
    assert not validate_assignments(puzzle, result.assignments)


def test_wrong_length_exact_answer_is_an_input_problem_not_a_generation_target():
    puzzle = numeric_puzzle(top="1 + 1")
    guesses = {"1A": [Candidate(answer="12", score=1)]}
    result = CrosswordAgent(NoModelCalls()).solve(puzzle, initial_candidates=guesses)
    assert result.status == "partial"
    assert result.stop_reason == "inconsistent_arithmetic_input"
    assert "1A" not in result.assignments
    assert result.candidates["1A"] == []
    assert any(
        "does not fit 2 cells" in issue
        for event in result.events
        if event.kind == "input_warning"
        for issue in event.data["issues"]
    )


def test_mixed_digit_clues_generate_only_unsupported_entries():
    provider = RecordingProvider({"1A": "12"})
    result = CrosswordAgent(provider).solve(numeric_puzzle(top="A dozen"))
    assert result.status == "complete_consistent"
    assert result.grid == ["12", "34"]
    assert provider.calls == [["1A"]]
    assert result.usage.model_calls == 1


def test_conflicting_exact_subset_stops_before_spending_calls_on_other_clues():
    puzzle = numeric_puzzle(top="A dozen", left="10 + 5")
    result = CrosswordAgent(NoModelCalls()).solve(puzzle)
    assert result.stop_reason == "inconsistent_arithmetic_input"
    assert result.usage.model_calls == 0


def test_letter_puzzle_does_not_treat_math_looking_clue_as_digit_answer():
    puzzle = Puzzle(
        grid=["..", ".."],
        clues=Clues(across={"1": "22-9", "3": "Bottom"}, down={"1": "Left", "2": "Right"}),
    )
    provider = RecordingProvider({"1A": "AT", "1D": "AS", "2D": "TO", "3A": "SO"})
    result = CrosswordAgent(provider).solve(puzzle)
    assert result.status == "complete_consistent"
    assert result.grid == ["AT", "SO"]
    assert result.usage.model_calls == 1
    assert len(provider.calls[0]) == 4


def test_exact_arithmetic_retains_existing_usage_without_spending_another_call():
    usage = Usage(model_calls=1, total_tokens=100)
    result = CrosswordAgent(NoModelCalls()).solve(
        numeric_puzzle(), SolveOptions(max_calls=1), initial_usage=usage
    )
    assert result.status == "complete_consistent"
    assert result.usage == usage
