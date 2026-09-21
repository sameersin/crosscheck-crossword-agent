import pytest

from crossword_agent.agent import CrosswordAgent
from crossword_agent.models import Candidate, Clues, Puzzle, SolveOptions, Usage
from crossword_agent.providers.base import GenerationBatch


def sparse_puzzle(answer_type="letters"):
    return Puzzle(
        grid=["##.##", ".....", "##.##"],
        answer_type=answer_type,
        clues=Clues(
            across={"2": "Following this time" if answer_type == "letters" else "12000+345"},
            down={"1": "Consumed" if answer_type == "letters" else "130+3"},
        ),
    )


FIRST = {"1D": [Candidate(answer="ATE", score=0.9)], "2A": [Candidate(answer="CATER", score=0.4)]}


class ReviewProvider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def generate(self, entries, **kwargs):
        self.calls.append({"ids": [entry.id for entry in entries], **kwargs})
        response = self.responses[len(self.calls) - 1]
        return GenerationBatch(response, Usage(model_calls=1))


def test_independent_review_can_replace_weak_fill_with_higher_ranked_alternative():
    provider = ReviewProvider(
        [
            FIRST,
            {
                "1D": [Candidate(answer="ATE", score=0.9)],
                "2A": [Candidate(answer="LATER", score=0.95)],
            },
        ]
    )
    result = CrosswordAgent(provider).solve(sparse_puzzle())
    assert result.status == "complete_consistent"
    assert result.assignments["2A"] == "LATER"
    assert result.usage.model_calls == 2
    assert result.rounds == 2
    assert provider.calls[1]["previous"] == {"1D": [], "2A": []}
    assert provider.calls[1]["patterns"] == {"1D": ".T.", "2A": "..T.."}
    assert len([event for event in result.events if event.kind == "review"]) == 1


def test_no_new_review_alternatives_preserve_complete_fill_without_repeated_review():
    provider = ReviewProvider([FIRST, {}])
    result = CrosswordAgent(provider).solve(sparse_puzzle(), SolveOptions(max_rounds=8))
    assert result.status == "complete_consistent"
    assert result.assignments["2A"] == "CATER"
    assert result.usage.model_calls == 2
    assert result.rounds == 2


@pytest.mark.parametrize("options", [SolveOptions(max_calls=1), SolveOptions(max_rounds=1)])
def test_review_respects_remaining_call_and_round_budget(options):
    provider = ReviewProvider([FIRST])
    result = CrosswordAgent(provider).solve(sparse_puzzle(), options)
    assert result.status == "complete_consistent"
    assert result.usage.model_calls == 1
    assert result.rounds == 1
    review = next(event for event in result.events if event.kind == "review")
    assert review.data["performed"] is False


def test_review_batching_never_exceeds_call_limit():
    provider = ReviewProvider(
        [
            {"1D": FIRST["1D"]},
            {"2A": FIRST["2A"]},
            {"1D": FIRST["1D"]},
        ]
    )
    result = CrosswordAgent(provider).solve(
        sparse_puzzle(), SolveOptions(batch_size=1, max_calls=3, max_rounds=8)
    )
    assert result.status == "complete_consistent"
    assert result.usage.model_calls == 3
    assert len(provider.calls) == 3
    assert [entry_id for call in provider.calls[2:] for entry_id in call["ids"]] == ["1D"]


def test_digit_entries_are_never_sent_for_weak_crossing_review():
    provider = ReviewProvider([])
    result = CrosswordAgent(provider).solve(sparse_puzzle("digits"))
    assert result.status == "complete_consistent"
    assert result.assignments == {"1D": "133", "2A": "12345"}
    assert not provider.calls
    assert not any(event.kind == "review" for event in result.events)


def test_entries_with_existing_diverse_candidates_do_not_get_extra_pass():
    initial = {
        "1D": [Candidate(answer="ATE", score=0.9), Candidate(answer="ITS", score=0.2)],
        "2A": [Candidate(answer="CATER", score=0.4), Candidate(answer="LATER", score=0.95)],
    }
    provider = ReviewProvider([initial])
    result = CrosswordAgent(provider).solve(sparse_puzzle())
    assert result.status == "complete_consistent"
    assert result.usage.model_calls == 1
    assert not any(event.kind == "review" for event in result.events)
