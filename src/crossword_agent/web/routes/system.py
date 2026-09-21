"""Health, safe public configuration, benchmark report, and browser entry point."""

import json

from fastapi import APIRouter
from fastapi.responses import FileResponse

from crossword_agent import __version__
from crossword_agent.web.services import WebServices


def build_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    settings = services.settings

    @router.get("/health")
    @router.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "model": settings.nebius_model,
            "vision_model": settings.nebius_vision_model,
        }

    @router.get("/api/config")
    def config():
        return {
            "provider_ready": settings.provider_ready,
            "model": settings.nebius_model,
            "vision_model": settings.nebius_vision_model,
            "limits": {"max_image_bytes": settings.max_image_bytes},
            "version": __version__,
        }

    @router.get("/api/evaluation")
    def evaluation():
        report = services.project_root() / "artifacts" / "evaluation" / "report.json"
        return (
            json.loads(report.read_text(encoding="utf-8"))
            if report.is_file()
            else {"available": False}
        )

    @router.get("/")
    def index():
        return FileResponse(services.static_dir / "index.html")

    return router
