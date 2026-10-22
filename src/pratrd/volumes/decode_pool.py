"""Shared process pool for CPU-bound decoding.

* created lazily on first use (spawn context — identical on macOS/Windows/Linux and in the
  frozen PyInstaller build, which calls multiprocessing.freeze_support());
* reused across imports (start-up ≈ 0.17 s, paid once);
* shut down after IDLE_S without work: every worker holds numpy + pydicom (~60 MB).
"""

import multiprocessing as mp
import os
import threading
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any

IDLE_S = 90.0
_MAX_WORKERS = 6

_lock = threading.Lock()
_pool: ProcessPoolExecutor | None = None
_users = 0
_timer: threading.Timer | None = None


def workers() -> int:
    return max(2, min(_MAX_WORKERS, (os.cpu_count() or 4) - 2))


def _shutdown_if_idle() -> None:
    global _pool
    with _lock:
        if _users == 0 and _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


class _Lease:
    def __enter__(self) -> ProcessPoolExecutor:
        global _pool, _users, _timer
        with _lock:
            if _timer:
                _timer.cancel()
                _timer = None
            if _pool is None:
                _pool = ProcessPoolExecutor(workers(), mp_context=mp.get_context("spawn"))
            _users += 1
            return _pool

    def __exit__(self, *exc: object) -> None:
        global _users, _timer
        with _lock:
            _users -= 1
            if _users == 0:
                _timer = threading.Timer(IDLE_S, _shutdown_if_idle)
                _timer.daemon = True
                _timer.start()


def ordered_map(
    fn: Callable[..., Any],
    batches: Sequence[tuple[Any, ...]],
    in_flight: int,
    on_result: Callable[[int, Any], None],
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Run fn(*batch) in the pool with at most `in_flight` batches pending, delivering
    results to on_result strictly in order. Bounded memory however many batches there are;
    stops submitting (and drops pending work) as soon as should_stop() is true."""
    with _Lease() as pool:
        pending: deque[Future[Any]] = deque()
        it: Iterator[tuple[Any, ...]] = iter(batches)
        n_done = 0
        try:
            for batch in it:
                pending.append(pool.submit(fn, *batch))
                if len(pending) >= in_flight:
                    if should_stop():
                        return
                    on_result(n_done, pending.popleft().result())
                    n_done += 1
            while pending:
                if should_stop():
                    return
                on_result(n_done, pending.popleft().result())
                n_done += 1
        finally:
            for f in pending:
                f.cancel()
