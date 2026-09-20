import pytest

from crossword_agent.domain import (
    PuzzleValidationError,
    entry_pattern,
    normalize_answer,
    parse_entries,
    render_grid,
    validate_assignments,
)
from crossword_agent.models import Clues, Puzzle


def square(grid=None):
    return Puzzle(
        grid=grid or ["..", ".."],
        clues=Clues(across={"1": "Top", "3": "Bottom"}, down={"1": "Left", "2": "Right"}),
    )


def test_row_major_numbering_and_cells():
    entries = parse_entries(square())
    assert [entry.id for entry in entries] == ["1A", "1D", "2D", "3A"]
    assert entries[2].direction == "down"
    assert entries[2].cells == ((0, 1), (1, 1))
    assert entries[3].number == 3
    assert entries[3].length == 2


def test_rectangular_grid_and_single_direction_entries():
    puzzle = Puzzle(grid=["...", "###"], clues=Clues(across={"1": "Only entry"}, down={}))
    assert [entry.id for entry in parse_entries(puzzle)] == ["1A"]
    assert render_grid(puzzle, {"1A": "CAT"}) == ["CAT", "###"]


@pytest.mark.parametrize(
    "clues, match",
    [
        (Clues(across={"1": "Top"}, down={"1": "Left", "2": "Right"}), "Missing across clues: 3"),
        (
            Clues(
                across={"1": "Top", "2": "Wrong", "3": "Bottom"}, down={"1": "Left", "2": "Right"}
            ),
            "Unexpected across clues: 2",
        ),
        (Clues(across={"1": "Top", "3": "Bottom"}, down={"1": "Left"}), "Missing down clues: 2"),
    ],
)
def test_clue_map_must_exactly_match_numbering(clues, match):
    with pytest.raises(PuzzleValidationError, match=match):
        parse_entries(Puzzle(grid=["..", ".."], clues=clues))


def test_rejects_isolated_cell():
    puzzle = Puzzle(grid=[".#", "#."], clues=Clues(across={}, down={}))
    with pytest.raises(PuzzleValidationError, match="isolated cells"):
        parse_entries(puzzle)


def test_blocked_grid_has_expected_numbering():
    puzzle = Puzzle(
        grid=["..#..", ".....", "#...#", ".....", "..#.."],
        clues=Clues(
            across={str(n): "Across" for n in (1, 3, 5, 7, 8, 10, 11)},
            down={str(n): "Down" for n in (1, 2, 3, 4, 6, 8, 9)},
        ),
    )
    entries = {entry.id: entry for entry in parse_entries(puzzle)}
    assert entries["6D"].cells == ((1, 2), (2, 2), (3, 2))
    assert entries["8A"].length == 5
    assert entries["11A"].cells == ((4, 3), (4, 4))


def test_normalization_allows_typographic_answers_but_keeps_invalid_symbols():
    assert normalize_answer("  café au-lait! ") == "CAFEAULAIT"
    assert normalize_answer("O’ER") == "OER"
    assert normalize_answer("B2B") == "B2B"
    assert normalize_answer("A+B") == "A+B"


def test_render_does_not_mutate_puzzle_and_preserves_fixed_letters():
    puzzle = square(["A.", ".."])
    assert render_grid(puzzle, {"1A": "at", "1D": "as"}) == ["AT", "S."]
    assert puzzle.grid == ["A.", ".."]
    assert validate_assignments(puzzle, {"1A": "at", "1D": "as"}) == []


@pytest.mark.parametrize(
    "assignments, match",
    [
        ({"10A": "AT"}, "Unknown entry"),
        ({"1A": "CAT"}, "expected 2 letters"),
        ({"1A": "B2"}, "only A-Z"),
        ({"1A": "NO"}, "fixed letter A"),
        ({"1A": "AT", "2D": "AS"}, "crossing conflict"),
    ],
)
def test_invalid_assignments_are_reported_and_not_rendered(assignments, match):
    puzzle = square(["A.", ".."])
    assert any(match in message for message in validate_assignments(puzzle, assignments))
    with pytest.raises(PuzzleValidationError, match=match):
        render_grid(puzzle, assignments)


def test_patterns_use_fixed_and_crossing_letters():
    puzzle = square(["A.", ".."])
    entries = {entry.id: entry for entry in parse_entries(puzzle)}
    assert entry_pattern(puzzle, entries["1A"]) == "A."
    assert entry_pattern(puzzle, entries["3A"], {"1D": "AS", "2D": "TO"}) == "SO"
    assert entry_pattern(puzzle, entries["1A"], {"1D": "NO"}) == "A."


def test_conflicting_tentative_letters_do_not_force_pattern():
    puzzle = square()
    entry = parse_entries(puzzle)[0]
    assert entry_pattern(puzzle, entry, {"1A": "AT", "1D": "NO"}) == ".T"


def test_invalid_tentative_answers_are_ignored():
    puzzle = square()
    entry = parse_entries(puzzle)[0]
    assert entry_pattern(puzzle, entry, {"1A": "X", "1D": "A2", "bogus": "AT"}) == ".."
