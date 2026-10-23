"""Values flowing along graph edges.

A volume is a HANDLE (zarr path + level + geometry), never an array: the graph JSON, the
cache manifests and the UI only ever see refs. Arrays are materialised on demand through
a byte-bounded LRU, so a chain of nodes reading the same input reads it from disk once.
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import SimpleITK as sitk

from ..volumes import store
from ..volumes.geometry import Geometry


@dataclass
class VolumeValue:
    ref: str  # library vid (12 hex) or result id (24 hex) — what the viewports display
    path: Path
    level: int  # pyramid level that represents this value's resolution
    geometry: Geometry  # of that level
    info: dict[str, Any] = field(default_factory=dict)  # name, modality, window, source…
    # "wolumen" (scalar) | "segment" (binary 0/1 mask) | "segmentacja" (label map 0..N)
    kind: str = "wolumen"

    def array(self) -> np.ndarray:
        return ARRAYS.get(self.path, self.level)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "level": self.level,
            "info": self.info,
            "geometry": self.geometry.to_json(),
        }


@dataclass
class MeshValue:
    """A surface: handle to <ref>.mesh (world LPS vertices). `info.ref` = background volume
    (what the viewports show behind it), `info.color`, plus the stats stored with it."""

    ref: str  # library mesh (12 hex) or node result (24 hex)
    path: Path
    info: dict[str, Any] = field(default_factory=dict)
    kind: str = "mesh"

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """(verts float32 [N,3], faces int64 [M,3]), read-only, from the mesh LRU."""
        from ..meshes.store import MESHES

        return MESHES.get(self.path)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "info": self.info}


@dataclass
class DataValue:
    """A small JSON value on an edge: "punkty" (markups) or "tabela" (columns + rows)."""

    kind: str
    value: Any

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value}


class ArrayCache:
    """LRU of whole decoded levels, bounded in bytes. Arrays are read-only (flag set) so a
    node can never corrupt a cached input shared with other nodes."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._map: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._bytes = 0

    def get(self, path: Path, level: int) -> np.ndarray:
        key = (str(path), level)
        with self._lock:
            a = self._map.get(key)
            if a is not None:
                self._map.move_to_end(key)
                return a
        a = np.asarray(store.open_level(path, level)[:])
        a.flags.writeable = False
        with self._lock:
            if key not in self._map:
                self._map[key] = a
                self._bytes += a.nbytes
                while self._bytes > self.max_bytes and len(self._map) > 1:
                    _, old = self._map.popitem(last=False)
                    self._bytes -= old.nbytes
        return a

    def put(self, path: Path, level: int, arr: np.ndarray) -> None:
        """A freshly computed level (the caller hands it over: it becomes read-only)."""
        arr.flags.writeable = False
        key = (str(path), level)
        with self._lock:
            old = self._map.pop(key, None)
            if old is not None:
                self._bytes -= old.nbytes
            self._map[key] = arr
            self._bytes += arr.nbytes
            while self._bytes > self.max_bytes and len(self._map) > 1:
                _, o = self._map.popitem(last=False)
                self._bytes -= o.nbytes

    def forget(self, path: Path) -> None:
        p = str(path)
        with self._lock:
            for k in [k for k in self._map if k[0] == p]:
                self._bytes -= self._map.pop(k).nbytes


ARRAYS = ArrayCache(1536 << 20)


# ── SimpleITK interop (same conventions: [k,j,i] arrays, (i,j,k) geometry, LPS) ──


def to_sitk(arr: np.ndarray, g: Geometry) -> sitk.Image:
    img = sitk.GetImageFromArray(arr)  # view-free copy into ITK memory
    img.SetSpacing(g.spacing)
    img.SetOrigin(g.origin)
    img.SetDirection(g.direction)  # ITK: row-major, columns = axes — identical to ours
    return img


def from_sitk(img: sitk.Image) -> tuple[np.ndarray, Geometry]:
    arr = sitk.GetArrayFromImage(img)
    g = Geometry(
        size=tuple(int(s) for s in img.GetSize()),  # type: ignore[arg-type]
        spacing=tuple(float(s) for s in img.GetSpacing()),  # type: ignore[arg-type]
        origin=tuple(float(o) for o in img.GetOrigin()),  # type: ignore[arg-type]
        direction=tuple(float(d) for d in img.GetDirection()),
    )
    return arr, g


def same_grid(a: Geometry, b: Geometry) -> bool:
    return (
        a.size == b.size
        and np.allclose(a.spacing, b.spacing)
        and np.allclose(a.origin, b.origin, atol=1e-4)
        and np.allclose(a.direction, b.direction, atol=1e-6)
    )


def resample_onto(v: VolumeValue, g: Geometry, linear: bool) -> np.ndarray:
    """`v` sampled on grid `g` (outside → 0). Nearest for labels, linear for intensities."""
    if same_grid(v.geometry, g):
        return v.array()
    src = to_sitk(v.array(), v.geometry)
    ref = sitk.Image([int(s) for s in g.size], src.GetPixelID())
    ref.SetSpacing(g.spacing)
    ref.SetOrigin(g.origin)
    ref.SetDirection(g.direction)
    interp = sitk.sitkLinear if linear else sitk.sitkNearestNeighbor
    return sitk.GetArrayFromImage(sitk.Resample(src, ref, sitk.Transform(), interp, 0))
