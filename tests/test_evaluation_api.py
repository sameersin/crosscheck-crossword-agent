import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from crossword_agent.agent import CrosswordAgent
from crossword_agent.api import create_app
from crossword_agent.config import Settings
from crossword_agent.jobs import Job, JobManager
from crossword_agent.models import Clues, Puzzle, SolveRequest, Usage
from crossword_agent.providers.base import ProviderError


@pytest.fixture
def numeric_puzzle():
    return Puzzle(
        id="numeric-test",
        answer_type="digits",
        grid=["1.", ".."],
        clues=Clues(across={"1": "6+6", "3": "30+4"}, down={"1": "10+3", "2": "20+4"}),
    )


@pytest.fixture
def app(tmp_path, numeric_puzzle):
    app = create_app(
        Settings(_env_file=None, nebius_api_key="test-key"),
        object,
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    app.state.history.record_run(
        "original", numeric_puzzle, CrosswordAgent(object()).solve(numeric_puzzle)
    )
    return app


def grade_payload(**overrides):
    return {
        "reference_grid": ["12", "34"],
        "source": "human_entered",
        "approved": True,
        **overrides,
    }


def test_history_api_grades_saved_result_and_survives_restart(app, tmp_path):
    with TestClient(app) as client:
        original = client.get("/api/runs/original").json()["original_result"]
        assert client.get("/api/runs").json()["total_count"] == 1
        response = client.post("/api/runs/original/evaluate", json=grade_payload())
        assert response.status_code == 200
        evaluation = response.json()
        assert evaluation["metrics"]["exact_puzzle"]
        assert (
            client.post("/api/runs/original/evaluate", json=grade_payload()).json()["evaluation_id"]
            == evaluation["evaluation_id"]
        )
        assert client.get("/api/runs/original").json()["original_result"] == original
        assert client.get("/api/runs?limit=0").status_code == 422
        assert client.get("/api/runs/missing").status_code == 404
    reopened = create_app(
        Settings(_env_file=None, nebius_api_key=""),
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    with TestClient(reopened) as client:
        record = client.get("/api/runs/original").json()
        assert record["original_result"] == original
        assert record["latest_evaluation"]["evaluation_id"] == evaluation["evaluation_id"]


def test_saved_puzzle_links_exact_imported_snapshot_without_duplicates(
    tmp_path, numeric_puzzle, monkeypatch
):
    directory = tmp_path / "artifacts/user-puzzles"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({"puzzles": [{"id": "numeric"}]}))
    (directory / "numeric.puzzle.json").write_text(numeric_puzzle.model_dump_json())
    result = CrosswordAgent(object()).solve(numeric_puzzle)
    (directory / "numeric.result.json").write_text(result.model_dump_json())
    monkeypatch.setattr("crossword_agent.api.PROJECT_ROOT", tmp_path)
    app = create_app(
        Settings(_env_file=None, nebius_api_key=""), history_path=tmp_path / "history.sqlite3"
    )
    with TestClient(app) as client:
        for _ in range(2):
            saved = client.get("/api/user-puzzles/numeric").json()
            assert saved["run_id"].startswith("import-")
            assert (
                client.get(f"/api/runs/{saved['run_id']}").json()["original_result"]
                == result.model_dump()
            )
        assert client.get("/api/runs").json()["total_count"] == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"approved": False},
        {"approved": "true"},
        {"approved": 1},
        {"reference_grid": ["12", "3."]},
        {"reference_grid": ["92", "34"]},
        {"reference_grid": ["12", "3#"]},
        {"puzzle_fingerprint": "0" * 64},
        {"puzzle_id": "other-puzzle"},
        {"source": "automatically_verified"},
        {"original_result": {"grid": ["12", "34"]}},
    ],
)
def test_approval_rejects_untrusted_or_incompatible_keys(app, updates):
    with TestClient(app) as client:
        response = client.post("/api/runs/original/evaluate", json=grade_payload(**updates))
        assert response.status_code == 422
        assert client.get("/api/runs/original").json()["latest_evaluation"] is None


def test_api_live_run_persists_before_terminal_status(tmp_path, numeric_puzzle):
    app = create_app(
        Settings(_env_file=None, nebius_api_key="test-key"),
        object,
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    with TestClient(app) as client:
        response = client.post("/api/solve", json={"puzzle": numeric_puzzle.model_dump()})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        assert job["run_id"] == job_id and job["history_error"] is None
        stored = client.get(f"/api/runs/{job_id}").json()
        assert stored["original_result"] == job["result"]
        assert stored["context"]["solve_options"]["max_calls"] == 12
        assert stored["latest_evaluation"] is None


@pytest.mark.parametrize("result_status", ["partial", "provider_error", "cancelled", None])
def test_every_terminal_run_remains_in_history(tmp_path, numeric_puzzle, result_status):
    result = CrosswordAgent(object()).solve(numeric_puzzle)
    if result_status is not None:
        result = result.model_copy(update={"status": result_status})

    class FinalAgent:
        provider = object()

        def solve(self, *args, **kwargs):
            if result_status is None:
                raise RuntimeError("Private upstream failure must not appear in API")
            return result

    app = create_app(
        Settings(_env_file=None, nebius_api_key="test-key"),
        object,
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    app.state.jobs.agent_factory = FinalAgent
    with TestClient(app) as client:
        job_id = client.post("/api/solve", json={"puzzle": numeric_puzzle.model_dump()}).json()[
            "job_id"
        ]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert job["run_id"] == job_id
        record = client.get(f"/api/runs/{job_id}").json()
        assert record["status"] == (result_status or "failed")
        assert record["original_result"] == (result.model_dump() if result_status else None)
        assert record["latest_evaluation"] is None
        assert "Private upstream failure" not in str(record)
        assert client.get("/api/runs").json()["total_count"] == 1


@pytest.mark.parametrize("grid", [["12", "3."], ["12", "34"], ["12", "3#"], ["12", "345"]])
def test_reference_image_stays_editable_draft_with_separate_usage(tmp_path, numeric_puzzle, grid):
    original = CrosswordAgent(object()).solve(numeric_puzzle)

    class VisionProvider:
        def extract_reference_image(self, puzzle, data, mime):
            assert puzzle == numeric_puzzle
            assert data.startswith(b"\x89PNG") and mime == "image/png"
            return grid, [], Usage(model_calls=1, total_tokens=200, estimated_cost_usd=0.02)

        def close(self):
            raise RuntimeError("cleanup must not hide draft")

    app = create_app(
        Settings(_env_file=None, nebius_api_key="test-key"),
        VisionProvider,
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    app.state.history.record_run("run", numeric_puzzle, original)
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, format="PNG")
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/runs/run/reference-image",
                files={"file": ("key.png", image.getvalue(), "image/png")},
            )
            assert response.status_code == 200
            draft = response.json()
            assert draft["reference_grid"] == grid and draft["approved"] is False
            assert bool(draft["validation_errors"]) is (grid != ["12", "34"])
            assert draft["missing_cells"] == sum(line.count(".") for line in grid)
            assert draft["usage_scope"] == "reference_image_extraction"
            assert draft["usage"]["model_calls"] == 1
            assert draft["vision_model"] == "zai-org/GLM-5.3-Flash"
        stored = client.get("/api/runs/run").json()
        assert stored["original_result"] == original.model_dump()
        assert stored["evaluations"] == []
        assert len(stored["reference_extractions"]) == 2
        assert all(item["status"] == "draft" for item in stored["reference_extractions"])
        assert all(item["token_counts_known"] for item in stored["reference_extractions"])
        assert all(item["cost_known"] for item in stored["reference_extractions"])


@pytest.mark.parametrize("reported_usage", [False, True])
def test_reference_image_failure_releases_slot_and_rejects_unknown_run(
    tmp_path, numeric_puzzle, reported_usage
):
    usage = (
        Usage(model_calls=1, total_tokens=120, estimated_cost_usd=0.001) if reported_usage else None
    )

    class FailedVision:
        def extract_reference_image(self, *args):
            raise ProviderError("Grid does not match the saved puzzle.", usage=usage)

        def close(self):
            raise RuntimeError("cleanup")

    app = create_app(
        Settings(_env_file=None, nebius_api_key="test-key"),
        FailedVision,
        history_path=tmp_path / "history.sqlite3",
        import_saved_history=False,
    )
    app.state.history.record_run(
        "run", numeric_puzzle, CrosswordAgent(object()).solve(numeric_puzzle)
    )
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, format="PNG")
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/runs/run/reference-image",
                files={"file": ("key.png", image.getvalue(), "image/png")},
            )
            assert response.status_code == 502
            assert response.json()["usage"]["model_calls"] == 1
            assert response.json()["token_counts_known"] is reported_usage
            assert response.json()["cost_known"] is reported_usage
            if reported_usage:
                assert response.json()["usage"] == usage.model_dump()
        attempts = client.get("/api/runs/run").json()["reference_extractions"]
        assert len(attempts) == 2
        assert all(item["status"] == "provider_error" for item in attempts)
        assert all(item["token_counts_known"] is reported_usage for item in attempts)
        assert (
            client.post(
                "/api/runs/missing/reference-image",
                files={"file": ("key.png", image.getvalue(), "image/png")},
            ).status_code
            == 404
        )


def test_history_failure_does_not_replace_completed_output(numeric_puzzle):
    completed = CrosswordAgent(object()).solve(numeric_puzzle)

    class Agent:
        provider = object()

        def solve(self, *args, **kwargs):
            return completed

    def unavailable_history(*args):
        raise OSError("disk full")

    manager = JobManager(Agent, capacity=1, on_finished=unavailable_history)
    try:
        job = Job(id="disk-full")
        manager.jobs[job.id] = job
        assert manager.slots.acquire(blocking=False)
        manager._run(job, SolveRequest(puzzle=numeric_puzzle))
        snapshot = manager.snapshot(job.id)
        assert snapshot["status"] == "completed"
        assert snapshot["result"] == completed.model_dump()
        assert snapshot["history_error"] and snapshot["run_id"] is None
        assert manager.slots.acquire(blocking=False)
        manager.slots.release()
    finally:
        manager.close()
