"""Graphs of a workspace: nodegraphs/registry.json + nodegraphs/<gid>.json (praSzczur layout)."""

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..jsonio import read_json, write_json
from ..volumes.library import LibraryError

_GID_RE = re.compile(r"^[0-9a-f]{10}$")
EMPTY_DOC = {"nodes": [], "edges": [], "view": {"x": 0, "y": 0, "zoom": 1}}


class GraphStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _dir(ws_dir: Path) -> Path:
        return ws_dir / "nodegraphs"

    def _reg(self, ws_dir: Path) -> list[dict[str, Any]]:
        reg = read_json(self._dir(ws_dir) / "registry.json", [])
        return reg if isinstance(reg, list) else []

    @staticmethod
    def check(gid: str) -> str:
        if not _GID_RE.match(gid):
            raise LibraryError(404, f"Graf '{gid}' nie istnieje")
        return gid

    def list(self, ws_dir: Path) -> list[dict[str, Any]]:
        with self._lock:
            reg = self._reg(ws_dir)
            if not reg:
                reg = [self._new(ws_dir, "Graf 1")]
                write_json(self._dir(ws_dir) / "registry.json", reg)
            return reg

    def _new(self, ws_dir: Path, name: str) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta = {"id": uuid.uuid4().hex[:10], "name": name, "createdAt": now, "updatedAt": now}
        write_json(self._dir(ws_dir) / f"{meta['id']}.json", EMPTY_DOC)
        return meta

    def create(self, ws_dir: Path, name: str) -> dict[str, Any]:
        with self._lock:
            reg = self._reg(ws_dir)
            meta = self._new(ws_dir, (name or "").strip() or f"Graf {len(reg) + 1}")
            reg.append(meta)
            write_json(self._dir(ws_dir) / "registry.json", reg)
            return meta

    def rename(self, ws_dir: Path, gid: str, name: str) -> dict[str, Any]:
        self.check(gid)
        with self._lock:
            reg = self._reg(ws_dir)
            for g in reg:
                if g["id"] == gid:
                    g["name"] = (name or "").strip() or g["name"]
                    write_json(self._dir(ws_dir) / "registry.json", reg)
                    return g
        raise LibraryError(404, f"Graf '{gid}' nie istnieje")

    def delete(self, ws_dir: Path, gid: str) -> None:
        self.check(gid)
        with self._lock:
            reg = self._reg(ws_dir)
            if len(reg) <= 1:
                raise LibraryError(400, "Nie można usunąć jedynego grafu")
            write_json(self._dir(ws_dir) / "registry.json", [g for g in reg if g["id"] != gid])
        (self._dir(ws_dir) / f"{gid}.json").unlink(missing_ok=True)

    def get(self, ws_dir: Path, gid: str) -> dict[str, Any]:
        self.check(gid)
        doc = read_json(self._dir(ws_dir) / f"{gid}.json", None)
        if not isinstance(doc, dict):
            raise LibraryError(404, f"Graf '{gid}' nie istnieje")
        return doc

    def put(self, ws_dir: Path, gid: str, doc: dict[str, Any]) -> None:
        self.check(gid)
        if not (self._dir(ws_dir) / f"{gid}.json").exists():
            raise LibraryError(404, f"Graf '{gid}' nie istnieje")
        write_json(self._dir(ws_dir) / f"{gid}.json", doc)
