"""Inspect immutable runs and grade them against explicitly approved reference keys."""

from fastapi import APIRouter, HTTPException, Query

from crossword_agent.web.schemas import EvaluateRequest
from crossword_agent.web.services import WebServices


def build_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    history = services.history
    stored_run = services.stored_run

    @router.get("/api/runs")
    def run_history(
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)
    ):
        return history.list_runs(limit=limit, offset=offset)

    @router.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        return stored_run(run_id)

    @router.post("/api/runs/{run_id}/evaluate")
    def grade_run(run_id: str, request: EvaluateRequest):
        run = stored_run(run_id)
        if request.puzzle_id is not None and request.puzzle_id != run["puzzle"]["id"]:
            raise HTTPException(422, "The answer key belongs to a different puzzle ID.")
        try:
            return history.evaluate(
                run_id,
                request.reference_grid,
                source=request.source,
                approved=request.approved,
                source_note=request.source_note,
                expected_fingerprint=request.puzzle_fingerprint,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
