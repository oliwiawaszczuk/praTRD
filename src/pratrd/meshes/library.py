"""Per-workspace mesh library (imported STL / OBJ / PLY files).

workspaces/<wid>/meshes/index.json      [entry, …]
workspaces/<wid>/meshes/<mid>.mesh/     see meshes.store

Vertices are stored as they are in the file; `space` is what the header says (3D Slicer
writes "SPACE=LPS" / "SPACE=RAS"), LPS when it says nothing. The node "Plik mesha" converts
to LPS — a wrong guess is fixed by one switch, without importing again.
"""

import hashlib
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..jsonio import read_json, write_json
from ..volumes.library import LibraryError
from . import io, store


class MeshLibrary:
    def __init__(self) -> None:
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    @staticmethod
    def _index(ws_dir: Path) -> Path:
        return ws_dir / "meshes" / "index.json"

    def list(self, ws_dir: Path) -> list[dict[str, Any]]:
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            alive = [e for e in entries if store.mesh_path(ws_dir, e["id"]).is_dir()]
            if len(alive) != len(entries):
                write_json(self._index(ws_dir), alive)
            return alive

    def get(self, ws_dir: Path, mid: str) -> dict[str, Any]:
        for e in self.list(ws_dir):
            if e["id"] == mid:
                return e
        raise LibraryError(404, f"Mesh '{mid}' nie istnieje")

    def import_file(self, ws_dir: Path, path: str | Path) -> dict[str, Any]:
        src = Path(path)
        if not src.is_file():
            raise LibraryError(404, f"Plik nie istnieje: {src}")
        if not io.is_mesh_file(src):
            raise LibraryError(400, f"Nieobsługiwany format: {src.suffix or src.name}")
        t0 = time.monotonic()
        try:
            v, f, space = io.read_mesh_file(src)
        except io.MeshFileError as e:
            raise LibraryError(400, f"{src.name}: {e}") from e
        st = src.stat()
        # same file (name, size, mtime) imported again → the same id, no second copy
        mid = hashlib.sha256(f"{src.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
        mid = mid[:12]
        for e in self.list(ws_dir):
            if e["id"] == mid:
                return e
        dst = store.mesh_path(ws_dir, mid)
        dst.parent.mkdir(parents=True, exist_ok=True)
        info = {"name": src.stem, "color": "#e8c547", "source": src.name, "space": space or "LPS"}
        meta = store.write_mesh(dst, v, f, info)
        entry = {
            "id": mid,
            "name": src.stem,
            "file": src.name,
            "format": src.suffix.lower().lstrip("."),
            "space": space or "LPS",
            "spaceFromFile": bool(space),
            "verts": meta["verts"],
            "faces": meta["faces"],
            **{k: meta["stats"][k] for k in ("area", "ml", "closed", "bounds")},
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "importSeconds": round(time.monotonic() - t0, 3),
        }
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            entries.append(entry)
            write_json(self._index(ws_dir), entries)
        return entry

    def rename(self, ws_dir: Path, mid: str, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise LibraryError(400, "Nazwa nie może być pusta")
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            for e in entries:
                if e["id"] == mid:
                    e["name"] = name
                    write_json(self._index(ws_dir), entries)
                    return e
        raise LibraryError(404, f"Mesh '{mid}' nie istnieje")

    def delete(self, ws_dir: Path, mid: str) -> None:
        path = store.mesh_path(ws_dir, mid)
        with self._locks[str(ws_dir)]:
            entries = read_json(self._index(ws_dir), [])
            write_json(self._index(ws_dir), [e for e in entries if e["id"] != mid])
        store.MESHES.forget(path)
        shutil.rmtree(path, ignore_errors=True)


def cleanup_partials(ws_dir: Path) -> None:
    for d in ("meshes", "cache"):
        for p in (ws_dir / d).glob("*.mesh.partial"):
            shutil.rmtree(p, ignore_errors=True)
