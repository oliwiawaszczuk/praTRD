import asyncio

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.get("/jobs")
def list_jobs(request: Request) -> list[dict]:
    return request.app.state.jobs.list()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict:
    return {"ok": request.app.state.jobs.cancel(job_id)}


@router.websocket("/ws")
async def events(ws: WebSocket) -> None:
    """Live events: {"type": "job", "job": …} and {"type": "library", "wid": …}.
    On connect the client gets a snapshot of all known jobs."""
    await ws.accept()
    hub = ws.app.state.hub
    q = hub.subscribe()
    recv: asyncio.Future | None = None
    try:
        await ws.send_json({"type": "snapshot", "jobs": ws.app.state.jobs.list()})
        recv = asyncio.ensure_future(ws.receive_text())  # only to notice disconnects
        while True:
            get = asyncio.ensure_future(q.get())
            done, _ = await asyncio.wait({get, recv}, return_when=asyncio.FIRST_COMPLETED)
            if recv in done:
                get.cancel()
                break
            await ws.send_json(get.result())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(q)
        # Consume the receive task's outcome (normally WebSocketDisconnect) so asyncio
        # does not log "Task exception was never retrieved" on every closed client.
        if recv is not None:
            if not recv.done():
                recv.cancel()
            elif not recv.cancelled():
                recv.exception()
