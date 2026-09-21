"""Transcribe puzzle and reference images with shared admission and cleanup rules."""

from contextlib import suppress

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from crossword_agent.domain import parse_entries
from crossword_agent.evaluation import validate_reference
from crossword_agent.models import Puzzle
from crossword_agent.providers.base import ProviderError
from crossword_agent.web.services import WebServices
from crossword_agent.web.uploads import read_uploaded_image


def build_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    settings = services.settings
    history = services.history
    factory = services.provider_factory
    extraction_slot = services.extraction_slot
    stored_run = services.stored_run

    def save_reference_attempt(run_id: str, **details) -> dict:
        try:
            return history.record_reference_extraction(
                run_id, model=settings.nebius_vision_model, **details
            )
        except Exception:
            return {
                "extraction_id": None,
                "history_error": "The reference image attempt could not be saved to local history.",
            }

    @router.post("/api/runs/{run_id}/reference-image")
    def reference_image(run_id: str, file: UploadFile):
        run = stored_run(run_id)
        if not settings.provider_ready:
            raise HTTPException(
                503, "Set NEBIUS_API_KEY in the local .env file to enable image extraction."
            )
        normalized = read_uploaded_image(file, max_image_bytes=settings.max_image_bytes)
        if not extraction_slot.acquire(blocking=False):
            raise HTTPException(
                429, "Another image is being transcribed. Please try again shortly."
            )
        provider = None
        try:
            provider = factory()
            puzzle = Puzzle.model_validate(run["puzzle"])
            reference_grid, notices, usage = provider.extract_reference_image(
                puzzle, normalized, "image/png"
            )
            errors = []
            try:
                validate_reference(puzzle, reference_grid)
            except ValueError as exc:
                errors.append(str(exc))
            notices = list(notices)
            notices.append(
                "Review every reference cell and explicitly approve the complete key before grading. Image transcription is a draft."
            )
            attempt = save_reference_attempt(
                run_id,
                status="draft",
                usage=usage,
                reference_grid=reference_grid,
                warnings=notices,
                validation_errors=errors,
            )
            return {
                **attempt,
                "reference_grid": reference_grid,
                "warnings": notices,
                "validation_errors": errors,
                "approved": False,
                "missing_cells": sum(line.count(".") for line in reference_grid),
                "usage": usage.model_dump(),
                "usage_scope": "reference_image_extraction",
                "model": settings.nebius_vision_model,
                "vision_model": settings.nebius_vision_model,
                "puzzle_id": puzzle.id,
                "puzzle_fingerprint": run["puzzle_fingerprint"],
                "source": "uploaded_image",
            }
        except ProviderError as exc:
            attempt = save_reference_attempt(
                run_id, status="provider_error", usage=exc.usage, error=str(exc)
            )
            return JSONResponse(
                status_code=502,
                content={
                    **attempt,
                    "detail": str(exc),
                    "usage": exc.usage.model_dump(),
                    "usage_scope": "reference_image_extraction",
                    "model": settings.nebius_vision_model,
                },
            )
        finally:
            try:
                with suppress(Exception):
                    if provider and callable(getattr(provider, "close", None)):
                        provider.close()
            finally:
                extraction_slot.release()

    @router.post("/api/extract")
    def extract(file: UploadFile):
        if not settings.provider_ready:
            raise HTTPException(
                503, "Set NEBIUS_API_KEY in the local .env file to enable image extraction."
            )
        normalized = read_uploaded_image(file, max_image_bytes=settings.max_image_bytes)
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
                errors = []
            except (ValidationError, ValueError) as exc:
                errors = [str(exc)]
                notices.append(
                    "The extracted structure needs correction. Edit the JSON and validate before solving."
                )
            notices.append(
                "Review the grid, supplied letters, and every clue before solving. Image transcription may be imperfect."
            )
            return {
                "puzzle": puzzle,
                "warnings": notices,
                "usage": usage.model_dump(),
                "model": settings.nebius_vision_model,
                "vision_model": settings.nebius_vision_model,
                "validation_errors": errors,
                "geometry_repaired": any(
                    "geometry repaired" in notice.lower() for notice in notices
                ),
            }
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        finally:
            try:
                with suppress(Exception):
                    if provider and callable(getattr(provider, "close", None)):
                        provider.close()
            finally:
                extraction_slot.release()

    return router
