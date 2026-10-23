"""On-disk mesh: a directory written once (`.partial` → rename), never modified.

<ref>.mesh/verts.bin    float32 LE [N, 3]  world LPS mm
<ref>.mesh/normals.bin  float32 LE [N, 3]  unit vertex normals (area weighted)
<ref>.mesh/cells.bin    uint32 LE [M, 4]   VTK cell layout (3, a, b, c) — what vtk.js takes as is
<ref>.mesh/meta.json    {"verts", "faces", "info", "stats"}
<ref>.mesh/thumb.png    written lazily on first request

Library meshes: <ws>/meshes/<12 hex>.mesh; node results: <ws>/cache/<24 hex>.mesh.
"""

import re
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from ..jsonio import read_json, write_json
from . import ops

_LIB_RE = re.compile(r"^[0-9a-f]{12}$")
_RESULT_RE = re.compile(r"^[0-9a-f]{24}$")


class MeshNotFound(Exception):
    pass


def mesh_path(ws_dir: Path, ref: str) -> Path:
    if _RESULT_RE.match(ref):
        return ws_dir / "cache" / f"{ref}.mesh"
    if _LIB_RE.match(ref):
        return ws_dir / "meshes" / f"{ref}.mesh"
    raise MeshNotFound(ref)


def write_mesh(path: Path, verts: np.ndarray, faces: np.ndarray, info: dict[str, Any]) -> dict:
    """Persist a mesh; returns its meta. Vertices/faces are taken as world LPS / indices."""
    v = np.ascontiguousarray(verts, dtype="<f4")
    f = np.ascontiguousarray(faces, dtype=np.int64)
    stats = ops.surface_stats(v, f)
    meta = {"verts": int(len(v)), "faces": int(len(f)), "info": info, "stats": stats}
    tmp = path.with_name(path.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        v.tofile(tmp / "verts.bin")
        ops.vertex_normals(v, f).astype("<f4").tofile(tmp / "normals.bin")
        cells = np.empty((len(f), 4), dtype="<u4")
        cells[:, 0] = 3
        cells[:, 1:] = f
        cells.tofile(tmp / "cells.bin")
        write_json(tmp / "meta.json", meta)
        if path.exists():  # same ref = same content (content-addressed): keep the old one
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.rename(path)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return meta


def read_meta(path: Path) -> dict[str, Any]:
    m = read_json(path / "meta.json", None)
    if not isinstance(m, dict):
        raise MeshNotFound(str(path))
    return m


def read_arrays(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(verts float32 [N,3], faces int64 [M,3]) — read-only."""
    m = read_meta(path)
    v = np.fromfile(path / "verts.bin", dtype="<f4").reshape(m["verts"], 3)
    cells = np.fromfile(path / "cells.bin", dtype="<u4").reshape(m["faces"], 4)
    f = cells[:, 1:].astype(np.int64)
    v.flags.writeable = False
    f.flags.writeable = False
    return v, f


def byte_files(path: Path) -> list[Path]:
    return [path / "verts.bin", path / "normals.bin", path / "cells.bin"]


DISPLAY_FACES = 1_500_000  # what a webview draws smoothly (≈ 40 MB of buffers)
_lod_locks: dict[str, threading.Lock] = {}
_lod_guard = threading.Lock()


def display_path(path: Path, max_faces: int = DISPLAY_FACES) -> Path:
    """The mesh itself, or a decimated copy (<mesh>/lod, made once) when it has more faces
    than a viewport needs — like a pyramid level for volumes. Exports use the original."""
    if read_meta(path)["faces"] <= max_faces:
        return path
    lod = path / "lod"
    with _lod_guard:
        lock = _lod_locks.setdefault(str(path), threading.Lock())
    with lock:
        if not lod.is_dir():
            v, f = MESHES.get(path)
            v2, f2 = ops.decimate(v, f, max_faces / len(f))
            write_mesh(lod, v2, f2, read_meta(path).get("info", {}))
    return lod


def disk_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


class MeshCache:
    """LRU of decoded meshes bounded in bytes (a chain of mesh nodes reads its input once)."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._map: OrderedDict[str, tuple[np.ndarray, np.ndarray]] = OrderedDict()
        self._bytes = 0

    def get(self, path: Path) -> tuple[np.ndarray, np.ndarray]:
        key = str(path)
        with self._lock:
            hit = self._map.get(key)
            if hit is not None:
                self._map.move_to_end(key)
                return hit
        if not path.is_dir():
            raise MeshNotFound(key)
        vf = read_arrays(path)
        self.put(path, *vf)
        return vf

    def put(self, path: Path, v: np.ndarray, f: np.ndarray) -> None:
        key = str(path)
        v.flags.writeable = False
        f.flags.writeable = False
        with self._lock:
            old = self._map.pop(key, None)
            if old is not None:
                self._bytes -= old[0].nbytes + old[1].nbytes
            self._map[key] = (v, f)
            self._bytes += v.nbytes + f.nbytes
            while self._bytes > self.max_bytes and len(self._map) > 1:
                _, (ov, of) = self._map.popitem(last=False)
                self._bytes -= ov.nbytes + of.nbytes

    def forget(self, path: Path) -> None:
        with self._lock:
            old = self._map.pop(str(path), None)
            if old is not None:
                self._bytes -= old[0].nbytes + old[1].nbytes


MESHES = MeshCache(512 << 20)


def thumbnail(path: Path, size: tuple[int, int] = (176, 132)) -> Path:
    """Shaded anterior view (camera at −y, head up) as PNG, cached next to the mesh."""
    out = path / "thumb.png"
    if out.is_file():
        return out
    from PIL import Image

    v, f = MESHES.get(path)
    color = str(read_meta(path).get("info", {}).get("color") or "#4db6ac")
    rgba = ops.render_thumb(v, f, size, color)
    tmp = path / "thumb.png.partial"
    Image.fromarray(rgba, "RGBA").save(tmp, format="PNG")
    tmp.replace(out)
    return out
