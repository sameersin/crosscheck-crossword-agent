from dataclasses import dataclass
from typing import Protocol

from crossword_agent.domain import Entry
from crossword_agent.models import Candidate, Usage


@dataclass
class GenerationBatch:
    candidates: dict[str, list[Candidate]]
    usage: Usage


class ProviderError(RuntimeError):
    """A safe-to-display error, never raw upstream response text or credentials."""

    def __init__(self, message: str, *, retryable: bool = False, usage: Usage | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage or Usage(model_calls=1)


class CandidateProvider(Protocol):
    def generate(
        self,
        entries: list[Entry],
        *,
        patterns: dict[str, str],
        previous: dict[str, list[str]],
        limit: int,
        timeout: float,
    ) -> GenerationBatch: ...
