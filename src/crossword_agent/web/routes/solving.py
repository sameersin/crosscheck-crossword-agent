"""Puzzle validation and bounded asynchronous solve-job endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from crossword_agent.domain import parse_entries
from crossword_agent.jobs import CapacityError
from crossword_agent.models import Puzzle, SolveRequest
from crossword_agent.web.services import WebServices


def build_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    settings = services.settings
    jobs = services.jobs

    @router.post("/api/validate")
    def validate(puzzle: Puzzle):
        return {"puzzle": puzzle, "entries": [asdict(entry) for entry in parse_entries(puzzle)]}

    @router.post("/api/solve", status_code=202)
    def solve(request: SolveRequest):
        parse_entries(request.puzzle)
        if not settings.provider_ready:
            raise HTTPException(503, "Set NEBIUS_API_KEY in the local .env file to enable solving.")
        try:
            return {"job_id": jobs.submit(request)}
        except CapacityError as exc:
            raise HTTPException(429, str(exc)) from exc

    @router.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        try:
            return jobs.snapshot(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Run not found or expired. Start a new run.") from exc

    @router.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        try:
            jobs.cancel(job_id)
            return {"cancel_requested": True}
        except KeyError as exc:
            raise HTTPException(404, "Run not found.") from exc

    return router
