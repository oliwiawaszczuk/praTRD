"""Per-workspace volume library.

workspaces/<wid>/series/index.json   [entry, …] — light summaries for listing
workspaces/<wid>/series/<vid>/       tags.json, thumb.png
workspaces/<wid>/store/<vid>.zarr    voxels + full metadata (group attrs "pratrd")
"""

import re
import shutil
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..jsonio import read_json, write_json
from . import store

_VID_RE = re.compile(r"^[0-9a-f]{12}$")
# Node-graph results live in cache/<24 hex>.zarr; every voxel endpoint accepts both.
_RESULT_RE = re.compile(r"^[0-9a-f]{24}$")


class LibraryError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Library:
    def __init__(self) -> None:
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    @staticmethod
    def check_vid(vid: str) -> str:
        if not _VID_RE.match(vid):
            raise LibraryError(404, f"Wolumen '{vid}' nie istnieje")
        return vid

    @staticmethod
    def volume_path(ws_dir: Path, vid: str) -> Path:
        """Library volume (12 hex) or node-graph result (24 hex)."""
        if _RESULT_RE.match(vid):
            return ws_dir / "cache" / f"{vid}.zarr"
        return ws_dir / "store" / f"{Library.check_vid(vid)}.zarr"

    @staticmethod
    def series_dir(ws_dir: Path, vid: str) -> Path:
        return ws_dir / "series" / Library.check_vid(vid)

    def _index(self, ws_dir: Path) -> Path:
        return ws_dir / "series" / "index.json"

    def list(self, ws_dir: Path) -> list[dict[str, Any]]:
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            alive = [e for e in entries if (ws_dir / "store" / f"{e['id']}.zarr").is_dir()]
            if len(alive) != len(entries):
                write_json(self._index(ws_dir), alive)
            return alive

    def get(self, ws_dir: Path, vid: str) -> dict[str, Any]:
        self.check_vid(vid)
        for e in self.list(ws_dir):
            if e["id"] == vid:
                return e
        raise LibraryError(404, f"Wolumen '{vid}' nie istnieje")

    def fingerprints(self, ws_dir: Path) -> set[str]:
        return {e.get("fingerprint", "") for e in self.list(ws_dir)}

    def add(self, ws_dir: Path, entry: dict[str, Any]) -> None:
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            entries.append(entry)
            write_json(self._index(ws_dir), entries)

    def rename(self, ws_dir: Path, vid: str, name: str) -> dict[str, Any]:
        self.check_vid(vid)
        name = (name or "").strip()
        if not name:
            raise LibraryError(400, "Nazwa nie może być pusta")
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            for e in entries:
                if e["id"] == vid:
                    e["name"] = name
                    write_json(self._index(ws_dir), entries)
                    return e
        raise LibraryError(404, f"Wolumen '{vid}' nie istnieje")

    def delete(self, ws_dir: Path, vid: str) -> None:
        path = self.volume_path(ws_dir, vid)
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            write_json(self._index(ws_dir), [e for e in entries if e["id"] != vid])
        store.forget(path)
        shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(self.series_dir(ws_dir, vid), ignore_errors=True)
