import random
import time
from itertools import product

import pytest

from crossword_agent.domain import parse_entries, render_grid, validate_assignments
from crossword_agent.models import Candidate, Clues, Puzzle
from crossword_agent.search import solve_constraints


def square(grid=None):
    return Puzzle(
        grid=grid or ["..", ".."],
        clues=Clues(across={"1": "Top", "3": "Bottom"}, down={"1": "Left", "2": "Right"}),
    )


def choices(*answers):
    return [
        Candidate(answer=answer, score=1 - index / (len(answers) + 1))
        for index, answer in enumerate(answers)
    ]


def solved_candidates():
    return {"1A": choices("AT"), "3A": choices("SO"), "1D": choices("AS"), "2D": choices("TO")}


def test_solves_consistent_grid():
    puzzle = square()
    result = solve_constraints(puzzle, solved_candidates())
    assert result.complete
    assert not result.exhausted
    assert result.blocked_entries == []
    assert result.nodes == 4
    assert render_grid(puzzle, result.assignments) == ["AT", "SO"]


def test_fixed_letters_eliminate_wrong_high_scored_candidates():
    puzzle = square(["A.", ".."])
    candidates = solved_candidates()
    candidates["1A"] = choices("NO", "AT")
    candidates["1D"] = choices("ON", "AS")
    result = solve_constraints(puzzle, candidates)
    assert result.complete
    assert result.assignments["1A"] == "AT"
    assert validate_assignments(puzzle, result.assignments) == []
    assert puzzle.grid == ["A.", ".."]


def test_missing_candidate_pool_returns_useful_partial():
    candidates = solved_candidates()
    del candidates["1A"]
    result = solve_constraints(square(), candidates)
    assert not result.complete
    assert not result.exhausted
    assert result.blocked_entries == ["1A"]
    assert len(result.assignments) == 3


def test_inconsistent_candidates_never_return_crossing_conflicts():
    puzzle = square()
    candidates = {
        "1A": choices("AA"),
        "3A": choices("AA"),
        "1D": choices("BB"),
        "2D": choices("BB"),
    }
    result = solve_constraints(puzzle, candidates)
    assert not result.complete
    assert not result.exhausted
    assert len(result.assignments) == 2
    assert validate_assignments(puzzle, result.assignments) == []


def test_partial_search_can_skip_an_early_choice_to_recover_more_entries():
    # 1A conflicts with both down answers. Omitting it retains three entries.
    candidates = {
        "1A": choices("ZZ"),
        "3A": choices("SO"),
        "1D": choices("AS"),
        "2D": choices("TO"),
    }
    result = solve_constraints(square(), candidates)
    assert len(result.assignments) == 3
    assert result.blocked_entries == ["1A"]
    assert not result.exhausted


def test_invalid_and_duplicate_answers_are_filtered_without_mutation():
    candidates = solved_candidates()
    candidates["1A"] = [
        Candidate(answer="a t", score=0.2),
        Candidate(answer="AT", score=0.9),
        Candidate(answer="TOO", score=1),
        Candidate(answer="A2", score=1),
    ]
    result = solve_constraints(square(), candidates)
    assert result.complete
    assert result.assignments["1A"] == "AT"
    assert result.score == pytest.approx(3.9)
    assert len(candidates["1A"]) == 4


def test_node_budget_is_bounded_and_returns_consistent_incumbent():
    puzzle = square()
    result = solve_constraints(puzzle, solved_candidates(), max_nodes=2)
    assert not result.complete
    assert result.exhausted
    assert result.nodes == 2
    assert len(result.assignments) == 2
    assert validate_assignments(puzzle, result.assignments) == []


def test_zero_budget_and_expired_deadline_are_honest():
    for kwargs in ({"max_nodes": 0}, {"deadline": time.monotonic() - 1}):
        result = solve_constraints(square(), solved_candidates(), **kwargs)
        assert result.exhausted
        assert result.assignments == {}
        assert result.nodes == 0


def test_empty_pools_are_infeasible_not_a_budget_exhaustion():
    result = solve_constraints(square(), {})
    assert not result.complete
    assert not result.exhausted
    assert len(result.blocked_entries) == 4


def test_negative_budget_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        solve_constraints(square(), {}, max_nodes=-1)


def test_five_by_five_word_square_with_distractors():
    words = ["HEART", "EMBER", "ABUSE", "RESIN", "TREND"]
    puzzle = Puzzle(
        grid=["....."] * 5,
        clues=Clues(
            across={str(n): "Across" for n in (1, 6, 7, 8, 9)},
            down={str(n): "Down" for n in range(1, 6)},
        ),
    )
    candidates = {}
    for entry in parse_entries(puzzle):
        answer = words[entry.row if entry.direction == "across" else entry.col]
        candidates[entry.id] = choices("ZZZZZ" if entry.direction == "across" else "XXXXX", answer)
    result = solve_constraints(puzzle, candidates, max_nodes=500)
    assert result.complete
    assert not result.exhausted
    assert render_grid(puzzle, result.assignments) == words


def test_backtracks_without_spending_budget_on_early_skip_branches():
    puzzle = Puzzle(
        grid=["..."] * 3,
        clues=Clues(
            across={"1": "Top", "4": "Middle", "5": "Bottom"},
            down={"1": "Left", "2": "Middle", "3": "Right"},
        ),
    )
    pools = {
        "1A": ["ABA", "BCC", "CCB", "CAA", "BAA"],
        "1D": ["CCA", "ACC", "BBC", "AAB", "CBC"],
        "2D": ["AAC", "BBA", "CCB", "CBA", "CBB"],
        "3D": ["ACC", "BCB", "ABB", "AAB", "CBB"],
        "4A": ["ACC", "CCC", "CAB", "ABC", "ACB"],
        "5A": ["ACB", "ACA", "CAC", "BAA", "BBC"],
    }
    result = solve_constraints(
        puzzle, {key: choices(*values) for key, values in pools.items()}, max_nodes=20
    )
    assert result.complete
    assert not result.exhausted
    assert render_grid(puzzle, result.assignments) == ["CAA", "CAB", "ACB"]
    assert validate_assignments(puzzle, result.assignments) == []


def test_regular_blocked_grid_with_distractors():
    grid = ["AB#CD", "EFGHI", "#JKL#", "MNOPQ", "RS#TU"]
    puzzle = Puzzle(
        grid=["..#..", ".....", "#...#", ".....", "..#.."],
        clues=Clues(
            across={str(n): "Across" for n in (1, 3, 5, 7, 8, 10, 11)},
            down={str(n): "Down" for n in (1, 2, 3, 4, 6, 8, 9)},
        ),
    )
    candidates = {
        entry.id: choices(
            ("Z" if entry.direction == "across" else "Y") * entry.length,
            "".join(grid[r][c] for r, c in entry.cells),
        )
        for entry in parse_entries(puzzle)
    }
    result = solve_constraints(puzzle, candidates, max_nodes=1000)
    assert result.complete
    assert render_grid(puzzle, result.assignments) == grid


def test_search_matches_exhaustive_maximum_coverage_on_small_pools():
    # An independent exhaustive oracle checks search/skip/pruning interactions,
    # including arc-consistent cycles that have no complete solution.
    rng = random.Random(811)
    puzzle = square()
    ids = [entry.id for entry in parse_entries(puzzle)]
    vocabulary = ["AA", "AB", "BA", "BB"]
    for _ in range(45):
        candidates = {key: choices(*rng.sample(vocabulary, rng.randint(0, 3))) for key in ids}
        optimum = 0
        for combination in product(
            *[[None, *[candidate.answer for candidate in candidates[key]]] for key in ids]
        ):
            assignment = {
                key: answer
                for key, answer in zip(ids, combination, strict=True)
                if answer is not None
            }
            if len(assignment) > optimum and not validate_assignments(puzzle, assignment):
                optimum = len(assignment)
        result = solve_constraints(puzzle, candidates, max_nodes=10000)
        assert not result.exhausted
        assert len(result.assignments) == optimum
        assert validate_assignments(puzzle, result.assignments) == []


def test_candidate_search_is_deterministic_and_reconsiders_guesses():
    candidates = solved_candidates()
    first = solve_constraints(square(), candidates)
    second = solve_constraints(square(), candidates)
    assert first == second
    changed = {"1A": choices("IN"), "3A": choices("TO"), "1D": choices("IT"), "2D": choices("NO")}
    assert render_grid(square(), solve_constraints(square(), changed).assignments) == ["IN", "TO"]
