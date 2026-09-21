import json
from types import SimpleNamespace

import pytest

from crossword_agent.config import Settings
from crossword_agent.domain import Entry
from crossword_agent.providers.base import ProviderError
from crossword_agent.providers.nebius import NebiusProvider


@pytest.fixture
def provider():
    value = NebiusProvider(
        Settings(_env_file=None, nebius_api_key="test-placeholder-not-a-real-key")
    )
    yield value
    value.close()


def response(content, finish="stop"):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))],
    )


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "[]",
        '{"entries":[{"id":"99A","candidates":[]}]}',
        '{"entries":[{"id":"1A","candidates":[{"answer":"CAT","score":5}]}]}',
    ],
)
def test_malformed_model_output_has_safe_error(provider, monkeypatch, content):
    monkeypatch.setattr(provider.client.chat.completions, "create", lambda **kw: response(content))
    with pytest.raises(ProviderError) as exc:
        provider.generate(
            [Entry("1A", 1, "across", 0, 0, 3, ((0, 0), (0, 1), (0, 2)), "Feline")],
            patterns={},
            previous={},
            limit=3,
            timeout=10,
        )
    assert exc.value.retryable
    assert exc.value.usage.total_tokens == 30
    assert "test-placeholder" not in str(exc.value)


def test_model_payload_and_usage(provider, monkeypatch):
    payloads = []

    def create(**kwargs):
        payloads.append(kwargs)
        return response('{"entries":[{"id":"1A","candidates":[{"answer":"CAT","score":0.9}]}]}')

    monkeypatch.setattr(provider.client.chat.completions, "create", create)
    result = provider.generate(
        [Entry("1A", 1, "across", 0, 0, 3, ((0, 0), (0, 1), (0, 2)), "Feline")],
        patterns={},
        previous={},
        limit=3,
        timeout=10,
    )
    assert result.candidates["1A"][0].answer == "CAT"
    assert result.usage.model_calls == 1
    assert payloads[0]["model"] == "zai-org/GLM-5.3"
    assert payloads[0]["timeout"] == 10


def test_truncated_response_is_not_accepted(provider, monkeypatch):
    monkeypatch.setattr(
        provider.client.chat.completions, "create", lambda **kw: response("{}", "length")
    )
    with pytest.raises(ProviderError, match="incomplete"):
        provider._request([], 10)


@pytest.mark.parametrize("answer_type,given", [(None, "0"), ("digits", "A")])
def test_image_geometry_preserves_supplied_characters(provider, monkeypatch, answer_type, given):
    from crossword_agent.vision import GridGeometry

    geometry = GridGeometry(["..", ".#"], [20, 40], [20, 40], 20, 20, 3)
    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda data: geometry)
    puzzle = {
        "grid": [given + ".", ".."],
        "clues": {"across": {"1": "10 + 2"}, "down": {"1": "10 + 3"}},
    }
    if answer_type:
        puzzle["answer_type"] = answer_type
    monkeypatch.setattr(
        provider.client.chat.completions,
        "create",
        lambda **kw: response(json.dumps({"puzzle": puzzle, "warnings": []})),
    )
    extracted, warnings, usage = provider.extract_image(b"stub")
    assert extracted["answer_type"] == "digits"
    assert extracted["grid"] == [given + ".", ".#"]
    assert any("geometry repaired" in warning for warning in warnings)
    assert usage.model_calls == 1


def test_image_geometry_does_not_relocate_supplied_characters(provider, monkeypatch):
    from crossword_agent.vision import GridGeometry

    geometry = GridGeometry(["...", ".##"], [20, 40, 60], [20, 40], 20, 20, 4)
    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda data: geometry)
    puzzle = {"grid": ["A.", ".."], "clues": {"across": {"1": "Feline"}, "down": {}}}
    monkeypatch.setattr(
        provider.client.chat.completions,
        "create",
        lambda **kw: response(json.dumps({"puzzle": puzzle})),
    )
    extracted, warnings, _ = provider.extract_image(b"stub")
    assert extracted["grid"] == ["A.", ".."]
    assert any("could not be safely aligned" in warning for warning in warnings)


def test_image_nested_warnings_are_metadata_not_puzzle_fields(provider, monkeypatch):
    from crossword_agent.models import Puzzle

    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda data: None)
    puzzle = {
        "grid": ["..", ".."],
        "clues": {"across": {}, "down": {}},
        "warnings": ["A clue may be blurry."],
    }
    monkeypatch.setattr(
        provider.client.chat.completions,
        "create",
        lambda **kw: response(json.dumps({"puzzle": puzzle, "warnings": []})),
    )
    extracted, warnings, _ = provider.extract_image(b"stub")
    assert "warnings" not in extracted
    assert warnings == ["A clue may be blurry."]
    assert Puzzle.model_validate(extracted).grid == ["..", ".."]
