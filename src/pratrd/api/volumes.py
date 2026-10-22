"""Scan → import → library, plus voxel access for previews/viewports."""

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from ..dicom.scan import Candidate, scan
from ..jobs import Job, JobManager
from ..volumes import store
from ..volumes.importer import import_candidate
from ..volumes.library import Library, LibraryError

router = APIRouter(prefix="/workspaces/{wid}")

_SCAN_KEEP = 8


class ScanCache:
    """Server-side scan results: candidates hold per-frame file lists (can be 10⁵ paths),
    so the UI only ever receives summaries and refers back by (scanId, candidate id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, float, list[Candidate]]] = {}

    def put(self, wid: str, cands: list[Candidate]) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._items[sid] = (wid, time.time(), cands)
            for old in sorted(self._items, key=lambda k: self._items[k][1])[:-_SCAN_KEEP]:
                del self._items[old]
        return sid

    def get(self, wid: str, sid: str) -> list[Candidate]:
        with self._lock:
            item = self._items.get(sid)
        if not item or item[0] != wid:
            raise LibraryError(404, "Wynik skanowania wygasł — zeskanuj ponownie")
        return item[2]


def _ctx(request: Request, wid: str) -> tuple[Path, Library, JobManager]:
    st = request.app.state
    return st.workspaces.existing_dir(wid), st.library, st.jobs


@router.post("/scan")
def start_scan(request: Request, wid: str, body: dict = Body(...)) -> dict:
    ws_dir, library, jobs = _ctx(request, wid)
    paths = [str(p) for p in body.get("paths", []) if p]
    if not paths:
        raise LibraryError(400, "Brak ścieżek do skanowania")
    cache: ScanCache = request.app.state.scans

    def run(job: Job) -> dict[str, Any]:
        cands = scan(paths, lambda p, m: job.report(p, m))
        imported = library.fingerprints(ws_dir)
        return {"scanId": cache.put(wid, cands), "candidates": [c.summary(imported) for c in cands]}

    job = jobs.submit("scan", "Skanowanie", wid, run, lane="io")
    return {"jobId": job.id}


@router.post("/import")
def start_import(request: Request, wid: str, body: dict = Body(...)) -> dict:
    ws_dir, library, jobs = _ctx(request, wid)
    cands = request.app.state.scans.get(wid, str(body.get("scanId", "")))
    wanted = {int(i) for i in body.get("ids", [])}
    anonymize = bool(body.get("anonymize", True))
    root: Path = request.app.state.config.root
    hub = request.app.state.hub
    job_ids = []
    for cand in cands:
        if cand.id not in wanted:
            continue

        def run(job: Job, cand: Candidate = cand) -> dict[str, Any]:
            return import_candidate(job, root, ws_dir, library, cand, anonymize)

        def done(job: Job) -> None:
            if job.state == "done":
                hub.publish({"type": "library", "wid": wid})

        job_ids.append(jobs.submit("import", f"Import: {cand.name}", wid, run, on_done=done).id)
    return {"jobIds": job_ids}


@router.get("/volumes")
def list_volumes(request: Request, wid: str) -> list[dict[str, Any]]:
    ws_dir, library, _ = _ctx(request, wid)
    return library.list(ws_dir)


@router.put("/volumes/{vid}")
def rename_volume(request: Request, wid: str, vid: str, body: dict = Body(...)) -> dict:
    ws_dir, library, _ = _ctx(request, wid)
    return library.rename(ws_dir, vid, str(body.get("name", "")))


@router.delete("/volumes/{vid}")
def delete_volume(request: Request, wid: str, vid: str) -> dict:
    ws_dir, library, _ = _ctx(request, wid)
    library.get(ws_dir, vid)
    library.delete(ws_dir, vid)
    request.app.state.hub.publish({"type": "library", "wid": wid})
    return {"ok": True}


@router.get("/volumes/{vid}/meta")
def volume_meta(request: Request, wid: str, vid: str) -> dict:
    ws_dir, library, _ = _ctx(request, wid)
    path = library.volume_path(ws_dir, vid)
    if not path.is_dir():
        raise LibraryError(404, f"Wolumen '{vid}' nie istnieje")
    return store.read_meta(path)


@router.get("/volumes/{vid}/tags")
def volume_tags(request: Request, wid: str, vid: str) -> Response:
    ws_dir, library, _ = _ctx(request, wid)
    f = library.series_dir(ws_dir, vid) / "tags.json"
    if not f.is_file():
        return Response("[]", media_type="application/json")
    return FileResponse(f, media_type="application/json")


@router.get("/volumes/{vid}/thumb.png")
def volume_thumb(request: Request, wid: str, vid: str) -> Response:
    ws_dir, library, _ = _ctx(request, wid)
    f = library.series_dir(ws_dir, vid) / "thumb.png"
    if not f.is_file():
        return Response(status_code=404)
    # Immutable per vid (a volume is never rewritten in place).
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "max-age=31536000"})


@router.get("/volumes/{vid}/slice")
def volume_slice(
    request: Request,
    wid: str,
    vid: str,
    axis: str = Query("k", pattern="^[ijk]$"),
    index: int = Query(0, ge=-1),
    level: int = Query(0, ge=0),
    fit: int = Query(0, ge=0),
) -> Response:
    """Raw little-endian voxels of one slice; shape/dtype/spacing in the X-Meta header.
    No JSON, no compression: 512² int16 = 512 KB straight from the chunk cache."""
    ws_dir, library, _ = _ctx(request, wid)
    path = library.volume_path(ws_dir, vid)
    if not path.is_dir():
        raise LibraryError(404, f"Wolumen '{vid}' nie istnieje")
    if fit or index < 0:
        # thumbnails: coarsest level whose slice still has an edge ≥ fit; index −1 = middle
        levels = store.read_meta(path)["levels"]
        a = "ijk".index(axis)
        if fit:
            level = 0
            for L, g in enumerate(levels):
                if max(n for d, n in enumerate(g["size"]) if d != a) >= fit:
                    level = L
        level = min(level, len(levels) - 1)
        if index < 0:
            index = levels[level]["size"][a] // 2
    arr = store.read_slice(path, level, axis, index)
    le = arr.astype(arr.dtype.newbyteorder("<"), copy=False)
    meta = {
        "shape": list(le.shape),
        "dtype": le.dtype.name,
        "axis": axis,
        "index": index,
        "level": level,
    }
    return Response(
        content=np.ascontiguousarray(le).tobytes(),
        media_type="application/octet-stream",
        headers={"X-Meta": json.dumps(meta)},
    )


@router.get("/volumes/{vid}/level/{level}")
def volume_level(request: Request, wid: str, vid: str, level: int) -> StreamingResponse:
    """A whole pyramid level as raw little-endian [k, j, i] voxels (for GPU upload).
    Streamed chunk layer by chunk layer; Content-Length lets the client show progress and
    preallocate one buffer instead of growing one."""
    ws_dir, library, _ = _ctx(request, wid)
    path = library.volume_path(ws_dir, vid)
    if not (path / str(level)).is_dir():
        raise LibraryError(404, f"Brak poziomu {level} wolumenu '{vid}'")
    meta, total, gen = store.iter_level_bytes(path, level)
    return StreamingResponse(
        gen,
        media_type="application/octet-stream",
        headers={"X-Meta": json.dumps(meta), "Content-Length": str(total)},
    )
