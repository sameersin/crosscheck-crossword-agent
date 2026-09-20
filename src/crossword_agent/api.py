"""Local HTTP boundary. All puzzle solving remains independently usable from Python/CLI."""

import io
import json
import threading
import warnings
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crossword_agent import __version__
from crossword_agent.agent import CrosswordAgent
from crossword_agent.config import PROJECT_ROOT, Settings
from crossword_agent.domain import PuzzleValidationError, parse_entries
from crossword_agent.jobs import CapacityError, JobManager
from crossword_agent.models import Puzzle, SolveRequest
from crossword_agent.providers.base import ProviderError
from crossword_agent.providers.nebius import NebiusProvider

STATIC_DIR = Path(__file__).parent / "static"


class BodySizeLimitMiddleware:
    """Bound actual body bytes before JSON/multipart parsing, including chunked uploads."""

    def __init__(self, app: ASGIApp, max_image_bytes: int):
        self.app = app
        self.max_image_bytes = max_image_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        limit = self.max_image_bytes + 100000 if scope["path"] == "/api/extract" else 512000
        lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]
        try:
            if len(lengths) > 1:
                raise ValueError("Repeated content length")
            declared = int(lengths[0]) if lengths else 0
            if declared < 0:
                raise ValueError("Negative content length")
        except ValueError:
            await JSONResponse(status_code=400, content={"detail": "Invalid content length."})(
                scope, receive, send
            )
            return
        if declared > limit:
            await JSONResponse(
                status_code=413, content={"detail": "Upload exceeds the allowed size."}
            )(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse(
                    status_code=413, content={"detail": "Upload exceeds the allowed size."}
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        payload = bytes(body)
        del body
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def prepare_image(raw: bytes) -> bytes:
    """Decode, bound and re-encode actual image content; remove metadata before transmission."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Use a PNG, JPEG, or WebP image.")
                if source.width * source.height > 16000000:
                    raise ValueError("Image is too large: maximum 16 million pixels.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2400, 2400))
                target = io.BytesIO()
                image.save(target, format="PNG")
                return target.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc


def create_app(settings: Settings | None = None, provider_factory=None) -> FastAPI:
    settings = settings or Settings()
    factory = provider_factory or (lambda: NebiusProvider(settings))
    jobs = JobManager(lambda: CrosswordAgent(factory(), model=settings.nebius_model))
    extraction_slot = threading.BoundedSemaphore(1)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.close()

    app = FastAPI(title="Crosscheck Crossword Agent", version=__version__, lifespan=lifespan)
    app.state.jobs = jobs
    app.add_middleware(BodySizeLimitMiddleware, max_image_bytes=settings.max_image_bytes)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin write requests are not allowed."},
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(PuzzleValidationError)
    async def invalid_puzzle(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    def config():
        return {
            "provider_ready": settings.provider_ready,
            "model": settings.nebius_model,
            "limits": {"max_image_bytes": settings.max_image_bytes},
            "version": __version__,
        }

    @app.get("/api/samples")
    def samples():
        result = []
        for path in sorted((PROJECT_ROOT / "data" / "puzzles").glob("*.json")):
            puzzle = Puzzle.model_validate_json(path.read_text(encoding="utf-8"))
            result.append(
                {
                    "id": puzzle.id,
                    "title": puzzle.title,
                    "rows": len(puzzle.grid),
                    "cols": len(puzzle.grid[0]),
                    "description": "Original authored assessment fixture",
                }
            )
        return {"samples": result}

    @app.get("/api/samples/{puzzle_id}")
    def sample(puzzle_id: str):
        # Match parsed IDs, never interpolate untrusted IDs into filesystem paths.
        for path in (PROJECT_ROOT / "data" / "puzzles").glob("*.json"):
            puzzle = Puzzle.model_validate_json(path.read_text(encoding="utf-8"))
            if puzzle.id == puzzle_id:
                return puzzle
        raise HTTPException(404, "Sample puzzle not found.")

    @app.post("/api/validate")
    def validate(puzzle: Puzzle):
        return {"puzzle": puzzle, "entries": [asdict(entry) for entry in parse_entries(puzzle)]}

    @app.post("/api/solve", status_code=202)
    def solve(request: SolveRequest):
        parse_entries(request.puzzle)
        if not settings.provider_ready:
            raise HTTPException(503, "Set NEBIUS_API_KEY in the local .env file to enable solving.")
        try:
            return {"job_id": jobs.submit(request)}
        except CapacityError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        try:
            return jobs.snapshot(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Run not found or expired. Start a new run.") from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        try:
            jobs.cancel(job_id)
            return {"cancel_requested": True}
        except KeyError as exc:
            raise HTTPException(404, "Run not found.") from exc

    @app.post("/api/extract")
    def extract(file: UploadFile):
        if not settings.provider_ready:
            raise HTTPException(
                503, "Set NEBIUS_API_KEY in the local .env file to enable image extraction."
            )
        raw = file.file.read(settings.max_image_bytes + 1)
        if len(raw) > settings.max_image_bytes:
            raise HTTPException(413, "Image exceeds the 10 MB upload limit.")
        try:
            normalized = prepare_image(raw)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not extraction_slot.acquire(blocking=False):
            raise HTTPException(
                429, "Another image is being transcribed. Please try again shortly."
            )
        provider = None
        try:
            provider = factory()
            puzzle, notices, usage = provider.extract_image(normalized)
            try:
                parsed = Puzzle.model_validate(puzzle)
                parse_entries(parsed)
                puzzle = parsed.model_dump()
            except (ValidationError, ValueError):
                notices.append(
                    "The extracted structure needs correction. Edit the JSON and validate before solving."
                )
            notices.append(
                "Review the grid, supplied letters, and every clue before solving. Image transcription may be imperfect."
            )
            return {"puzzle": puzzle, "warnings": notices, "usage": usage.model_dump()}
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        finally:
            try:
                with suppress(Exception):
                    if provider and callable(getattr(provider, "close", None)):
                        provider.close()
            finally:
                extraction_slot.release()

    @app.get("/api/evaluation")
    def evaluation():
        report = PROJECT_ROOT / "artifacts" / "evaluation" / "report.json"
        return (
            json.loads(report.read_text(encoding="utf-8"))
            if report.is_file()
            else {"available": False}
        )

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
