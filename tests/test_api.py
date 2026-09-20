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
def client():
    settings = Settings(_env_file=None, nebius_api_key="")
    with TestClient(create_app(settings)) as client:
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


def test_real_job_lifecycle_with_stub_provider():
    class EmptyProvider:
        def generate(self, entries, **kwargs):
            return GenerationBatch({}, Usage(model_calls=1))

    settings = Settings(_env_file=None, nebius_api_key="test-key")
    with TestClient(create_app(settings, EmptyProvider)) as client:
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
