"""Meshes: workspace library (imported files), binary geometry for the viewports, thumbnails
and export. `{ref}` is a library mesh (12 hex) or a node result (24 hex), like volumes."""

import json
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..meshes import io
from ..meshes import store as mesh_store
from ..volumes.library import LibraryError

router = APIRouter(prefix="/workspaces/{wid}/meshes")

_CHUNK = 1 << 20


def _ws(request: Request, wid: str) -> Path:
    return request.app.state.workspaces.existing_dir(wid)


def _path(ws_dir: Path, ref: str) -> Path:
    try:
        p = mesh_store.mesh_path(ws_dir, ref)
    except mesh_store.MeshNotFound:
        p = None
    if p is None or not p.is_dir():
        raise LibraryError(404, f"Mesh '{ref}' nie istnieje")
    return p


@router.get("")
def list_meshes(request: Request, wid: str) -> list[dict]:
    return request.app.state.meshes.list(_ws(request, wid))


@router.post("/import")
def import_meshes(request: Request, wid: str, body: dict = Body(...)) -> dict:
    """STL / OBJ / PLY files → library. Per-file errors are reported, not fatal."""
    ws_dir = _ws(request, wid)
    added, errors = [], []
    for p in [str(x) for x in body.get("paths", [])]:
        try:
            added.append(request.app.state.meshes.import_file(ws_dir, p))
        except LibraryError as e:
            errors.append({"path": p, "error": e.detail})
    if added:
        request.app.state.hub.publish({"type": "meshes-changed", "wid": wid})
    return {"added": added, "errors": errors}


@router.put("/{mid}")
def rename_mesh(request: Request, wid: str, mid: str, body: dict = Body(...)) -> dict:
    entry = request.app.state.meshes.rename(_ws(request, wid), mid, str(body.get("name", "")))
    request.app.state.hub.publish({"type": "meshes-changed", "wid": wid})
    return entry


@router.delete("/{mid}")
def delete_mesh(request: Request, wid: str, mid: str) -> dict:
    request.app.state.meshes.delete(_ws(request, wid), mid)
    request.app.state.hub.publish({"type": "meshes-changed", "wid": wid})
    return {"ok": True}


@router.get("/{ref}/data")
def mesh_data(request: Request, wid: str, ref: str) -> StreamingResponse:
    """verts f32 [N,3] | normals f32 [N,3] | cells u32 [M,4] (3, a, b, c), little-endian,
    straight from the files (vtk.js takes the cell layout as is). Counts in X-Meta. Meshes
    above DISPLAY_FACES come decimated (made once, kept next to the mesh)."""
    full = _path(_ws(request, wid), ref)
    p = mesh_store.display_path(full)
    meta = mesh_store.read_meta(p)
    files = mesh_store.byte_files(p)
    total = sum(f.stat().st_size for f in files)

    def gen():  # noqa: ANN202
        for f in files:
            with f.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    yield chunk

    head = {
        "verts": meta["verts"],
        "faces": meta["faces"],
        "bounds": meta["stats"]["bounds"],
        "lod": p != full,
    }
    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={"X-Meta": json.dumps(head), "Content-Length": str(total)},
    )


@router.get("/{ref}/thumb.png")
def mesh_thumb(request: Request, wid: str, ref: str) -> FileResponse:
    f = mesh_store.thumbnail(_path(_ws(request, wid), ref))
    # immutable per ref (a mesh directory is never rewritten)
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "max-age=31536000"})


@router.post("/{ref}/export")
def export_mesh(request: Request, wid: str, ref: str, body: dict = Body(...)) -> dict:
    """Write STL (binary) / OBJ / PLY (binary) to a path chosen in the native Save dialog."""
    p = _path(_ws(request, wid), ref)
    out = Path(str(body.get("path", "")))
    space = "RAS" if body.get("space") == "RAS" else "LPS"
    if not out.is_absolute() or not io.is_mesh_file(out):
        raise LibraryError(400, "Oczekiwano bezwzględnej ścieżki do pliku .stl, .obj lub .ply")
    if not out.parent.is_dir():
        raise LibraryError(400, "Folder nie istnieje")
    v, f = mesh_store.MESHES.get(p)
    io.write_mesh_file(out, v, f, space)
    return {"path": str(out), "bytes": out.stat().st_size}
