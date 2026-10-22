from pathlib import Path

from fastapi import APIRouter, Body, Request

from ..workspaces import WorkspaceStore

router = APIRouter(prefix="/workspaces")


def _store(request: Request) -> WorkspaceStore:
    return request.app.state.workspaces


@router.get("")
def list_workspaces(request: Request) -> dict:
    return _store(request).list()


@router.post("")
def create_workspace(request: Request, body: dict = Body(default={})) -> dict:
    return _store(request).create(body.get("name"))


@router.post("/import")
def import_workspace(request: Request, body: dict = Body(...)) -> dict:
    return _store(request).import_(Path(body["src_dir"]))


@router.put("/{wid}")
def rename_workspace(request: Request, wid: str, body: dict = Body(...)) -> dict:
    return _store(request).rename(wid, body.get("name"))


@router.delete("/{wid}")
def delete_workspace(request: Request, wid: str) -> dict:
    _store(request).delete(wid)
    return {"ok": True}


@router.post("/{wid}/activate")
def activate_workspace(request: Request, wid: str) -> dict:
    _store(request).activate(wid)
    return {"ok": True, "active_id": wid}


@router.get("/{wid}/settings")
def get_settings(request: Request, wid: str) -> dict:
    return _store(request).get_settings(wid)


@router.put("/{wid}/settings")
def put_settings(request: Request, wid: str, body: dict = Body(...)) -> dict:
    _store(request).put_settings(wid, body)
    return {"ok": True}


@router.post("/{wid}/export")
def export_workspace(request: Request, wid: str, body: dict = Body(...)) -> dict:
    out = _store(request).export(wid, Path(body["dest_dir"]))
    return {"ok": True, "path": str(out)}
