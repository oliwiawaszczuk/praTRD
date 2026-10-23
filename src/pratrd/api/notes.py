"""Notes (zakładka Notatki + pływający notatnik) — global, independent of workspaces:
notes/registry.json (list with title + preview) and notes/<id>.json (text)."""

import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request

from ..jsonio import read_json, write_json

router = APIRouter(prefix="/notes")
_lock = threading.Lock()
_ID = re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dir(request: Request) -> Path:
    return request.app.state.config.notes_dir


def _registry(d: Path) -> dict:
    reg = read_json(d / "registry.json", {"notes": []})
    return reg if isinstance(reg, dict) and isinstance(reg.get("notes"), list) else {"notes": []}


def _find(reg: dict, nid: str) -> dict:
    if not _ID.match(nid):
        raise HTTPException(400, "Nieprawidłowy identyfikator")
    n = next((x for x in reg["notes"] if x["id"] == nid), None)
    if n is None:
        raise HTTPException(404, "Notatka nie istnieje")
    return n


def _title_from(text: str, fallback: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first.lstrip("#").strip()[:80] if first else fallback


@router.get("")
def list_notes(request: Request) -> dict:
    return {"notes": _registry(_dir(request))["notes"]}


@router.post("")
def create_note(request: Request, body: dict = Body(default={})) -> dict:
    d = _dir(request)
    title = str(body.get("title") or "Nowa notatka").strip() or "Nowa notatka"
    now = _now()
    n = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "titleManual": False,
        "preview": "",
        "createdAt": now,
        "updatedAt": now,
    }
    with _lock:
        reg = _registry(d)
        reg["notes"].append(n)
        write_json(d / f"{n['id']}.json", {"text": ""})
        write_json(d / "registry.json", reg)
    return n


@router.put("/{nid}")
def rename_note(request: Request, nid: str, body: dict = Body(...)) -> dict:
    d = _dir(request)
    with _lock:
        reg = _registry(d)
        n = _find(reg, nid)
        title = str(body.get("title") or "").strip()
        if title:
            n["title"] = title[:120]
            n["titleManual"] = True
        n["updatedAt"] = _now()
        write_json(d / "registry.json", reg)
    return n


@router.delete("/{nid}")
def delete_note(request: Request, nid: str) -> dict:
    d = _dir(request)
    with _lock:
        reg = _registry(d)
        _find(reg, nid)
        reg["notes"] = [x for x in reg["notes"] if x["id"] != nid]
        write_json(d / "registry.json", reg)
        (d / f"{nid}.json").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/{nid}/data")
def get_note(request: Request, nid: str) -> dict:
    d = _dir(request)
    _find(_registry(d), nid)
    data = read_json(d / f"{nid}.json", {"text": ""})
    return {"text": str(data.get("text", "")) if isinstance(data, dict) else ""}


@router.put("/{nid}/data")
def save_note(request: Request, nid: str, body: dict = Body(...)) -> dict:
    d = _dir(request)
    text = str(body.get("text", ""))
    with _lock:
        reg = _registry(d)
        n = _find(reg, nid)
        write_json(d / f"{nid}.json", {"text": text})
        # the title follows the first non-empty line until the user renames the note;
        # the preview is kept here so the list never needs N extra requests
        if not n.get("titleManual"):
            n["title"] = _title_from(text, n["title"])
        n["preview"] = text.strip()[:300]
        n["updatedAt"] = _now()
        write_json(d / "registry.json", reg)
    return {"ok": True, "title": n["title"]}
