import pytest

from crossword_agent.arithmetic import arithmetic_candidates
from crossword_agent.domain import Entry, parse_entries, render_grid, validate_assignments
from crossword_agent.models import Clues, Puzzle
from crossword_agent.search import solve_constraints


def entry(clue, length, answer_type="digits"):
    return Entry(
        "1A", 1, "across", 0, 0, length, tuple((0, c) for c in range(length)), clue, answer_type
    )


@pytest.mark.parametrize(
    "clue, expected",
    [
        ("22 − 9", "13"),
        ("710 + 543", "1253"),
        ("18 – 6", "12"),
        ("18 — 6", "12"),
        ("6 × 7", "42"),
        ("84 ÷ 2", "42"),
        ("6 * 7", "42"),
        ("(9 + 5) * 3", "42"),
        ("6 + 3 * 12", "42"),
        ("(1 / 3) * 126", "42"),
        ("-5 + 17", "12"),
        ("+12", "12"),
        ("10 - 10", "0"),
    ],
)
def test_exact_integer_arithmetic(clue, expected):
    candidate = arithmetic_candidates([entry(clue, len(expected))])["1A"][0]
    assert candidate.answer == expected
    assert candidate.score == 1


@pytest.mark.parametrize(
    "clue",
    [
        "2 - 14",
        "7 / 2",
        "10 / 0",
        "12.0",
        "True + 12",
        "1e2",
        "0x12",
        "1_200",
        "12 ** 9999999999",
        "42 // 2",
        "42 % 20",
        "abs(-12)",
        "__import__('os').system('echo unsafe')",
        "(12).__class__",
        "[12][0]",
        "12 if 1 else 13",
        "a + 12",
        "Twelve",
        "12 x 2",
        "１２",
        "1; 12",
        "(12",
        "",
    ],
)
def test_unsupported_or_unsafe_expressions_are_not_candidates(clue):
    assert arithmetic_candidates([entry(clue, 2)]) == {}


def test_size_complexity_and_intermediate_limits():
    clues = [
        "1" * 257,
        "+".join(["1"] * 100),
        "-" * 30 + "12",
        "1" * 26,
        " * ".join(["9" * 25] * 3),
    ]
    for clue in clues:
        assert arithmetic_candidates([entry(clue, 25)]) == {}


def test_does_not_pad_answers_or_run_math_on_letter_clues():
    assert arithmetic_candidates([entry("6 + 6", 3)]) == {}
    assert arithmetic_candidates([entry("6 + 6", 2, "letters")]) == {}


def test_mixed_supported_and_unsupported_clues_preserve_only_valid_ids():
    entries = [
        entry("22 - 9", 2),
        Entry("2D", 2, "down", 0, 0, 2, ((0, 0), (1, 0)), "unknown", "digits"),
    ]
    assert set(arithmetic_candidates(entries)) == {"1A"}


# Manually transcribed and visually checked against math-crossword-1-1200.png.
# The reference grid was computed independently from its printed arithmetic.
MATH_IMAGE_PUZZLE = {
    "id": "user-math-crossword-1",
    "title": "Math Crossword #1",
    "author": "puzzles-to-print.com",
    "answer_type": "digits",
    "grid": [
        "#..##...##",
        "....#....#",
        "..#....#..",
        "#..#..#...",
        "##..##....",
        "....##..##",
        "...#..#..#",
        "..#....#..",
        "#....#....",
        "##...##..#",
    ],
    "clues": {
        "across": {
            "1": "22 − 9",
            "3": "159 − 13",
            "6": "465 + 750",
            "8": "2329 + 3294",
            "10": "25 − 10",
            "11": "18833 − 9266",
            "13": "20 − 7",
            "15": "15 + 16",
            "17": "120 − 24",
            "18": "952 − 344",
            "19": "99 − 40",
            "21": "445 + 8975",
            "22": "1496 + 930",
            "24": "124 − 46",
            "25": "1290 − 300",
            "26": "98 − 44",
            "28": "11 + 5",
            "30": "27 + 40",
            "31": "9284 − 2589",
            "33": "44 − 10",
            "35": "3292 − 768",
            "37": "9 + 1616",
            "39": "858 − 356",
            "40": "1 + 10",
        },
        "down": {
            "1": "710 + 543",
            "2": "46 − 15",
            "3": "297 + 1269",
            "4": "235 + 232",
            "5": "83 − 21",
            "6": "15 − 4",
            "7": "29 + 30",
            "9": "5457 − 2355",
            "12": "24 + 35",
            "14": "560 − 180",
            "16": "381 + 1139",
            "18": "12346 − 5865",
            "20": "27 + 69",
            "21": "183 − 86",
            "22": "338 − 42",
            "23": "280 + 4692",
            "26": "10786 − 5144",
            "27": "27 + 22",
            "29": "12200 − 5879",
            "31": "687 − 67",
            "32": "62 − 11",
            "34": "21 + 24",
            "36": "61 − 6",
            "38": "17 + 44",
        },
    },
}

MATH_IMAGE_REFERENCE_GRID = [
    "#13##146##",
    "1215#5623#",
    "15#9567#13",
    "#31#96#608",
    "##59##9420",
    "2426##78##",
    "990#54#16#",
    "67#6695#34",
    "#2524#1625",
    "##502##11#",
]


def test_actual_math_image_geometry_arithmetic_and_reference_agree():
    puzzle = Puzzle.model_validate(MATH_IMAGE_PUZZLE)
    entries = parse_entries(puzzle)
    assert len(entries) == 48
    assert sum(entry.direction == "across" for entry in entries) == 24
    candidates = arithmetic_candidates(entries)
    assert len(candidates) == 48
    for entry_ in entries:
        expected = "".join(MATH_IMAGE_REFERENCE_GRID[r][c] for r, c in entry_.cells)
        assert candidates[entry_.id][0].answer == expected
    result = solve_constraints(puzzle, candidates)
    assert result.complete
    assert not result.exhausted
    assert render_grid(puzzle, result.assignments) == MATH_IMAGE_REFERENCE_GRID
    assert validate_assignments(puzzle, result.assignments) == []


def test_numeric_fixed_digit_cannot_be_overwritten_by_arithmetic():
    puzzle = Puzzle(
        answer_type="digits",
        grid=["9.", ".."],
        clues=Clues(across={"1": "6+6", "3": "30+4"}, down={"1": "10+3", "2": "20+4"}),
    )
    result = solve_constraints(puzzle, arithmetic_candidates(parse_entries(puzzle)))
    assert not result.complete
    assert render_grid(puzzle, result.assignments)[0][0] == "9"
    assert not validate_assignments(puzzle, result.assignments)
