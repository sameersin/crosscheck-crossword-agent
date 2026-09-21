"""Durable local snapshots and versioned, explicitly approved answer keys.

Original puzzle/result JSON is insert-only. Reference grids live in a different
table and are used only by the evaluator, never supplied to the solving agent.
"""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .domain import parse_entries
from .evaluation import evaluate_result, validate_reference
from .models import Puzzle, SolveResult, Usage

REFERENCE_SOURCES = {
    "human_reviewed_agent_copy",
    "human_entered",
    "uploaded_json",
    "publisher_key",
    "uploaded_image",
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def puzzle_fingerprint(puzzle: Puzzle) -> str:
    """Bind keys to original geometry, supplied characters, type and clue text."""
    payload = {
        "answer_type": puzzle.answer_type,
        "grid": puzzle.grid,
        "clues": puzzle.clues.model_dump(),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _saved_run_id(puzzle: Puzzle, result: SolveResult) -> str:
    digest = hashlib.sha256(
        _json([puzzle.model_dump(), result.model_dump()]).encode("utf-8")
    ).hexdigest()
    return f"import-{digest[:32]}"


class EvaluationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    puzzle_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    puzzle_json TEXT NOT NULL,
                    result_json TEXT,
                    content_hash TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    reference_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_note TEXT NOT NULL,
                    approved INTEGER NOT NULL CHECK (approved = 1),
                    reference_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    UNIQUE (run_id, reference_version)
                );
                CREATE INDEX IF NOT EXISTS runs_created_at ON runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS reference_extractions (
                    extraction_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    usage_json TEXT NOT NULL,
                    reference_json TEXT,
                    warnings_json TEXT NOT NULL,
                    validation_errors_json TEXT NOT NULL,
                    error TEXT
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
            if "context_json" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"
                )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_run(
        self,
        run_id: str,
        puzzle: Puzzle,
        result: SolveResult | None,
        *,
        status: str = "failed",
        error: str | None = None,
        source: str = "live",
        source_label: str = "",
        created_at: str | None = None,
        context: dict | None = None,
    ) -> str:
        parse_entries(puzzle)
        if result is not None and result.puzzle_id != puzzle.id:
            raise ValueError("Original result does not belong to this puzzle.")
        puzzle_json = _json(puzzle.model_dump())
        result_json = _json(result.model_dump()) if result is not None else None
        status = result.status if result is not None else status
        content_hash = hashlib.sha256(
            _json([puzzle_json, result_json, status, error, context or {}]).encode("utf-8")
        ).hexdigest()
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    puzzle_fingerprint(puzzle),
                    created_at or datetime.now(UTC).isoformat(),
                    source,
                    source_label,
                    status,
                    error,
                    puzzle_json,
                    result_json,
                    content_hash,
                    _json(context or {}),
                ),
            )
            existing = connection.execute(
                "SELECT content_hash FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if existing["content_hash"] != content_hash:
                raise ValueError("Original run snapshots are immutable; use a new run ID.")
        return run_id

    def find_saved_run(self, puzzle: Puzzle, result: SolveResult) -> str | None:
        run_id = _saved_run_id(puzzle, result)
        with self._connection() as connection:
            row = connection.execute("SELECT run_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return row["run_id"] if row is not None else None

    @staticmethod
    def _evaluation(row) -> dict:
        return {
            "evaluation_id": row["evaluation_id"],
            "run_id": row["run_id"],
            "reference_version": row["reference_version"],
            "created_at": row["created_at"],
            "source": row["source"],
            "source_note": row["source_note"],
            "approved": bool(row["approved"]),
            "approval_kind": "user_approved",
            "reference_grid": json.loads(row["reference_json"]),
            "metrics": json.loads(row["metrics_json"]),
            "evaluator_version": row["evaluator_version"],
        }

    def get_run(self, run_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            evaluations = [
                self._evaluation(item)
                for item in connection.execute(
                    "SELECT * FROM evaluations WHERE run_id=? ORDER BY reference_version DESC",
                    (run_id,),
                )
            ]
            extractions = [
                self._extraction(item)
                for item in connection.execute(
                    "SELECT * FROM reference_extractions WHERE run_id=? ORDER BY created_at DESC",
                    (run_id,),
                )
            ]
        return {
            "run_id": row["run_id"],
            "puzzle_fingerprint": row["puzzle_fingerprint"],
            "created_at": row["created_at"],
            "source": row["source"],
            "source_label": row["source_label"],
            "timestamp_basis": "imported_at"
            if row["source"] == "saved_import"
            else "run_started_at",
            "status": row["status"],
            "error": row["error"],
            "context": json.loads(row["context_json"]),
            "puzzle": json.loads(row["puzzle_json"]),
            "original_result": json.loads(row["result_json"]) if row["result_json"] else None,
            "evaluations": evaluations,
            "latest_evaluation": evaluations[0] if evaluations else None,
            "reference_extractions": extractions,
        }

    @staticmethod
    def _extraction(row) -> dict:
        usage = json.loads(row["usage_json"])
        return {
            "extraction_id": row["extraction_id"],
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "status": row["status"],
            "model": row["model"],
            "usage": usage,
            "usage_scope": "reference_image_extraction",
            "token_counts_known": usage["total_tokens"] > 0,
            "cost_known": usage["estimated_cost_usd"] is not None,
            "reference_grid": json.loads(row["reference_json"]) if row["reference_json"] else None,
            "warnings": json.loads(row["warnings_json"]),
            "validation_errors": json.loads(row["validation_errors_json"]),
            "error": row["error"],
            "approved": False,
        }

    def record_reference_extraction(
        self,
        run_id: str,
        *,
        model: str,
        status: str,
        usage: Usage,
        reference_grid: list[str] | None = None,
        warnings: list[str] | None = None,
        validation_errors: list[str] | None = None,
        error: str | None = None,
    ) -> dict:
        extraction_id = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO reference_extractions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    extraction_id,
                    run_id,
                    datetime.now(UTC).isoformat(),
                    status,
                    model,
                    _json(usage.model_dump()),
                    _json(reference_grid) if reference_grid is not None else None,
                    _json(warnings or []),
                    _json(validation_errors or []),
                    error,
                ),
            )
            row = connection.execute(
                "SELECT * FROM reference_extractions WHERE extraction_id=?", (extraction_id,)
            ).fetchone()
        return self._extraction(row)

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> dict:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            runs = []
            for row in rows:
                puzzle = json.loads(row["puzzle_json"])
                result = json.loads(row["result_json"]) if row["result_json"] else None
                latest = connection.execute(
                    "SELECT * FROM evaluations WHERE run_id=? ORDER BY reference_version DESC LIMIT 1",
                    (row["run_id"],),
                ).fetchone()
                runs.append(
                    {
                        "run_id": row["run_id"],
                        "puzzle_id": puzzle["id"],
                        "title": puzzle["title"],
                        "answer_type": puzzle.get("answer_type", "letters"),
                        "puzzle_fingerprint": row["puzzle_fingerprint"],
                        "created_at": row["created_at"],
                        "source": row["source"],
                        "source_label": row["source_label"],
                        "status": row["status"],
                        "error": row["error"],
                        "gradeable": result is not None,
                        "filled_cells": result["filled_cells"] if result else None,
                        "total_cells": sum(char != "#" for line in puzzle["grid"] for char in line),
                        "elapsed_seconds": result["elapsed_seconds"] if result else None,
                        "usage": result["usage"] if result else None,
                        "model": result.get("model", "")
                        if result
                        else json.loads(row["context_json"]).get("model", ""),
                        "timestamp_basis": "imported_at"
                        if row["source"] == "saved_import"
                        else "run_started_at",
                        "latest_evaluation": self._evaluation(latest) if latest else None,
                    }
                )
        return {"runs": runs, "total_count": total, "limit": limit, "offset": offset}

    def evaluate(
        self,
        run_id: str,
        reference_grid: list[str],
        *,
        source: str,
        approved: bool,
        source_note: str = "",
        expected_fingerprint: str | None = None,
    ) -> dict:
        if approved is not True:
            raise ValueError("Approve the complete answer key before grading.")
        if source not in REFERENCE_SOURCES:
            raise ValueError("Unsupported answer-key source.")
        run = self.get_run(run_id)
        if expected_fingerprint is not None and expected_fingerprint != run["puzzle_fingerprint"]:
            raise ValueError("The answer key belongs to a different puzzle fingerprint.")
        if run["original_result"] is None:
            raise ValueError("This failed run has no original result to grade.")
        puzzle = Puzzle.model_validate(run["puzzle"])
        validate_reference(puzzle, reference_grid)
        metrics = evaluate_result(
            puzzle, reference_grid, SolveResult.model_validate(run["original_result"])
        )
        evaluation_id = uuid.uuid4().hex
        with self._connection() as connection:
            # Serialize version allocation so simultaneous approvals cannot reuse a version.
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT * FROM evaluations WHERE run_id=? ORDER BY reference_version DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if latest is not None and (
                latest["reference_json"] == _json(reference_grid)
                and latest["source"] == source
                and latest["source_note"] == source_note
            ):
                response = self._evaluation(latest)
                response["puzzle_fingerprint"] = run["puzzle_fingerprint"]
                return response
            version = connection.execute(
                "SELECT COALESCE(MAX(reference_version), 0) + 1 FROM evaluations WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO evaluations VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    evaluation_id,
                    run_id,
                    version,
                    datetime.now(UTC).isoformat(),
                    source,
                    source_note,
                    _json(reference_grid),
                    _json(metrics),
                    __version__,
                ),
            )
            row = connection.execute(
                "SELECT * FROM evaluations WHERE evaluation_id=?", (evaluation_id,)
            ).fetchone()
        response = self._evaluation(row)
        response["puzzle_fingerprint"] = run["puzzle_fingerprint"]
        return response

    def import_saved_runs(self, directory: Path) -> int:
        """Import saved snapshots idempotently, without inventing reference approval."""
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            return 0
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(manifest, dict) or not isinstance(manifest.get("puzzles"), list):
            return 0
        imported = 0
        for item in manifest.get("puzzles", []):
            if not isinstance(item, dict):
                continue
            puzzle_id = item.get("id")
            if (
                not isinstance(puzzle_id, str)
                or not puzzle_id
                or not all(ch.isalnum() or ch == "-" for ch in puzzle_id)
            ):
                continue
            puzzle_path = directory / f"{puzzle_id}.puzzle.json"
            # Earlier named snapshots precede the current saved result in import order.
            paths = [
                *sorted(directory.glob(f"{puzzle_id}.*.result.json")),
                directory / f"{puzzle_id}.result.json",
            ]
            for path in paths:
                if not puzzle_path.is_file() or not path.is_file():
                    continue
                try:
                    puzzle = Puzzle.model_validate_json(puzzle_path.read_text(encoding="utf-8"))
                    result = SolveResult.model_validate_json(path.read_text(encoding="utf-8"))
                    run_id = _saved_run_id(puzzle, result)
                    self.record_run(
                        run_id, puzzle, result, source="saved_import", source_label=path.name
                    )
                    imported += 1
                except (OSError, ValueError):
                    continue
        return imported
