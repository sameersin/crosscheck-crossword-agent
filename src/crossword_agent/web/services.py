"""Per-application dependencies shared by HTTP route groups."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from fastapi import HTTPException

from crossword_agent.config import Settings
from crossword_agent.evaluation_store import EvaluationStore
from crossword_agent.jobs import JobManager


@dataclass(frozen=True)
class WebServices:
    """Keep each application instance's jobs, persistence, and provider isolated."""

    settings: Settings
    provider_factory: Callable[[], Any]
    history: EvaluationStore
    jobs: JobManager
    extraction_slot: BoundedSemaphore
    project_root: Callable[[], Path]
    static_dir: Path

    def stored_run(self, run_id: str) -> dict:
        """Resolve one immutable run using the shared HTTP not-found response."""
        try:
            return self.history.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Saved run not found.") from exc
