"""Mesh file formats: STL (ASCII + binary), OBJ, PLY (ASCII + binary little/big endian).

Readers return (verts float64 [N,3], faces int64 [M,3], space) with duplicate vertices
welded (STL is a triangle soup) and polygons fan-triangulated. `space` is the coordinate
system named in the file header ("LPS" / "RAS", as 3D Slicer writes it) or "" if none.
Writers take world LPS vertices and convert to the requested space.
"""

import re
import struct
from pathlib import Path

import numpy as np

MESH_EXTENSIONS = (".stl", ".obj", ".ply")

_SPACE_RE = re.compile(rb"SPACE\s*=\s*(LPS|RAS)", re.IGNORECASE)
_FLOAT = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_STL_VERTEX_RE = re.compile(
    rb"vertex\s+(" + _FLOAT + rb")\s+(" + _FLOAT + rb")\s+(" + _FLOAT + rb")"
)


class MeshFileError(Exception):
    pass


def is_mesh_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in MESH_EXTENSIONS


def _space_of(head: bytes) -> str:
    m = _SPACE_RE.search(head)
    return m.group(1).decode().upper() if m else ""


def weld(verts: np.ndarray, faces: np.ndarray, tol: float = 1e-5) -> tuple[np.ndarray, np.ndarray]:
    """Merge vertices closer than `tol` mm (quantised) and drop faces that collapse."""
    q = np.round(verts / tol).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    v = verts[first]
    f = inv.reshape(-1)[faces]
    ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return v, f[ok]


def _fan(polys: list[list[int]]) -> np.ndarray:
    out = [(p[0], p[n], p[n + 1]) for p in polys for n in range(1, len(p) - 1)]
    return np.asarray(out, dtype=np.int64).reshape(-1, 3)


# ── STL ──────────────────────────────────────────────────────────────────────


def _read_stl(data: bytes) -> tuple[np.ndarray, np.ndarray, str]:
    space = _space_of(data[:400])
    binary = len(data) >= 84
    if binary:
        (n,) = struct.unpack_from("<I", data, 80)
        binary = len(data) == 84 + 50 * n
    if binary:
        rec = np.frombuffer(
            data,
            dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
            count=n,
            offset=84,
        )
        soup = rec["v"].reshape(-1, 3).astype(np.float64)
    else:
        if not data.lstrip()[:5].lower() == b"solid":
            raise MeshFileError("To nie jest plik STL")
        nums = _STL_VERTEX_RE.findall(data)
        soup = np.asarray(nums, dtype=np.float64).reshape(-1, 3)
        soup = soup[: len(soup) // 3 * 3]
    if not len(soup):
        raise MeshFileError("Plik STL nie zawiera trójkątów")
    faces = np.arange(len(soup), dtype=np.int64).reshape(-1, 3)
    v, f = weld(soup, faces)
    return v, f, space


def _write_stl(path: Path, v: np.ndarray, f: np.ndarray, space: str) -> None:
    tri = v[f].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec = np.zeros(len(f), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"] = n
    rec["v"] = tri
    header = f"praTRD SPACE={space}".encode().ljust(80, b" ")
    with path.open("wb") as fh:
        fh.write(header)
        fh.write(struct.pack("<I", len(f)))
        fh.write(rec.tobytes())


# ── OBJ ──────────────────────────────────────────────────────────────────────


def _read_obj(data: bytes) -> tuple[np.ndarray, np.ndarray, str]:
    verts: list[bytes] = []
    polys: list[list[int]] = []
    for line in data.splitlines():
        if line.startswith(b"v "):
            verts.append(line[2:])
        elif line.startswith(b"f "):
            idx = [int(t.split(b"/")[0]) for t in line[2:].split()]
            polys.append(idx)
    if not verts or not polys:
        raise MeshFileError("Plik OBJ nie zawiera ścian")
    v = np.asarray([row.split()[:3] for row in verts], dtype=np.float64)
    nv = len(v)
    # 1-based; negative = relative to the end
    polys = [[(i - 1) if i > 0 else nv + i for i in p] for p in polys]
    f = _fan(polys)
    if f.size and (f.min() < 0 or f.max() >= nv):
        raise MeshFileError("Plik OBJ ma ściany z nieistniejącymi wierzchołkami")
    v, f = weld(v, f)
    return v, f, _space_of(data[:2000])


def _write_obj(path: Path, v: np.ndarray, f: np.ndarray, space: str) -> None:
    with path.open("w", encoding="ascii", newline="\n") as fh:
        fh.write(f"# praTRD SPACE={space}\n")
        np.savetxt(fh, v, fmt="v %.5f %.5f %.5f")
        np.savetxt(fh, f + 1, fmt="f %d %d %d")


# ── PLY ──────────────────────────────────────────────────────────────────────

_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}  # fmt: skip


def _read_ply(data: bytes) -> tuple[np.ndarray, np.ndarray, str]:
    end = data.find(b"end_header")
    if not data.startswith(b"ply") or end < 0:
        raise MeshFileError("To nie jest plik PLY")
    body = data[data.index(b"\n", end) + 1 :]
    header = data[:end].decode("ascii", "replace").splitlines()
    fmt = ""
    elements: list[dict] = []
    for line in header:
        t = line.split()
        if not t:
            continue
        if t[0] == "format":
            fmt = t[1]
        elif t[0] == "element":
            elements.append({"name": t[1], "count": int(t[2]), "props": []})
        elif t[0] == "property" and elements:
            elements[-1]["props"].append(t[1:])
    order = "<" if fmt == "binary_little_endian" else ">"
    verts = faces = None
    if fmt == "ascii":
        rows = iter(body.splitlines())
        for el in elements:
            if el["name"] == "vertex":
                xyz = [i for i, p in enumerate(el["props"]) if p[-1] in ("x", "y", "z")]
                lines = [next(rows).split() for _ in range(el["count"])]
                verts = np.asarray([[ln[i] for i in xyz] for ln in lines], dtype=np.float64)
            elif el["name"] == "face":
                polys = []
                for _ in range(el["count"]):
                    t = [int(x) for x in next(rows).split()]
                    polys.append(t[1 : 1 + t[0]])
                faces = _fan(polys)
            else:
                for _ in range(el["count"]):
                    next(rows)
    else:
        off = 0
        for el in elements:
            props = el["props"]
            if props and props[0][0] == "list":
                # faces: list count type + index type; fast path for all-triangle files
                ct = np.dtype(order + _PLY_TYPES[props[0][1]])
                it = np.dtype(order + _PLY_TYPES[props[0][2]])
                extra = props[1:]
                if extra:
                    raise MeshFileError("Nieobsługiwany układ ścian PLY")
                rec = np.dtype([("n", ct), ("i", it, 3)])
                arr = np.frombuffer(body, dtype=rec, count=el["count"], offset=off)
                if el["name"] == "face" and np.all(arr["n"] == 3):
                    faces = arr["i"].astype(np.int64)
                    off += arr.nbytes
                else:  # mixed polygons: walk the records
                    polys, o = [], off
                    for _ in range(el["count"]):
                        (k,) = np.frombuffer(body, ct, 1, o)
                        o += ct.itemsize
                        polys.append(np.frombuffer(body, it, int(k), o).tolist())
                        o += it.itemsize * int(k)
                    off = o
                    if el["name"] == "face":
                        faces = _fan(polys)
                continue
            dt = np.dtype([(p[1], order + _PLY_TYPES[p[0]]) for p in props])
            arr = np.frombuffer(body, dtype=dt, count=el["count"], offset=off)
            off += arr.nbytes
            if el["name"] == "vertex":
                verts = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float64)
    if verts is None or faces is None or not len(faces):
        raise MeshFileError("Plik PLY nie zawiera ścian")
    v, f = weld(verts, faces)
    return v, f, _space_of(data[:end])


def _write_ply(path: Path, v: np.ndarray, f: np.ndarray, space: str) -> None:
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"comment praTRD SPACE={space}\n"
        f"element vertex {len(v)}\nproperty float x\nproperty float y\nproperty float z\n"
        f"element face {len(f)}\nproperty list uchar uint vertex_indices\nend_header\n"
    )
    rec = np.empty(len(f), dtype=np.dtype([("n", "u1"), ("i", "<u4", 3)]))
    rec["n"] = 3
    rec["i"] = f
    with path.open("wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(v.astype("<f4").tobytes())
        fh.write(rec.tobytes())


# ── public ───────────────────────────────────────────────────────────────────


def read_mesh_file(path: str | Path) -> tuple[np.ndarray, np.ndarray, str]:
    p = Path(path)
    ext = p.suffix.lower()
    data = p.read_bytes()
    if ext == ".stl":
        return _read_stl(data)
    if ext == ".obj":
        return _read_obj(data)
    if ext == ".ply":
        return _read_ply(data)
    raise MeshFileError(f"Nieobsługiwany format: {ext or p.name}")


def lps_to(space: str, v: np.ndarray) -> np.ndarray:
    """LPS ↔ RAS is its own inverse: negate x and y (handedness unchanged → same winding)."""
    if space == "RAS":
        v = v.copy()
        v[:, :2] *= -1
    return v


def write_mesh_file(path: str | Path, v_lps: np.ndarray, f: np.ndarray, space: str = "LPS") -> Path:
    p = Path(path)
    ext = p.suffix.lower()
    v = lps_to(space, np.asarray(v_lps, dtype=np.float64))
    f = np.asarray(f, dtype=np.int64)
    writer = {".stl": _write_stl, ".obj": _write_obj, ".ply": _write_ply}.get(ext)
    if writer is None:
        raise MeshFileError(f"Nieobsługiwany format: {ext or p.name}")
    tmp = p.with_name(p.name + ".partial")
    writer(tmp, v, f, space)
    tmp.replace(p)
    return p
