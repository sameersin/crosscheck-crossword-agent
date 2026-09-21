"""Crossword geometry and hard constraints, independent of any language model."""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from .models import AnswerType, Puzzle


class PuzzleValidationError(ValueError):
    """The grid, clues, or proposed assignments violate the puzzle contract."""


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    number: int
    direction: str
    row: int
    col: int
    length: int
    cells: tuple[tuple[int, int], ...]
    clue: str
    answer_type: AnswerType = "letters"


def normalize_answer(text: str, answer_type: AnswerType = "letters") -> str:
    """Normalize words; for digits, strip surrounding whitespace only.

    Numeric signs, punctuation, and internal spaces stay intact so a negative or
    decimal answer can never become a different valid number. For letter answers,
    remove spaces, punctuation, and accent marks; keep unsupported symbols/digits
    so subsequent validation rejects them.
    """
    if answer_type == "digits":
        return text.strip()
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text.upper())
        if not char.isspace()
        and not unicodedata.category(char).startswith("P")
        and not unicodedata.combining(char)
    )


def is_valid_answer(answer: str, answer_type: AnswerType = "letters") -> bool:
    alphabet = "0123456789" if answer_type == "digits" else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return bool(answer) and all(char in alphabet for char in answer)


def parse_entries(puzzle: Puzzle) -> list[Entry]:
    """Derive standard row-major numbering and require exactly the matching clues.

    Runs of two or more cells are entries. A single-cell run in one direction is
    allowed when the cell belongs to a longer entry in the other direction.
    """
    height, width = len(puzzle.grid), len(puzzle.grid[0])
    specifications: list[tuple[int, str, tuple[tuple[int, int], ...]]] = []
    covered: set[tuple[int, int]] = set()
    number = 0
    for row in range(height):
        for col in range(width):
            if puzzle.grid[row][col] == "#":
                continue
            starts = []
            if (col == 0 or puzzle.grid[row][col - 1] == "#") and (
                col + 1 < width and puzzle.grid[row][col + 1] != "#"
            ):
                starts.append(("across", 0, 1))
            if (row == 0 or puzzle.grid[row - 1][col] == "#") and (
                row + 1 < height and puzzle.grid[row + 1][col] != "#"
            ):
                starts.append(("down", 1, 0))
            if not starts:
                continue
            number += 1
            for direction, dr, dc in starts:
                cells = []
                r, c = row, col
                while r < height and c < width and puzzle.grid[r][c] != "#":
                    cells.append((r, c))
                    r, c = r + dr, c + dc
                specifications.append((number, direction, tuple(cells)))
                covered.update(cells)

    uncovered = [
        (r + 1, c + 1)
        for r, line in enumerate(puzzle.grid)
        for c, char in enumerate(line)
        if char != "#" and (r, c) not in covered
    ]
    if uncovered:
        raise PuzzleValidationError(
            f"Open cells must belong to an entry of at least two cells; "
            f"isolated cells (row, column): {uncovered}."
        )

    errors = []
    for direction in ("across", "down"):
        expected = {str(n) for n, d, _ in specifications if d == direction}
        supplied = set(getattr(puzzle.clues, direction))
        missing = sorted(expected - supplied, key=int)
        extra = sorted(supplied - expected, key=int)
        if missing:
            errors.append(f"Missing {direction} clues: {', '.join(missing)}")
        if extra:
            errors.append(f"Unexpected {direction} clues: {', '.join(extra)}")
    if errors:
        raise PuzzleValidationError("; ".join(errors) + ".")

    return [
        Entry(
            id=f"{number}{'A' if direction == 'across' else 'D'}",
            number=number,
            direction=direction,
            row=cells[0][0],
            col=cells[0][1],
            length=len(cells),
            cells=cells,
            clue=getattr(puzzle.clues, direction)[str(number)],
            answer_type=puzzle.answer_type,
        )
        for number, direction, cells in specifications
    ]


def validate_assignments(puzzle: Puzzle, assignments: dict[str, str]) -> list[str]:
    """Return hard-constraint violations; this does not establish clue correctness."""
    entries = {entry.id: entry for entry in parse_entries(puzzle)}
    violations: list[str] = []
    occupied: dict[tuple[int, int], tuple[str, str]] = {}
    for entry_id, raw_answer in assignments.items():
        entry = entries.get(entry_id)
        if entry is None:
            violations.append(f"Unknown entry: {entry_id}.")
            continue
        answer = normalize_answer(raw_answer, entry.answer_type)
        label = "digits" if entry.answer_type == "digits" else "letters"
        alphabet_label = "0-9 digits" if entry.answer_type == "digits" else "A-Z letters"
        if not is_valid_answer(answer, entry.answer_type):
            violations.append(f"{entry_id}: answer must contain only {alphabet_label}.")
            continue
        if len(answer) != entry.length:
            violations.append(
                f"{entry_id}: expected {entry.length} {label}, received {len(answer)}."
            )
            continue
        for (row, col), char in zip(entry.cells, answer, strict=True):
            fixed = puzzle.grid[row][col]
            if fixed != "." and fixed != char:
                violations.append(
                    f"{entry_id}: fixed {'digit' if entry.answer_type == 'digits' else 'letter'} {fixed} at row {row + 1}, "
                    f"column {col + 1} conflicts with {char}."
                )
            other = occupied.get((row, col))
            if other is not None and other[0] != char:
                violations.append(
                    f"{entry_id} and {other[1]}: crossing conflict at row {row + 1}, "
                    f"column {col + 1} ({char} versus {other[0]})."
                )
            else:
                occupied[(row, col)] = (char, entry_id)
    return violations


def render_grid(puzzle: Puzzle, assignments: dict[str, str]) -> list[str]:
    """Render a consistent assignment without changing blocks or supplied letters."""
    violations = validate_assignments(puzzle, assignments)
    if violations:
        raise PuzzleValidationError(" ".join(violations))
    grid = [list(row) for row in puzzle.grid]
    for entry in parse_entries(puzzle):
        if entry.id in assignments:
            answer = normalize_answer(assignments[entry.id], entry.answer_type)
            for (row, col), char in zip(entry.cells, answer, strict=True):
                grid[row][col] = char
    return ["".join(row) for row in grid]


def entry_pattern(puzzle: Puzzle, entry: Entry, assignments: dict[str, str] | None = None) -> str:
    """Combine supplied letters with tentative letters that agree at each cell.

    A malformed answer or one conflicting with supplied letters contributes
    nothing. Disagreement between tentative answers leaves an unknown cell.
    Callers revisiting an entry should omit its own previous assignment when
    they want only crossing-letter evidence.
    """
    tentative: dict[tuple[int, int], set[str]] = defaultdict(set)
    if assignments:
        for other in parse_entries(puzzle):
            if other.id not in assignments:
                continue
            answer = normalize_answer(assignments[other.id], other.answer_type)
            if len(answer) != other.length or not is_valid_answer(answer, other.answer_type):
                continue
            if any(
                puzzle.grid[row][col] not in (".", char)
                for (row, col), char in zip(other.cells, answer, strict=True)
            ):
                continue
            for cell, char in zip(other.cells, answer, strict=True):
                tentative[cell].add(char)
    pattern = []
    for row, col in entry.cells:
        fixed = puzzle.grid[row][col]
        letters = tentative[(row, col)]
        pattern.append(fixed if fixed != "." else next(iter(letters)) if len(letters) == 1 else ".")
    return "".join(pattern)
