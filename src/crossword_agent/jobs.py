"""Bounded in-process job lifecycle for the local assessment application."""

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crossword_agent.agent import CrosswordAgent
from crossword_agent.models import AgentEvent, SolveRequest, SolveResult


class CapacityError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    status: str = "queued"
    events: list[AgentEvent] = field(default_factory=list)
    result: SolveResult | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    created_at_iso: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    history_saved: bool = False
    history_error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class JobManager:
    """Bound live workers and optionally snapshot final runs before exposing completion."""

    def __init__(
        self,
        agent_factory: Callable[[], CrosswordAgent],
        capacity: int = 2,
        on_finished: Callable[[Job, SolveRequest], None] | None = None,
    ):
        self.agent_factory = agent_factory
        self.on_finished = on_finished
        self.executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="crossword")
        self.slots = threading.BoundedSemaphore(capacity)
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}

    def submit(self, request: SolveRequest) -> str:
        if not self.slots.acquire(blocking=False):
            raise CapacityError("Both solver slots are busy. Wait for a run to finish.")
        job = Job(id=uuid.uuid4().hex)
        with self.lock:
            finished = sorted(
                (j for j in self.jobs.values() if j.status not in {"queued", "running"}),
                key=lambda j: j.created_at,
            )
            for old in finished:
                if time.monotonic() - old.created_at > 3600 or len(self.jobs) >= 32:
                    self.jobs.pop(old.id, None)
            self.jobs[job.id] = job
        try:
            self.executor.submit(self._run, job, request)
        except RuntimeError:
            with self.lock:
                self.jobs.pop(job.id, None)
            self.slots.release()
            raise
        return job.id

    def _run(self, job: Job, request: SolveRequest) -> None:
        agent = None
        final_status = "failed"
        try:
            with self.lock:
                job.status = "running"
            agent = self.agent_factory()

            def record(event: AgentEvent) -> None:
                with self.lock:
                    job.events.append(event)

            result = agent.solve(
                request.puzzle, request.options, on_event=record, cancel_event=job.cancel
            )
            with self.lock:
                job.result = result
                final_status = "cancelled" if result.status == "cancelled" else "completed"
        except Exception:
            # Do not send raw provider exceptions, request headers, or keys to the browser/log.
            with self.lock:
                job.error = "The run failed unexpectedly. Check the input and server configuration, then retry."
        finally:
            try:
                if self.on_finished is not None:
                    try:
                        self.on_finished(job, request)
                        with self.lock:
                            job.history_saved = True
                    except Exception:
                        # Keep a usable result even if local persistence fails.
                        with self.lock:
                            job.history_error = (
                                "The run finished, but its local history could not be saved."
                            )
                with self.lock:
                    job.status = final_status
                # A transport cleanup failure must not replace a recorded result.
                with suppress(Exception):
                    if agent and callable(getattr(agent.provider, "close", None)):
                        agent.provider.close()
            finally:
                self.slots.release()

    def snapshot(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs[job_id]
            return {
                "job_id": job.id,
                "status": job.status,
                "events": [event.model_dump() for event in job.events],
                "result": job.result.model_dump() if job.result else None,
                "error": job.error,
                "run_id": job.id if job.history_saved else None,
                "history_error": job.history_error,
            }

    def cancel(self, job_id: str) -> None:
        with self.lock:
            self.jobs[job_id].cancel.set()

    def close(self) -> None:
        with self.lock:
            for job in self.jobs.values():
                job.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=False)
