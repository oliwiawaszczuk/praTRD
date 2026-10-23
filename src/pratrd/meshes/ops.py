"""Mesh geometry, vectorised (numpy / scipy.sparse). Vertices in world LPS mm.

Winding convention: counter-clockwise seen from outside → face normals point outwards and
the signed volume of a closed surface is positive (checked and fixed after every op that
could flip it, e.g. marching cubes in [k, j, i] order or a left-handed direction matrix).
"""

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from ..volumes.geometry import Geometry

Progress = Callable[[float], None]


def _noop(_: float) -> None:
    pass


def face_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Un-normalised (length = 2 × area)."""
    a = v[f[:, 0]].astype(np.float64)
    return np.cross(v[f[:, 1]] - a, v[f[:, 2]] - a)


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    fn = face_normals(v, f)
    n = np.empty((len(v), 3), dtype=np.float64)
    idx = f.reshape(-1)
    for c in range(3):  # bincount with weights: area-weighted sum per vertex, no np.add.at
        n[:, c] = np.bincount(idx, weights=np.repeat(fn[:, c], 3), minlength=len(v))
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    return n


def signed_volume(v: np.ndarray, f: np.ndarray) -> float:
    a = v[f[:, 0]].astype(np.float64)
    b = v[f[:, 1]].astype(np.float64)
    c = v[f[:, 2]].astype(np.float64)
    return float(np.einsum("ij,ij->", a, np.cross(b, c)) / 6.0)


def boundary_edges(f: np.ndarray, nv: int) -> int:
    """Edges used by exactly one face (0 → the surface is closed)."""
    if not len(f):
        return 0
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e.sort(axis=1)
    key = e[:, 0].astype(np.int64) * nv + e[:, 1]
    key.sort()
    if len(key) == 1:
        return 1
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    counts = np.diff(np.r_[starts, len(key)])
    return int(np.count_nonzero(counts == 1))


def surface_stats(v: np.ndarray, f: np.ndarray) -> dict[str, Any]:
    if not len(f):
        return {"area": 0.0, "volume": 0.0, "ml": 0.0, "closed": False, "boundary": 0,
                "bounds": [0.0] * 6}  # fmt: skip
    area = float(np.linalg.norm(face_normals(v, f), axis=1).sum() / 2)
    vol = signed_volume(v, f)
    open_edges = boundary_edges(f, len(v))
    lo = v.min(axis=0)
    hi = v.max(axis=0)
    return {
        "area": round(area, 3),
        "volume": round(vol, 3),
        "ml": round(abs(vol) / 1000, 4),
        "closed": open_edges == 0,
        "boundary": open_edges,
        # vtk.js order: xmin, xmax, ymin, ymax, zmin, zmax
        "bounds": [round(float(x), 3) for pair in zip(lo, hi, strict=True) for x in pair],
    }


def orient_outwards(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    if len(f) and signed_volume(v, f) < 0:
        return f[:, [0, 2, 1]]
    return f


def index_to_world(g: Geometry, ijk: np.ndarray) -> np.ndarray:
    return np.asarray(g.origin) + (ijk * np.asarray(g.spacing)) @ g.matrix.T


def world_to_index(g: Geometry, w: np.ndarray) -> np.ndarray:
    return ((w - np.asarray(g.origin)) @ g.matrix) / np.asarray(g.spacing)


# ── segment → surface ─────────────────────────────────────────────────────────

_SLAB = 64  # k-slices per marching-cubes call (bounded memory on 512²×2000 masks)


def _bbox(mask: np.ndarray) -> tuple[list[int], list[int]] | None:
    """[k, j, i] bounding box from axis projections (no voxel-sized index arrays)."""
    lo, hi = [], []
    for ax in range(3):
        other = tuple(a for a in range(3) if a != ax)
        nz = np.flatnonzero(np.any(mask, axis=other))
        if not nz.size:
            return None
        lo.append(int(nz[0]))
        hi.append(int(nz[-1]) + 1)
    return lo, hi


def from_mask(
    mask: np.ndarray, g: Geometry, sigma_mm: float, report: Progress = _noop
) -> tuple[np.ndarray, np.ndarray]:
    """Iso-surface (0.5) of a 0/1 mask after a Gaussian of σ mm; world LPS vertices.

    Marching cubes runs on k-slabs of the mask's bounding box. Neighbouring slabs share one
    slice, so the vertices on that plane are computed identically twice and welded back —
    the result is one closed surface, while memory stays at a slab, not the whole box.
    """
    from scipy.ndimage import gaussian_filter
    from skimage.measure import marching_cubes

    box = _bbox(mask)
    if box is None:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    lo, hi = box
    sig = [sigma_mm / g.spacing[2], sigma_mm / g.spacing[1], sigma_mm / g.spacing[0]]  # k, j, i
    smooth = sigma_mm > 0
    margin = [int(math.ceil(4 * s)) + 1 if smooth else 0 for s in sig]  # gaussian truncate=4
    pad = [m + 1 for m in margin]  # zero border → closed surface
    # padded box in [k, j, i]; slabs cut along k inside it
    nk = hi[0] - lo[0] + 2 * pad[0]
    verts_all: list[np.ndarray] = []
    faces_all: list[np.ndarray] = []
    seams: list[tuple[int, int, float]] = []  # (slab index a, slab a+1, k of shared plane)
    n_v = 0
    starts = list(range(0, nk - 1, _SLAB))
    for si, a in enumerate(starts):
        b = min(a + _SLAB, nk - 1)  # slab covers padded k in [a, b] inclusive
        ka, kb = a - margin[0], b + 1 + margin[0]  # with filter margin
        sub = _padded(mask, lo, hi, pad, ka, kb)
        if smooth:
            sub = gaussian_filter(sub, sig, truncate=4.0)
        sub = sub[a - ka : a - ka + (b - a + 1)]
        report((si + 0.5) / len(starts))
        if sub.max() <= 0.5 or sub.min() >= 0.5 or sub.shape[0] < 2:
            continue
        vv, ff, _, _ = marching_cubes(sub, 0.5, allow_degenerate=False)
        vv[:, 0] += a
        verts_all.append(vv)
        faces_all.append(ff + n_v)
        n_v += len(vv)
        if si + 1 < len(starts):
            seams.append((len(verts_all) - 1, len(verts_all), float(b)))
    if not verts_all:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    kji = np.concatenate(verts_all)
    faces = np.concatenate(faces_all).astype(np.int64)
    if len(starts) > 1:
        kji, faces = _weld_planes(kji, faces, sorted({s[2] for s in seams}))
    # padded [k, j, i] → volume index (i, j, k) → world
    ijk = kji[:, ::-1] + np.asarray([lo[2] - pad[2], lo[1] - pad[1], lo[0] - pad[0]], float)
    verts = index_to_world(g, ijk)
    return verts, orient_outwards(verts, faces)


def _padded(
    mask: np.ndarray, lo: list[int], hi: list[int], pad: list[int], ka: int, kb: int
) -> np.ndarray:
    """float32 block of the padded bounding box, padded-k range [ka, kb) (zeros outside)."""
    nj = hi[1] - lo[1] + 2 * pad[1]
    ni = hi[2] - lo[2] + 2 * pad[2]
    out = np.zeros((kb - ka, nj, ni), dtype=np.float32)
    # padded k → mask k
    k0 = max(ka, pad[0]) + lo[0] - pad[0]
    k1 = min(kb, hi[0] - lo[0] + pad[0]) + lo[0] - pad[0]
    if k1 > k0:
        src = mask[k0:k1, lo[1] : hi[1], lo[2] : hi[2]]
        d0 = k0 - (lo[0] - pad[0]) - ka
        out[d0 : d0 + (k1 - k0), pad[1] : pad[1] + src.shape[1], pad[2] : pad[2] + src.shape[2]] = (
            src
        )
    return out


def _weld_planes(
    kji: np.ndarray, faces: np.ndarray, planes: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Merge the duplicated vertices lying on the shared slab planes (exact coordinates)."""
    on = np.isin(kji[:, 0], np.asarray(planes))
    idx = np.flatnonzero(on)
    remap = np.arange(len(kji))
    if idx.size:
        q = np.round(kji[idx] * 1e4).astype(np.int64)
        _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
        remap[idx] = idx[first][inv.reshape(-1)]
    keep = remap == np.arange(len(kji))
    new_id = np.cumsum(keep) - 1
    f = new_id[remap[faces]]
    ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return kji[keep], f[ok]


# ── smoothing / decimation ────────────────────────────────────────────────────


def _neighbour_mean(f: np.ndarray, nv: int):  # noqa: ANN202 — scipy sparse matrix
    from scipy.sparse import csr_matrix

    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    rows = np.concatenate([e[:, 0], e[:, 1]])
    cols = np.concatenate([e[:, 1], e[:, 0]])
    a = csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(nv, nv))
    a.data[:] = 1.0  # duplicate entries (edge shared by two faces) summed → back to 1
    deg = np.asarray(a.sum(axis=1)).ravel()
    deg[deg == 0] = 1
    return csr_matrix(a.multiply(1.0 / deg[:, None]))


def smooth(
    v: np.ndarray,
    f: np.ndarray,
    iterations: int,
    method: str = "taubin",
    strength: float = 0.5,
    report: Progress = _noop,
) -> np.ndarray:
    """Taubin λ|μ (keeps the volume) or plain Laplacian (shrinks). Umbrella operator."""
    if iterations <= 0 or not len(f):
        return np.asarray(v, dtype=np.float64)
    w = _neighbour_mean(f, len(v))
    x = np.asarray(v, dtype=np.float64).copy()
    lam = float(strength)
    mu = -lam / (1 - 0.1 * lam)  # pass-band k_PB = 0.1 (Taubin 1995)
    for it in range(iterations):
        x += lam * (w @ x - x)
        if method == "taubin":
            x += mu * (w @ x - x)
        report((it + 1) / iterations)
    return x


def decimate(v: np.ndarray, f: np.ndarray, keep: float) -> tuple[np.ndarray, np.ndarray]:
    """Quadric edge collapse to ~`keep` (0..1] of the triangles (fast-simplification)."""
    if keep >= 1 or len(f) < 8:
        return np.asarray(v, np.float64), np.asarray(f, np.int64)
    import fast_simplification

    pts, tri = fast_simplification.simplify(
        np.asarray(v, np.float32), np.asarray(f, np.int32), target_reduction=1 - keep
    )
    pts = np.asarray(pts, np.float64)
    return pts, orient_outwards(pts, np.asarray(tri, np.int64))


# ── surface → segment ─────────────────────────────────────────────────────────

_RAY_BATCH = 4 << 20  # (triangle, ray) candidates per vectorised batch


def voxelize(v: np.ndarray, f: np.ndarray, g: Geometry, report: Progress = _noop) -> np.ndarray:
    """Inside of a closed surface on grid `g` → uint8 [k, j, i] mask.

    One ray along k through every (i, j) voxel column: each triangle crossing a ray toggles
    the parity from its crossing depth on; a cumulative sum along k then marks the voxels
    with an odd number of crossings below them. Rays are nudged by ~1e-4 voxel so they
    never run exactly through a vertex or an edge (marching-cubes meshes sit on the grid).
    """
    out = np.zeros(g.shape_kji, dtype=np.uint8)
    if not len(f):
        return out
    p = world_to_index(g, np.asarray(v, np.float64))
    # only the mesh's box is ray cast and summed (a small model on a 512²×600 grid: ms, not s)
    lo = np.clip(np.floor(p.min(0)).astype(np.int64), 0, g.size)
    hi = np.clip(np.ceil(p.max(0)).astype(np.int64) + 1, 0, g.size)
    if np.any(hi <= lo):
        return out
    ni, nj, nk = (int(x) for x in hi - lo)
    toggles = np.zeros((nk + 1, nj, ni), dtype=np.uint8)
    tri = (p - lo)[f]  # [M, 3 corners, (i, j, k)] in the box
    i0 = np.ceil(tri[:, :, 0].min(1) - 1.234e-4).astype(np.int64).clip(0, ni)
    i1 = np.floor(tri[:, :, 0].max(1) - 1.234e-4).astype(np.int64).clip(-1, ni - 1)
    j0 = np.ceil(tri[:, :, 1].min(1) - 2.345e-4).astype(np.int64).clip(0, nj)
    j1 = np.floor(tri[:, :, 1].max(1) - 2.345e-4).astype(np.int64).clip(-1, nj - 1)
    wi = np.maximum(i1 - i0 + 1, 0)
    wj = np.maximum(j1 - j0 + 1, 0)
    count = wi * wj
    live = np.flatnonzero(count)
    csum = np.cumsum(count[live])
    start = 0
    while start < len(live):
        base = csum[start - 1] if start else 0
        stop = int(np.searchsorted(csum, base + _RAY_BATCH, side="right"))
        stop = max(stop, start + 1)
        t = live[start:stop]
        _cast(tri[t], i0[t], j0[t], wi[t], count[t], toggles, nk)
        start = stop
        report(min(1.0, float(csum[stop - 1]) / float(csum[-1])))
    np.cumsum(toggles, axis=0, dtype=np.uint8, out=toggles)
    np.bitwise_and(toggles, 1, out=toggles)
    out[lo[2] : hi[2], lo[1] : hi[1], lo[0] : hi[0]] = toggles[:nk]
    return out


def _cast(
    tri: np.ndarray,
    i0: np.ndarray,
    j0: np.ndarray,
    wi: np.ndarray,
    count: np.ndarray,
    toggles: np.ndarray,
    nk: int,
) -> None:
    owner = np.repeat(np.arange(len(tri)), count)
    local = np.arange(len(owner)) - np.repeat(np.cumsum(count) - count, count)
    ri = i0[owner] + local % wi[owner]
    rj = j0[owner] + local // wi[owner]
    x = ri + 1.234e-4
    y = rj + 2.345e-4
    a, b, c = tri[owner, 0], tri[owner, 1], tri[owner, 2]
    # barycentric coordinates of the ray's (x, y) in the triangle's (i, j) projection
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(d) > 1e-12
    d = np.where(ok, d, 1.0)
    la = ((b[:, 1] - c[:, 1]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (y - c[:, 1])) / d
    lb = ((c[:, 1] - a[:, 1]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (y - c[:, 1])) / d
    lc = 1 - la - lb
    hit = ok & (la >= 0) & (lb >= 0) & (lc >= 0)
    z = la * a[:, 2] + lb * b[:, 2] + lc * c[:, 2]
    kc = np.ceil(z[hit]).astype(np.int64).clip(0, nk)
    np.bitwise_xor.at(toggles, (kc, rj[hit], ri[hit]), 1)


# ── thumbnail ─────────────────────────────────────────────────────────────────


def render_thumb(v: np.ndarray, f: np.ndarray, size: tuple[int, int], color: str) -> np.ndarray:
    """Anterior view (screen x = L, screen up = S), splatted surface samples + z-buffer,
    Lambert shading from the viewer. RGBA uint8 [H, W, 4], transparent background."""
    w_px, h_px = size
    img = np.zeros((h_px, w_px, 4), dtype=np.uint8)
    if not len(f):
        return img
    rng = np.random.default_rng(0)
    if len(f) > 2_000_000:  # a thumbnail doesn't need every triangle
        f = f[rng.choice(len(f), 2_000_000, replace=False)]
    tri = np.asarray(v, np.float64)[f]
    sx, sy, depth = tri[..., 0], -tri[..., 2], tri[..., 1]
    lo_x, hi_x, lo_y, hi_y = sx.min(), sx.max(), sy.min(), sy.max()
    scale = 0.9 * min(w_px / max(hi_x - lo_x, 1e-6), h_px / max(hi_y - lo_y, 1e-6))
    ox = (w_px - (hi_x - lo_x) * scale) / 2
    oy = (h_px - (hi_y - lo_y) * scale) / 2
    px = (sx - lo_x) * scale + ox
    py = (sy - lo_y) * scale + oy
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-30)
    # samples per face ~ its projected area in px² (≥ 1), capped
    area = 0.5 * np.abs(
        (px[:, 1] - px[:, 0]) * (py[:, 2] - py[:, 0])
        - (px[:, 2] - px[:, 0]) * (py[:, 1] - py[:, 0])
    )
    n = np.clip(np.ceil(area * 2), 1, 64).astype(np.int64)
    owner = np.repeat(np.arange(len(f)), n)
    r1, r2 = rng.random(len(owner)), rng.random(len(owner))
    s = np.sqrt(r1)
    bary = np.stack([1 - s, s * (1 - r2), s * r2], axis=1)
    X = (bary * px[owner]).sum(1)
    Y = (bary * py[owner]).sum(1)
    Z = (bary * depth[owner]).sum(1)
    ix = np.clip(X.astype(np.int64), 0, w_px - 1)
    iy = np.clip(Y.astype(np.int64), 0, h_px - 1)
    pix = iy * w_px + ix
    order = np.lexsort((Z, pix))  # nearest to the camera (smallest y) first per pixel
    pix_s = pix[order]
    first = order[np.r_[True, pix_s[1:] != pix_s[:-1]]]
    shade = 0.25 + 0.75 * np.abs(fn[owner[first], 1])
    rgb = np.asarray([int(color[i : i + 2], 16) for i in (1, 3, 5)], np.float64)
    flat = img.reshape(-1, 4)
    flat[pix[first], :3] = np.clip(shade[:, None] * rgb, 0, 255).astype(np.uint8)
    flat[pix[first], 3] = 255
    return _fill_pinholes(img)


def _fill_pinholes(img: np.ndarray) -> np.ndarray:
    """Empty pixels with ≥ 5 of 8 neighbours drawn take their mean (splat gaps, not edges)."""
    a = img[..., 3] > 0
    pad = np.pad(img.astype(np.float32), ((1, 1), (1, 1), (0, 0)))
    pa = np.pad(a, 1)
    h, w = a.shape
    acc = np.zeros((h, w, 3), np.float32)
    cnt = np.zeros((h, w), np.int32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            m = pa[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
            acc += pad[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w, :3] * m[..., None]
            cnt += m
    hole = ~a & (cnt >= 5)
    img[hole, :3] = (acc[hole] / cnt[hole, None]).astype(np.uint8)
    img[hole, 3] = 255
    return img
