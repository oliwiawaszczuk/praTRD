"""Workspace registry and on-disk layout.

workspaces/
  registry.json            {"active_id": str, "workspaces": [WorkspaceMeta, ...]}
  <wid>/
    workspace.json         WorkspaceMeta + format version (lets import validate a folder)
    settings.json          free-form UI state written by the front (wsGet/wsSet)
    series/ store/ nodegraphs/   filled by later stages
    cache/                 regenerable node results — never exported

FastAPI runs sync endpoints in a thread pool, so every registry read-modify-write is
serialized by one lock.
"""

import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_json

FORMAT_VERSION = 1
DEFAULT_NAME = "Nowy workspace"
EXPORT_PREFIX = "praTRD_workspace_"
SUBDIRS = ("series", "store", "cache", "nodegraphs")
NON_EXPORTED = ("cache",)

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class WorkspaceError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean_name(name: Any) -> str:
    return (str(name).strip() if name else "") or DEFAULT_NAME


class WorkspaceStore:
    def __init__(self, base: Path):
        self.base = base
        self._registry_file = base / "registry.json"
        self._lock = threading.Lock()

    # ── internals (call with lock held) ──────────────────────────────────────
    def _load(self) -> dict:
        reg = read_json(self._registry_file, None)
        if not isinstance(reg, dict) or not isinstance(reg.get("workspaces"), list):
            reg = {"active_id": "", "workspaces": []}
        return reg

    def _save(self, reg: dict) -> None:
        write_json(self._registry_file, reg)

    def _find(self, reg: dict, wid: str) -> dict:
        if _ID_RE.match(wid):
            for ws in reg["workspaces"]:
                if ws["id"] == wid:
                    return ws
        raise WorkspaceError(404, f"Workspace '{wid}' nie istnieje")

    def _init_dir(self, meta: dict) -> None:
        d = self.dir(meta["id"])
        for sub in SUBDIRS:
            (d / sub).mkdir(parents=True, exist_ok=True)
        write_json(d / "workspace.json", {**meta, "formatVersion": FORMAT_VERSION})

    def _new(self, reg: dict, name: str) -> dict:
        now = _now()
        meta = {"id": uuid.uuid4().hex[:12], "name": name, "createdAt": now, "updatedAt": now}
        self._init_dir(meta)
        reg["workspaces"].append(meta)
        return meta

    # ── public API ───────────────────────────────────────────────────────────
    def dir(self, wid: str) -> Path:
        if not _ID_RE.match(wid):
            raise WorkspaceError(404, f"Workspace '{wid}' nie istnieje")
        return self.base / wid

    def existing_dir(self, wid: str) -> Path:
        """Directory of a registered workspace (404 otherwise)."""
        with self._lock:
            self._find(self._load(), wid)
        return self.dir(wid)

    def list(self) -> dict:
        """Registry; guarantees at least one workspace and a valid active id."""
        with self._lock:
            reg = self._load()
            dirty = False
            if not reg["workspaces"]:
                self._new(reg, "Workspace 1")
                dirty = True
            ids = {w["id"] for w in reg["workspaces"]}
            if reg["active_id"] not in ids:
                reg["active_id"] = reg["workspaces"][0]["id"]
                dirty = True
            if dirty:
                self._save(reg)
            return reg

    def create(self, name: Any) -> dict:
        with self._lock:
            reg = self._load()
            meta = self._new(reg, _clean_name(name))
            self._save(reg)
            return meta

    def rename(self, wid: str, name: Any) -> dict:
        with self._lock:
            reg = self._load()
            ws = self._find(reg, wid)
            ws["name"] = _clean_name(name)
            ws["updatedAt"] = _now()
            self._save(reg)
            write_json(self.dir(wid) / "workspace.json", {**ws, "formatVersion": FORMAT_VERSION})
            return ws

    def delete(self, wid: str) -> None:
        with self._lock:
            reg = self._load()
            self._find(reg, wid)
            if len(reg["workspaces"]) <= 1:
                raise WorkspaceError(400, "Nie można usunąć jedynego workspace'u")
            reg["workspaces"] = [w for w in reg["workspaces"] if w["id"] != wid]
            if reg["active_id"] == wid:
                reg["active_id"] = reg["workspaces"][0]["id"]
            self._save(reg)
        shutil.rmtree(self.dir(wid), ignore_errors=True)

    def activate(self, wid: str) -> None:
        with self._lock:
            reg = self._load()
            self._find(reg, wid)
            reg["active_id"] = wid
            self._save(reg)

    def get_settings(self, wid: str) -> dict:
        with self._lock:
            self._find(self._load(), wid)
        data = read_json(self.dir(wid) / "settings.json", {})
        return data if isinstance(data, dict) else {}

    def put_settings(self, wid: str, settings: dict) -> None:
        # Settings are written ~every 500 ms while the user works: deliberately no
        # registry rewrite here (updatedAt is bumped only on structural changes).
        with self._lock:
            self._find(self._load(), wid)
        write_json(self.dir(wid) / "settings.json", settings)

    def export(self, wid: str, dest_dir: Path) -> Path:
        with self._lock:
            ws = self._find(self._load(), wid)
        if not dest_dir.is_dir():
            raise WorkspaceError(404, f"Brak folderu docelowego: {dest_dir}")
        safe = re.sub(r"[^\w\- ]", "_", ws["name"]).strip() or wid
        out = dest_dir / f"{EXPORT_PREFIX}{safe}"
        if out.exists():
            raise WorkspaceError(409, f"'{out}' już istnieje")
        shutil.copytree(self.dir(wid), out, ignore=shutil.ignore_patterns(*NON_EXPORTED))
        return out

    def import_(self, src_dir: Path) -> dict:
        meta_file = src_dir / "workspace.json"
        src_meta = read_json(meta_file, None)
        if not isinstance(src_meta, dict):
            raise WorkspaceError(400, f"'{src_dir}' nie jest folderem workspace'u praTRD")
        if src_meta.get("formatVersion", 0) > FORMAT_VERSION:
            raise WorkspaceError(400, "Workspace z nowszej wersji praTRD")
        now = _now()
        name = _clean_name(src_meta.get("name") or src_dir.name.removeprefix(EXPORT_PREFIX))
        meta = {"id": uuid.uuid4().hex[:12], "name": name, "createdAt": now, "updatedAt": now}
        # Copy outside the lock (may be GBs of store data); register only when complete.
        shutil.copytree(src_dir, self.dir(meta["id"]), ignore=shutil.ignore_patterns(*NON_EXPORTED))
        self._init_dir(meta)
        with self._lock:
            reg = self._load()
            reg["workspaces"].append(meta)
            self._save(reg)
        return meta
