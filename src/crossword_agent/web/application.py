"""Compose the local web application and its per-instance lifecycle."""

import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from crossword_agent import __version__
from crossword_agent.agent import CrosswordAgent
from crossword_agent.config import PROJECT_ROOT, Settings
from crossword_agent.evaluation_store import EvaluationStore
from crossword_agent.jobs import JobManager
from crossword_agent.providers.nebius import NebiusProvider
from crossword_agent.web.middleware import configure_http_boundary
from crossword_agent.web.routes import catalog, history, images, solving, system
from crossword_agent.web.services import WebServices

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def create_app(
    settings: Settings | None = None,
    provider_factory=None,
    *,
    history_path: Path | None = None,
    import_saved_history: bool = True,
    project_root: Callable[[], Path] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Wire routes without coupling the domain solver to FastAPI or local storage."""
    settings = settings or Settings()
    factory = provider_factory or (lambda: NebiusProvider(settings))
    root = project_root or (lambda: PROJECT_ROOT)
    store = EvaluationStore(history_path or root() / "artifacts/private/evaluations.sqlite3")
    if import_saved_history:
        store.import_saved_runs(root() / "artifacts/user-puzzles")

    def save_run(job, request):
        store.record_run(
            job.id,
            request.puzzle,
            job.result,
            error=job.error,
            created_at=job.created_at_iso,
            context={"solve_options": request.options.model_dump(), "model": settings.nebius_model},
        )

    jobs = JobManager(
        lambda: CrosswordAgent(factory(), model=settings.nebius_model), on_finished=save_run
    )
    services = WebServices(
        settings=settings,
        provider_factory=factory,
        history=store,
        jobs=jobs,
        extraction_slot=threading.BoundedSemaphore(1),
        project_root=root,
        static_dir=static_dir or STATIC_DIR,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.close()

    app = FastAPI(title="Crosscheck Crossword Agent", version=__version__, lifespan=lifespan)
    # These handles are also the existing inspection and injection hooks for local callers.
    app.state.jobs = jobs
    app.state.history = store
    configure_http_boundary(app, max_image_bytes=settings.max_image_bytes)

    for routes in (system, catalog, solving, history, images):
        app.include_router(routes.build_router(services))

    if services.static_dir.exists():
        app.mount("/static", StaticFiles(directory=services.static_dir), name="static")
    return app
