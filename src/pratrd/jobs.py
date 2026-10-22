"""Background jobs with progress, cooperative cancellation and live events.

Two single-worker lanes: `io` (folder scans — quick, must not queue behind imports) and
`heavy` (imports — each one already saturates the CPU through the decode pool, so running
two at once would only thrash RAM and disk) and `graph` (node-graph evaluation).
"""

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from .events import EventHub

JobState = Literal["queued", "running", "done", "error", "cancelled"]
Lane = Literal["io", "heavy", "graph"]

_PUBLISH_INTERVAL_S = 0.1  # progress events per job are throttled to ≤ 10/s
_KEEP_FINISHED = 50


class Cancelled(Exception):
    """Raised inside a job function by Job.check() once cancel was requested."""


@dataclass(eq=False)
class Job:
    id: str
    kind: str
    title: str
    wid: str
    state: JobState = "queued"
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str = ""
    created: float = field(default_factory=time.time)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _hub: EventHub | None = field(default=None, repr=False)
    _last_pub: float = field(default=0.0, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "wid": self.wid,
            "state": self.state,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result if self.state == "done" else None,
            "error": self.error,
            "created": self.created,
        }

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled

    def report(self, progress: float, message: str | None = None) -> None:
        """Update progress (0..1). Cheap to call per slice: publishing is throttled."""
        self.progress = min(max(progress, 0.0), 1.0)
        if message is not None:
            self.message = message
        now = time.monotonic()
        if now - self._last_pub >= _PUBLISH_INTERVAL_S:
            self._last_pub = now
            self._publish()
        self.check()

    def _publish(self) -> None:
        if self._hub:
            self._hub.publish({"type": "job", "job": self.to_json()})


class JobManager:
    def __init__(self, hub: EventHub) -> None:
        self._hub = hub
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._lanes: dict[Lane, ThreadPoolExecutor] = {
            "io": ThreadPoolExecutor(1, thread_name_prefix="job-io"),
            "heavy": ThreadPoolExecutor(1, thread_name_prefix="job-heavy"),
            # node-graph evaluation must never wait behind a long import
            "graph": ThreadPoolExecutor(1, thread_name_prefix="job-graph"),
        }

    def submit(
        self,
        kind: str,
        title: str,
        wid: str,
        fn: Callable[[Job], Any],
        lane: Lane = "heavy",
        on_done: Callable[[Job], None] | None = None,
    ) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, wid=wid, _hub=self._hub)
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        job._publish()
        self._lanes[lane].submit(self._run, job, fn, on_done)
        return job

    def _run(
        self, job: Job, fn: Callable[[Job], Any], on_done: Callable[[Job], None] | None
    ) -> None:
        if job.cancelled:
            job.state = "cancelled"
            job._publish()
            return
        job.state = "running"
        job._publish()
        try:
            job.result = fn(job)
            job.state = "done"
            job.progress = 1.0
        except Cancelled:
            job.state = "cancelled"
        except Exception as e:  # noqa: BLE001 — surface any failure to the UI
            job.state = "error"
            job.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        job._publish()
        if on_done:
            try:
                on_done(job)
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.state in ("done", "error", "cancelled"):
            return False
        job._cancel.set()
        job.message = "Anulowanie…"
        job._publish()
        return True

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [j.to_json() for j in self._jobs.values()]

    def _prune(self) -> None:
        finished = sorted(
            (j for j in self._jobs.values() if j.state in ("done", "error", "cancelled")),
            key=lambda j: j.created,
        )
        for j in finished[: max(0, len(finished) - _KEEP_FINISHED)]:
            del self._jobs[j.id]

    def shutdown(self) -> None:
        for j in list(self._jobs.values()):
            j._cancel.set()
        for ex in self._lanes.values():
            ex.shutdown(wait=False, cancel_futures=True)
