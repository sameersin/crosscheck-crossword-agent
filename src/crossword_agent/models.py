"""Validated public data contracts. Reference solutions never enter these contracts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

AnswerType = Literal["letters", "digits"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Clues(StrictModel):
    across: dict[str, str]
    down: dict[str, str]

    @field_validator("across", "down")
    @classmethod
    def valid_clues(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 400:
            raise ValueError("Too many clues (maximum 400 per direction).")
        result = {}
        for key, clue in value.items():
            if not key.isdigit() or int(key) < 1 or str(int(key)) != key:
                raise ValueError("Clue numbers must be positive integers without leading zeros.")
            if not clue.strip() or len(clue) > 1000:
                raise ValueError("Each clue must contain between 1 and 1000 characters.")
            result[key] = clue.strip()
        return result


class Puzzle(StrictModel):
    id: str = Field(default="uploaded-puzzle", min_length=1, max_length=100)
    title: str = Field(default="Untitled crossword", max_length=200)
    author: str = Field(default="", max_length=200)
    answer_type: AnswerType = "letters"
    grid: list[str] = Field(min_length=2, max_length=25)
    clues: Clues

    @field_validator("grid")
    @classmethod
    def valid_grid(cls, value: list[str], info: ValidationInfo) -> list[str]:
        rows = [row.upper() for row in value]
        width = len(rows[0])
        if not 2 <= width <= 25 or any(len(row) != width for row in rows):
            raise ValueError("Grid must be rectangular, between 2 and 25 cells per side.")
        digits = info.data.get("answer_type") == "digits"
        alphabet = "0123456789" if digits else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if any(char not in ".#" + alphabet for row in rows for char in row):
            label = "0-9 for fixed digits" if digits else "A-Z for fixed letters"
            raise ValueError(f"Use '.' for empty cells, '#' for blocks, and {label}.")
        if all(char == "#" for row in rows for char in row):
            raise ValueError("Grid must contain at least one open cell.")
        return rows


class Candidate(StrictModel):
    answer: str = Field(min_length=1, max_length=100)
    score: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)


class SolveOptions(StrictModel):
    max_rounds: int = Field(default=4, ge=1, le=8)
    candidates_per_clue: int = Field(default=6, ge=1, le=15)
    max_calls: int = Field(default=12, ge=1, le=30)
    max_seconds: float = Field(default=180, ge=5, le=600)
    max_search_nodes: int = Field(default=100000, ge=10, le=1000000)
    batch_size: int = Field(default=12, ge=1, le=30)


class SolveRequest(StrictModel):
    puzzle: Puzzle
    options: SolveOptions = Field(default_factory=SolveOptions)


class AgentEvent(StrictModel):
    sequence: int
    kind: str
    message: str
    elapsed_seconds: float
    data: dict[str, Any] = Field(default_factory=dict)


class Usage(StrictModel):
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None


class SolveResult(StrictModel):
    puzzle_id: str
    status: Literal["complete_consistent", "partial", "cancelled", "provider_error"]
    grid: list[str]
    assignments: dict[str, str]
    unresolved_entries: list[str]
    constraint_violations: list[str]
    filled_cells: int
    total_cells: int
    elapsed_seconds: float
    rounds: int
    search_nodes: int
    stop_reason: str
    usage: Usage
    candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    initial_candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    model: str = ""
