"""Thread-safe fan-out of JSON events to every connected WebSocket client.

Jobs run in worker threads; WebSocket handlers live on the asyncio loop. publish() may be
called from any thread and hops onto the loop with call_soon_threadsafe.
"""

import asyncio
import threading
from typing import Any

# A client that stops reading must not grow memory without bound: when its queue is full
# the oldest messages are dropped (progress events are superseded by newer ones anyway).
_QUEUE_MAX = 512


class EventHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(_QUEUE_MAX)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._queues.discard(q)

    def publish(self, msg: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            queues = tuple(self._queues)
        if queues:
            loop.call_soon_threadsafe(_deliver, queues, msg)


def _deliver(queues: tuple[asyncio.Queue[dict[str, Any]], ...], msg: dict[str, Any]) -> None:
    for q in queues:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(msg)
