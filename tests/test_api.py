import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from crossword_agent.api import create_app, prepare_image
from crossword_agent.config import Settings
from crossword_agent.models import Usage
from crossword_agent.providers.base import GenerationBatch

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, nebius_api_key="")
    with TestClient(
        create_app(settings, history_path=tmp_path / "history.sqlite3", import_saved_history=False)
    ) as client:
        yield client


def test_health_and_config_do_not_reveal_secret(client):
    assert client.get("/health").status_code == 200
    payload = client.get("/api/config").json()
    assert payload["provider_ready"] is False
    assert "api_key" not in payload


def test_validate_and_missing_provider(client):
    puzzle = json.loads((ROOT / "data/puzzles/dev-mixed-3.json").read_text())
    assert len(client.post("/api/validate", json=puzzle).json()["entries"]) == 6
    assert client.post("/api/solve", json={"puzzle": puzzle}).status_code == 503
    puzzle["clues"]["across"]["99"] = "Unexpected"
    assert client.post("/api/validate", json=puzzle).status_code == 422


def test_cross_origin_mutation_blocked(client):
    assert (
        client.post(
            "/api/validate", json={}, headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )


def test_unknown_job_and_sample(client):
    assert client.get("/api/jobs/unknown").status_code == 404
    assert client.get("/api/samples/unknown").status_code == 404


def test_invalid_image_rejected():
    with pytest.raises(ValueError, match="not a valid"):
        prepare_image(b"not an image")


def test_image_decoded_and_metadata_removed():
    buf = io.BytesIO()
    Image.new("RGB", (100, 50), "white").save(buf, format="PNG")
    encoded = prepare_image(buf.getvalue())
    assert Image.open(io.BytesIO(encoded)).size == (100, 50)


def test_real_job_lifecycle_with_stub_provider(tmp_path):
    class EmptyProvider:
        def generate(self, entries, **kwargs):
            return GenerationBatch({}, Usage(model_calls=1))

    settings = Settings(_env_file=None, nebius_api_key="test-key")
    with TestClient(
        create_app(
            settings,
            EmptyProvider,
            history_path=tmp_path / "history.sqlite3",
            import_saved_history=False,
        )
    ) as client:
        puzzle = json.loads((ROOT / "data/puzzles/dev-mixed-3.json").read_text())
        response = client.post("/api/solve", json={"puzzle": puzzle, "options": {"max_calls": 1}})
        assert response.status_code == 202
        for _ in range(100):
            job = client.get("/api/jobs/" + response.json()["job_id"]).json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        assert job["result"]["status"] == "partial"
        assert job["events"][-1]["kind"] == "finished"


def test_saved_image_puzzles_are_allowlisted_and_include_results(client, tmp_path, monkeypatch):
    directory = tmp_path / "artifacts" / "user-puzzles"
    directory.mkdir(parents=True)
    puzzle = json.loads((ROOT / "data/puzzles/dev-mixed-3.json").read_text())
    (directory / "pets.puzzle.json").write_text(json.dumps(puzzle), encoding="utf-8")
    (directory / "pets.result.json").write_text('{"status":"partial"}', encoding="utf-8")
    (directory / "pets.verification.json").write_text('{"reviewed":true}', encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps({"puzzles": [{"id": "pets", "source_name": "pets.jpg"}, {"id": "../private"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("crossword_agent.api.PROJECT_ROOT", tmp_path)
    items = client.get("/api/user-puzzles").json()["puzzles"]
    assert len(items) == 1 and items[0]["has_result"]
    payload = client.get("/api/user-puzzles/pets").json()
    assert payload["result"]["status"] == "partial"
    assert payload["verification"]["reviewed"]
    assert client.get("/api/user-puzzles/private").status_code == 404


@pytest.mark.parametrize("valid", [True, False])
def test_extraction_reports_validation_for_review(valid, tmp_path):
    puzzle = json.loads((ROOT / "data/puzzles/dev-mixed-3.json").read_text())
    if not valid:
        puzzle["clues"]["across"].pop("1")

    class VisionProvider:
        def extract_image(self, data):
            assert data.startswith(b"\x89PNG")
            return (
                puzzle,
                ["Grid geometry repaired from detected cell borders."],
                Usage(model_calls=1),
            )

    image = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(image, format="PNG")
    settings = Settings(_env_file=None, nebius_api_key="test-key")
    with TestClient(
        create_app(
            settings,
            VisionProvider,
            history_path=tmp_path / "history.sqlite3",
            import_saved_history=False,
        )
    ) as client:
        response = client.post(
            "/api/extract", files={"file": ("puzzle.png", image.getvalue(), "image/png")}
        )
    assert response.status_code == 200
    payload = response.json()
    assert bool(payload["validation_errors"]) is not valid
    assert payload["geometry_repaired"]
    assert payload["usage"]["model_calls"] == 1
