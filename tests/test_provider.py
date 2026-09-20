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
    assert payloads[0]["model"] == "zai-org/GLM-5.3-Flash"
    assert payloads[0]["timeout"] == 10


def test_truncated_response_is_not_accepted(provider, monkeypatch):
    monkeypatch.setattr(
        provider.client.chat.completions, "create", lambda **kw: response("{}", "length")
    )
    with pytest.raises(ProviderError, match="incomplete"):
        provider._request([], 10)
