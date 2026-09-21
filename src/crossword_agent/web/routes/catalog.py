"""Read authored sample inputs and allowlisted saved puzzle snapshots."""

import json
from contextlib import suppress

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from crossword_agent.models import Puzzle, SolveResult
from crossword_agent.web.services import WebServices


def build_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    history = services.history

    @router.get("/api/samples")
    def samples():
        result = []
        for path in sorted((services.project_root() / "data" / "puzzles").glob("*.json")):
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

    @router.get("/api/user-puzzles")
    def user_puzzles():
        directory = services.project_root() / "artifacts" / "user-puzzles"
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            return {"puzzles": []}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = []
        for item in manifest.get("puzzles", []):
            puzzle_id = item.get("id", "")
            if not puzzle_id or not all(ch.isalnum() or ch == "-" for ch in puzzle_id):
                continue
            path = directory / f"{puzzle_id}.puzzle.json"
            if not path.is_file():
                continue
            puzzle = Puzzle.model_validate_json(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": puzzle_id,
                    "title": puzzle.title,
                    "rows": len(puzzle.grid),
                    "cols": len(puzzle.grid[0]),
                    "answer_type": puzzle.answer_type,
                    "has_result": (directory / f"{puzzle_id}.result.json").is_file(),
                    "source_name": item.get("source_name", ""),
                }
            )
        return {"puzzles": items}

    @router.get("/api/user-puzzles/{puzzle_id}")
    def user_puzzle(puzzle_id: str):
        item = next((item for item in user_puzzles()["puzzles"] if item["id"] == puzzle_id), None)
        if item is None:
            raise HTTPException(404, "Saved image puzzle not found.")
        directory = services.project_root() / "artifacts" / "user-puzzles"
        puzzle = Puzzle.model_validate_json(
            (directory / f"{puzzle_id}.puzzle.json").read_text(encoding="utf-8")
        )
        result_path = directory / f"{puzzle_id}.result.json"
        verification_path = directory / f"{puzzle_id}.verification.json"
        result = (
            json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
        )
        run_id = None
        if result is not None:
            with suppress(ValidationError):
                run_id = history.find_saved_run(puzzle, SolveResult.model_validate(result))
        return {
            "puzzle": puzzle,
            "result": result,
            "run_id": run_id,
            "verification": json.loads(verification_path.read_text(encoding="utf-8"))
            if verification_path.is_file()
            else None,
            "source_name": item["source_name"],
        }

    @router.get("/api/samples/{puzzle_id}")
    def sample(puzzle_id: str):
        # Match parsed IDs, never interpolate untrusted IDs into filesystem paths.
        for path in (services.project_root() / "data" / "puzzles").glob("*.json"):
            puzzle = Puzzle.model_validate_json(path.read_text(encoding="utf-8"))
            if puzzle.id == puzzle_id:
                return puzzle
        raise HTTPException(404, "Sample puzzle not found.")

    return router
