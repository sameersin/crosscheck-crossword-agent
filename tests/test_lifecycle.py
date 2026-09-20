import asyncio
import io
from threading import Event

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from crossword_agent.agent import CrosswordAgent
from crossword_agent.api import BodySizeLimitMiddleware, create_app
from crossword_agent.config import Settings
from crossword_agent.domain import validate_assignments
from crossword_agent.jobs import Job, JobManager
from crossword_agent.models import Candidate, Clues, Puzzle, SolveRequest, Usage
from crossword_agent.providers.base import ProviderError
from crossword_agent.search import solve_constraints


@pytest.fixture
def puzzle_and_pool():
    puzzle = Puzzle(
        grid=["..", ".."],
        clues=Clues(across={"1": "Top", "3": "Bottom"}, down={"1": "Left", "2": "Right"}),
    )
    candidates = {
        key: [Candidate(answer=answer)]
        for key, answer in {"1A": "AT", "3A": "SO", "1D": "AS", "2D": "TO"}.items()
    }
    return puzzle, candidates


def test_search_cancellation_preserves_consistent_incumbent(puzzle_and_pool, monkeypatch):
    puzzle, candidates = puzzle_and_pool
    cancel = Event()
    calls = 0

    def cancel_after_two_nodes():
        nonlocal calls
        calls += 1
        if calls >= 3:
            cancel.set()
        return calls >= 3

    monkeypatch.setattr(cancel, "is_set", cancel_after_two_nodes)
    result = solve_constraints(puzzle, candidates, cancel_event=cancel)
    assert result.exhausted
    assert result.nodes == 2
    assert len(result.assignments) == 2
    assert not validate_assignments(puzzle, result.assignments)


def test_agent_cancellation_during_successful_search_is_not_reported_complete(
    puzzle_and_pool, monkeypatch
):
    puzzle, candidates = puzzle_and_pool
    cancel = Event()

    def cancel_at_search_completion(*args, **kwargs):
        assert kwargs["cancel_event"] is cancel
        result = solve_constraints(*args, **kwargs)
        assert result.complete
        cancel.set()
        return result

    monkeypatch.setattr("crossword_agent.agent.solve_constraints", cancel_at_search_completion)
    result = CrosswordAgent(object()).solve(
        puzzle, initial_candidates=candidates, cancel_event=cancel
    )
    assert result.status == "cancelled"
    assert result.stop_reason == "cancelled"
    assert result.grid == ["AT", "SO"]
    assert result.events[-1].data["status"] == "cancelled"


def test_agent_honors_cancellation_in_last_search_event(puzzle_and_pool):
    puzzle, candidates = puzzle_and_pool
    cancel = Event()

    def on_event(event):
        if event.kind == "search_complete":
            cancel.set()

    result = CrosswordAgent(object()).solve(
        puzzle, initial_candidates=candidates, cancel_event=cancel, on_event=on_event
    )
    assert result.status == "cancelled"
    assert result.grid == ["AT", "SO"]


def test_job_cleanup_failure_preserves_result_and_releases_slot(puzzle_and_pool):
    puzzle, candidates = puzzle_and_pool
    completed = CrosswordAgent(object()).solve(puzzle, initial_candidates=candidates)

    class BadCleanupProvider:
        def close(self):
            raise RuntimeError("transport cleanup failed")

    class FinishedAgent:
        provider = BadCleanupProvider()

        def solve(self, *args, **kwargs):
            return completed

    manager = JobManager(FinishedAgent, capacity=1)
    try:
        job = Job(id="cleanup-test")
        manager.jobs[job.id] = job
        assert manager.slots.acquire(blocking=False)
        manager._run(job, SolveRequest(puzzle=puzzle))
        snapshot = manager.snapshot(job.id)
        assert snapshot["status"] == "completed"
        assert snapshot["result"]["grid"] == ["AT", "SO"]
        assert snapshot["error"] is None
        assert manager.slots.acquire(blocking=False)
        manager.slots.release()
    finally:
        manager.close()


@pytest.mark.parametrize("extraction_fails", [False, True])
def test_extraction_cleanup_never_hides_response_or_leaks_slot(puzzle_and_pool, extraction_fails):
    puzzle, _ = puzzle_and_pool

    class BadCleanupProvider:
        def extract_image(self, *_args, **_kwargs):
            if extraction_fails:
                raise ProviderError("Safe extraction failure")
            return puzzle.model_dump(), [], Usage(model_calls=1)

        def close(self):
            raise RuntimeError("transport cleanup failed")

    image = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="PNG")
    settings = Settings(_env_file=None, nebius_api_key="test-key")
    with TestClient(create_app(settings, BadCleanupProvider)) as client:
        for _ in range(2):
            response = client.post(
                "/api/extract", files={"file": ("puzzle.png", image.getvalue(), "image/png")}
            )
            assert response.status_code == (502 if extraction_fails else 200)
            if extraction_fails:
                assert response.json()["detail"] == "Safe extraction failure"
            else:
                assert response.json()["puzzle"] == puzzle.model_dump()


def run_body_guard(chunks, *, path="/api/validate", headers=None, max_image_bytes=1024):
    """Exercise real ASGI receive messages, without a client adding Content-Length."""
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    calls = 0
    consumed = 0
    response = []
    forwarded = []

    async def receive():
        nonlocal consumed
        if consumed >= len(messages):
            return {"type": "http.disconnect"}
        message = messages[consumed]
        consumed += 1
        return message

    async def endpoint(scope, receive, send):
        nonlocal calls
        calls += 1
        forwarded.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        response.append(message)

    guard = BodySizeLimitMiddleware(endpoint, max_image_bytes=max_image_bytes)
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers or []}
    asyncio.run(guard(scope, receive, send))
    status = next(
        message["status"] for message in response if message["type"] == "http.response.start"
    )
    return status, calls, consumed, forwarded


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_actual_body_limit_cannot_be_bypassed_by_missing_or_false_length(headers):
    status, calls, consumed, _ = run_body_guard(
        [b"x" * 256000, b"x" * 256001, b"never-read"], headers=headers
    )
    assert status == 413
    assert calls == 0
    assert consumed == 2


def test_chunked_multipart_is_rejected_before_parsing_or_spooling():
    status, calls, consumed, _ = run_body_guard(
        [b"x" * 50000, b"x" * 50000, b"x" * 1025],
        path="/api/extract",
        headers=[(b"transfer-encoding", b"chunked")],
    )
    assert status == 413
    assert calls == 0
    assert consumed == 3


def test_allowed_chunked_body_is_replayed_exactly_once():
    status, calls, consumed, forwarded = run_body_guard([b"a" * 256000, b"b" * 256000])
    assert status == 204
    assert calls == 1
    assert consumed == 2
    assert forwarded == [
        {"type": "http.request", "body": b"a" * 256000 + b"b" * 256000, "more_body": False}
    ]


@pytest.mark.parametrize(
    "headers, expected",
    [
        ([(b"content-length", b"-1")], 400),
        ([(b"content-length", b"abc")], 400),
        ([(b"content-length", b"2"), (b"content-length", b"3")], 400),
        ([(b"content-length", b"512001")], 413),
    ],
)
def test_bad_length_header_rejected_without_reading_body(headers, expected):
    status, calls, consumed, _ = run_body_guard([b"unread"], headers=headers)
    assert status == expected
    assert calls == 0
    assert consumed == 0


def test_api_applies_body_guard_to_streamed_request():
    settings = Settings(_env_file=None, nebius_api_key="")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/validate",
            content=iter([b"x" * 256000, b"x" * 256001]),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 413
        assert response.headers["cache-control"] == "no-store"
