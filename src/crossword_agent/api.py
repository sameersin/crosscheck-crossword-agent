"""Compatible ASGI entry point; HTTP implementation lives in crossword_agent.web."""

from pathlib import Path

from fastapi import FastAPI

from crossword_agent.config import PROJECT_ROOT, Settings
from crossword_agent.web.application import create_app as _create_app
from crossword_agent.web.middleware import BodySizeLimitMiddleware
from crossword_agent.web.schemas import EvaluateRequest
from crossword_agent.web.uploads import prepare_image

STATIC_DIR = Path(__file__).parent / "static"

__all__ = [
    "BodySizeLimitMiddleware",
    "EvaluateRequest",
    "PROJECT_ROOT",
    "STATIC_DIR",
    "app",
    "create_app",
    "prepare_image",
]


def create_app(
    settings: Settings | None = None,
    provider_factory=None,
    *,
    history_path: Path | None = None,
    import_saved_history: bool = True,
) -> FastAPI:
    """Preserve the public factory and its existing provider, path, and state seams."""
    return _create_app(
        settings,
        provider_factory,
        history_path=history_path,
        import_saved_history=import_saved_history,
        # Resolve at request time too: existing callers can replace this path after setup.
        project_root=lambda: PROJECT_ROOT,
        static_dir=STATIC_DIR,
    )


app = create_app()
