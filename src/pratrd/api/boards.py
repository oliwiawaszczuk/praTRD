"""Whiteboards (zakładka Tablica) — global, independent of workspaces:
boards/registry.json, boards/<id>/board.json (objects + viewport), boards/<id>/assets/*
(images: uploaded, pasted, dropped, or viewport screenshots)."""

import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from ..jsonio import read_json, write_json

router = APIRouter(prefix="/boards")
_lock = threading.Lock()
_ID = re.compile(r"^[0-9a-f]{12}$")
_ASSET = re.compile(r"^[0-9a-f]{16}\.(png|jpg|jpeg|gif|webp|bmp)$")
_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_MAX_ASSET = 64 << 20
_EMPTY = {"objects": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dir(request: Request) -> Path:
    return request.app.state.config.boards_dir


def _registry(d: Path) -> dict:
    reg = read_json(d / "registry.json", {"boards": []})
    return reg if isinstance(reg, dict) and isinstance(reg.get("boards"), list) else {"boards": []}


def _find(reg: dict, bid: str) -> dict:
    if not _ID.match(bid):
        raise HTTPException(400, "Nieprawidłowy identyfikator")
    b = next((x for x in reg["boards"] if x["id"] == bid), None)
    if b is None:
        raise HTTPException(404, "Tablica nie istnieje")
    return b


def _touch(d: Path, bid: str) -> None:
    with _lock:
        reg = _registry(d)
        _find(reg, bid)["updatedAt"] = _now()
        write_json(d / "registry.json", reg)


@router.get("")
def list_boards(request: Request) -> dict:
    return {"boards": _registry(_dir(request))["boards"]}


@router.post("")
def create_board(request: Request, body: dict = Body(default={})) -> dict:
    d = _dir(request)
    name = str(body.get("name") or "Nowa tablica").strip() or "Nowa tablica"
    now = _now()
    b = {"id": uuid.uuid4().hex[:12], "name": name[:120], "createdAt": now, "updatedAt": now}
    with _lock:
        reg = _registry(d)
        reg["boards"].append(b)
        (d / b["id"] / "assets").mkdir(parents=True, exist_ok=True)
        write_json(d / b["id"] / "board.json", _EMPTY)
        write_json(d / "registry.json", reg)
    return b


@router.put("/{bid}")
def rename_board(request: Request, bid: str, body: dict = Body(...)) -> dict:
    d = _dir(request)
    with _lock:
        reg = _registry(d)
        b = _find(reg, bid)
        name = str(body.get("name") or "").strip()
        if name:
            b["name"] = name[:120]
        b["updatedAt"] = _now()
        write_json(d / "registry.json", reg)
    return b


@router.delete("/{bid}")
def delete_board(request: Request, bid: str) -> dict:
    d = _dir(request)
    with _lock:
        reg = _registry(d)
        _find(reg, bid)
        reg["boards"] = [x for x in reg["boards"] if x["id"] != bid]
        write_json(d / "registry.json", reg)
    shutil.rmtree(d / bid, ignore_errors=True)
    return {"ok": True}


@router.get("/{bid}/data")
def get_board(request: Request, bid: str) -> dict:
    d = _dir(request)
    _find(_registry(d), bid)
    data = read_json(d / bid / "board.json", None)
    return data if isinstance(data, dict) else dict(_EMPTY)


@router.put("/{bid}/data")
def save_board(request: Request, bid: str, body: dict = Body(...)) -> dict:
    d = _dir(request)
    _find(_registry(d), bid)
    write_json(d / bid / "board.json", body)
    _touch(d, bid)
    return {"ok": True}


def _store_asset(d: Path, bid: str, data: bytes, ext: str) -> dict:
    ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
    if ext not in _EXTS:
        raise HTTPException(400, f"Niedozwolony format obrazu: {ext}")
    if not data or len(data) > _MAX_ASSET:
        raise HTTPException(400, "Pusty albo zbyt duży plik")
    name = f"{uuid.uuid4().hex[:16]}{ext}"
    (d / bid / "assets").mkdir(parents=True, exist_ok=True)
    (d / bid / "assets" / name).write_bytes(data)
    return {"filename": name, "url": f"/boards/{bid}/assets/{name}"}


@router.post("/{bid}/assets")
async def upload_asset(request: Request, bid: str, ext: str = "png") -> dict:
    """Raw image bytes in the body (no multipart: pasted / captured blobs)."""
    d = _dir(request)
    _find(_registry(d), bid)
    return _store_asset(d, bid, await request.body(), ext)


@router.post("/{bid}/assets/from-path")
def asset_from_path(request: Request, bid: str, body: dict = Body(...)) -> dict:
    """An image file dropped onto the window (the webview only knows its path)."""
    d = _dir(request)
    _find(_registry(d), bid)
    p = Path(str(body.get("path", "")))
    if not p.is_absolute() or not p.is_file():
        raise HTTPException(400, "Plik nie istnieje")
    if p.stat().st_size > _MAX_ASSET:
        raise HTTPException(400, "Zbyt duży plik")
    return _store_asset(d, bid, p.read_bytes(), p.suffix)


@router.get("/{bid}/assets/{name}")
def get_asset(request: Request, bid: str, name: str) -> FileResponse:
    if not _ID.match(bid) or not _ASSET.match(name):
        raise HTTPException(404, "Brak pliku")
    p = _dir(request) / bid / "assets" / name
    if not p.is_file():
        raise HTTPException(404, "Brak pliku")
    # assets are write-once (new name per upload)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})
