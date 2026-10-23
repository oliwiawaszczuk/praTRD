import threading
from typing import Any

from fastapi import APIRouter, Body, Request

from ..graph import types as gtypes
from ..graph.evaluator import Evaluator
from ..jobs import Job
from ..jsonio import read_json

router = APIRouter()

_CACHE_BUDGET_DEFAULT = 20 << 30


@router.get("/node-types")
def node_types() -> dict[str, Any]:
    return gtypes.schema()


def _ws(request: Request, wid: str):  # noqa: ANN202
    return request.app.state.workspaces.existing_dir(wid)


@router.get("/workspaces/{wid}/graphs")
def list_graphs(request: Request, wid: str) -> list[dict]:
    return request.app.state.graphs.list(_ws(request, wid))


@router.post("/workspaces/{wid}/graphs")
def create_graph(request: Request, wid: str, body: dict = Body(default={})) -> dict:
    return request.app.state.graphs.create(_ws(request, wid), str(body.get("name", "")))


@router.put("/workspaces/{wid}/graphs/{gid}")
def rename_graph(request: Request, wid: str, gid: str, body: dict = Body(...)) -> dict:
    return request.app.state.graphs.rename(_ws(request, wid), gid, str(body.get("name", "")))


@router.delete("/workspaces/{wid}/graphs/{gid}")
def delete_graph(request: Request, wid: str, gid: str) -> dict:
    request.app.state.graphs.delete(_ws(request, wid), gid)
    return {"ok": True}


@router.get("/workspaces/{wid}/graphs/{gid}/doc")
def get_graph(request: Request, wid: str, gid: str) -> dict:
    return request.app.state.graphs.get(_ws(request, wid), gid)


@router.put("/workspaces/{wid}/graphs/{gid}/doc")
def put_graph(request: Request, wid: str, gid: str, body: dict = Body(...)) -> dict:
    request.app.state.graphs.put(_ws(request, wid), gid, body)
    return {"ok": True}


_CACHE_BUDGET_MIN = 1 << 30


def cache_budget(settings: dict[str, Any]) -> int:
    """Cache budget from the app settings. A missing, broken or tiny value (e.g. 0 from a
    32-bit overflow in an old front) falls back to the default instead of emptying the
    cache after every evaluation."""
    try:
        b = int(settings.get("cacheBytes", _CACHE_BUDGET_DEFAULT))
    except (TypeError, ValueError):
        return _CACHE_BUDGET_DEFAULT
    return b if b >= _CACHE_BUDGET_MIN else _CACHE_BUDGET_DEFAULT


_evaluators: dict[str, Evaluator] = {}
_running: dict[tuple[str, str, str], Job] = {}
_lock = threading.Lock()


@router.post("/workspaces/{wid}/graphs/{gid}/evaluate")
def evaluate(request: Request, wid: str, gid: str, body: dict = Body(...)) -> dict:
    """Evaluate the posted graph state (not the saved file — no save/eval race). A newer
    request for the same graph and quality cancels the running one."""
    st = request.app.state
    ws_dir = _ws(request, wid)
    st.graphs.check(gid)
    quality = "full" if body.get("quality") == "full" else "preview"
    graph = body.get("graph") or {}
    targets = [str(t) for t in body.get("targets", [])]
    with _lock:
        ev = _evaluators.get(wid)
        if ev is None or ev.ws_dir != ws_dir:
            ev = _evaluators[wid] = Evaluator(wid, ws_dir, st.library, st.hub)
        prev = _running.get((wid, gid, quality))
    if prev is not None:
        st.jobs.cancel(prev.id)

    budget = cache_budget(read_json(st.config.app_settings_file, {}))

    def run(job: Job) -> dict[str, Any]:
        res = ev.evaluate(job, gid, graph, targets, quality)  # type: ignore[arg-type]
        ev.prune(budget)
        return res

    title = "Graf — pełna rozdzielczość" if quality == "full" else "Graf — podgląd"
    job = st.jobs.submit("graph", title, wid, run, lane="graph")
    with _lock:
        _running[(wid, gid, quality)] = job
    return {"jobId": job.id}
