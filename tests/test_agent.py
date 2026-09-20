import json
import threading
from pathlib import Path

import pytest

from crossword_agent.agent import CrosswordAgent, add_usage, merge_candidates
from crossword_agent.domain import parse_entries
from crossword_agent.models import Candidate, Puzzle, SolveOptions, Usage
from crossword_agent.providers.base import GenerationBatch, ProviderError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture():
    puzzle = Puzzle.model_validate_json((ROOT / "data/puzzles/dev-mixed-3.json").read_text())
    key = json.loads((ROOT / "data/solutions/dev-mixed-3.json").read_text())["grid"]
    pool = {
        e.id: [Candidate(answer="".join(key[r][c] for r, c in e.cells), score=0.9)]
        for e in parse_entries(puzzle)
    }
    return puzzle, key, pool


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, entries, **kwargs):
        self.calls.append(([e.id for e in entries], kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return GenerationBatch(
            response, Usage(model_calls=1, prompt_tokens=10, completion_tokens=20, total_tokens=30)
        )


def test_live_style_initial_success(fixture):
    puzzle, key, pool = fixture
    provider = FakeProvider([pool])
    seen = []
    result = CrosswordAgent(provider).solve(puzzle, on_event=seen.append)
    assert result.status == "complete_consistent"
    assert result.grid == key
    assert not result.constraint_violations
    assert result.usage.model_calls == 1
    assert [e.sequence for e in seen] == list(range(1, len(seen) + 1))
    assert result.initial_candidates == result.candidates


def test_missing_answer_triggers_targeted_regeneration(fixture):
    puzzle, key, pool = fixture
    missing = list(pool)[-1]
    first = {k: v for k, v in pool.items() if k != missing}
    provider = FakeProvider([first, pool])
    result = CrosswordAgent(provider).solve(puzzle)
    assert result.grid == key
    assert result.status == "complete_consistent"
    assert result.usage.model_calls == 2
    assert missing in provider.calls[1][0]
    assert any(e.kind == "repair" for e in result.events)
    assert missing not in result.initial_candidates or not result.initial_candidates[missing]


def test_call_budget_returns_consistent_partial(fixture):
    puzzle, _, pool = fixture
    provider = FakeProvider([{list(pool)[0]: pool[list(pool)[0]]}])
    result = CrosswordAgent(provider).solve(puzzle, SolveOptions(max_calls=1))
    assert result.status == "partial"
    assert result.stop_reason == "call_budget"
    assert not result.constraint_violations
    assert len(provider.calls) == 1


def test_retry_counts_failed_attempt(fixture):
    puzzle, _, pool = fixture
    provider = FakeProvider([ProviderError("Temporary error", retryable=True), pool])
    result = CrosswordAgent(provider).solve(puzzle)
    assert result.status == "complete_consistent"
    assert result.usage.model_calls == 2


def test_nonretryable_error_stops(fixture):
    puzzle, _, _ = fixture
    result = CrosswordAgent(FakeProvider([ProviderError("Credentials rejected")])).solve(puzzle)
    assert result.status == "provider_error"
    assert result.usage.model_calls == 1


def test_cancellation_before_generation_spends_nothing(fixture):
    puzzle, _, _ = fixture
    cancel = threading.Event()
    cancel.set()
    result = CrosswordAgent(FakeProvider([])).solve(puzzle, cancel_event=cancel)
    assert result.status == "cancelled"
    assert result.usage.model_calls == 0


def test_shared_candidates_do_not_regenerate_on_success(fixture):
    puzzle, key, pool = fixture
    result = CrosswordAgent(FakeProvider([])).solve(
        puzzle, initial_candidates=pool, initial_usage=Usage(model_calls=1)
    )
    assert result.grid == key
    assert result.usage.model_calls == 1


def test_invalid_candidates_are_filtered(fixture):
    puzzle, _, _ = fixture
    entry = parse_entries(puzzle)[0]
    pool = {}
    accepted, rejected = merge_candidates(
        puzzle, [entry], pool, {entry.id: [Candidate(answer="C4T"), Candidate(answer="TOOLONG")]}
    )
    assert accepted == 0 and rejected == 2


def test_unknown_and_known_cost_are_distinct():
    assert add_usage(Usage(), Usage(model_calls=1)).estimated_cost_usd is None
    assert (
        add_usage(Usage(), Usage(model_calls=1, estimated_cost_usd=0.2)).estimated_cost_usd == 0.2
    )
