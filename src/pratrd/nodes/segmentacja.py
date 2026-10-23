"""Domain "Segmentacja": binary segments (uint8 0/1) and label maps (uint8 0..N).

Every segment carries `info.ref` — the intensity volume it was derived from — so the
viewports can show it as an overlay on its own background. All sizes are physical (mm,
mm³) and all positions are world LPS mm, never voxel indices: the same graph gives the
same physical result on a preview level and at full resolution, and brush strokes / seeds
survive any change of the input geometry.
"""

from typing import Any

import numpy as np
import SimpleITK as sitk

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import VolumeValue, from_sitk, resample_onto, to_sitk
from ..volumes.geometry import Geometry

VOL, SEG, LAB = "wolumen", "segment", "segmentacja"

PALETTE = [
    "#7bc47f",
    "#e05a5a",
    "#5b9bd5",
    "#e8c547",
    "#b48ce0",
    "#4db6ac",
    "#f2994a",
    "#f06292",
    "#c0ca33",
    "#90a4ae",
    "#8d6e63",
    "#26c6da",
]


# ── helpers ────────────────────────────────────────────────────────────────────


def _first(
    inputs: dict[str, list[Any]], port: str, kind: str, required: bool = True
) -> VolumeValue | None:
    for v in inputs.get(port) or []:
        if isinstance(v, VolumeValue) and v.kind == kind:
            return v
    if required:
        raise GraphError("Brak wejścia")
    return None


def _seg_info(name: str, ref: str, color: str = PALETTE[0], **extra: Any) -> dict[str, Any]:
    return {"name": name, "ref": ref, "color": color, **extra}


def _ref_of(v: VolumeValue) -> str:
    """Background (intensity) volume of a value: itself for volumes, its source for masks."""
    return v.ref if v.kind == VOL else v.info.get("ref", "")


def _on_grid(v: VolumeValue, g: Geometry) -> np.ndarray:
    """A label volume resampled (nearest neighbour) onto another grid — e.g. a preview mask
    combined with a full-resolution one, or masks from differently cropped inputs."""
    return resample_onto(v, g, linear=False)


def _world_to_index(g: Geometry, w: list[float]) -> tuple[int, int, int] | None:
    rel = np.asarray(w, dtype=np.float64) - np.asarray(g.origin)
    ijk = (g.matrix.T @ rel) / np.asarray(g.spacing)
    idx = np.rint(ijk).astype(int)
    if np.any(idx < 0) or np.any(idx >= np.asarray(g.size)):
        return None
    return int(idx[0]), int(idx[1]), int(idx[2])


def _radius_vox(g: Geometry, mm: float) -> list[int]:
    return [max(0, int(round(mm / s))) for s in g.spacing]


def _mask_out(ctx: EvalContext, mask: np.ndarray, g: Geometry, info: dict[str, Any]) -> VolumeValue:
    # a contiguous bool mask already IS 0/1 bytes: view it as uint8 instead of copying
    mask = np.ascontiguousarray(mask)
    out = mask.view(np.uint8) if mask.dtype == np.bool_ else mask.astype(np.uint8, copy=False)
    return ctx.volume_result(out, g, info, kind=SEG)


def _slabs(n: int, step: int = 64):
    for k in range(0, n, step):
        yield slice(k, min(n, k + step))


# ── Próg ───────────────────────────────────────────────────────────────────────


def _prog(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    lo, hi = sorted((p["lo"], p["hi"]))
    a = v.array()
    # slab by slab into one byte mask: no full-size temporaries (3 × 0.5 GB on 512²×2000)
    mask = np.empty(a.shape, np.bool_)
    for sl in _slabs(a.shape[0]):
        np.logical_and(a[sl] >= lo, a[sl] <= hi, out=mask[sl])
    return {"out": _mask_out(ctx, mask, v.geometry, _seg_info(f"Próg {lo:g}–{hi:g}", _ref_of(v)))}


register(
    NodeType(
        id="segmentacja/prog",
        label="Próg",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Segment = woksele z wartością w zakresie [od, do]. W CT: kości ≈ 300+, naczynia z kontrastem ≈ 150–600 HU.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param("lo", "Od", "number", 300.0, min=-5000, max=50000, step=1),
            Param("hi", "Do", "number", 3071.0, min=-5000, max=50000, step=1),
        ),
        run=_prog,
        widget="threshold",
    )
)


# ── Otsu ───────────────────────────────────────────────────────────────────────


def _otsu(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    f = sitk.OtsuThresholdImageFilter()
    f.SetInsideValue(0)
    f.SetOutsideValue(1)  # bright class = foreground
    f.SetNumberOfHistogramBins(int(p["bins"]))
    out = f.Execute(to_sitk(v.array(), v.geometry))
    t = float(f.GetThreshold())
    mask, _ = from_sitk(out)
    return {
        "out": _mask_out(ctx, mask, v.geometry, _seg_info(f"Otsu > {t:.0f}", _ref_of(v))),
        "prog": round(t, 3),
    }


register(
    NodeType(
        id="segmentacja/otsu",
        label="Otsu",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Automatyczny próg (metoda Otsu) — dzieli histogram na tło i jasny obiekt. Drugie wyjście: wyliczona wartość progu.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG), Port("prog", "Próg", "liczba")),
        params=(Param("bins", "Koszyki", "int", 256, min=16, max=1024, step=16),),
        run=_otsu,
    )
)


# ── Region growing ──────────────────────────────────────────────────────────────


def _rozrost(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    seeds = [s for s in (_world_to_index(v.geometry, w) for w in p["seeds"]) if s is not None]
    if not seeds:
        raise GraphError("Kliknij ziarno w widoku 2D (narzędzie ziarna)")
    a = v.array()
    # Seed value + the bright side of a 2 mm neighbourhood: a click on the EDGE of a vessel
    # (partial volume, e.g. 449 HU) still reaches its interior (≈ 550 HU) through the 90th
    # percentile, while the surrounding soft tissue stays below seed − tolerance.
    rv = _radius_vox(v.geometry, 2.0)
    vals = []  # value at each seed voxel
    highs = []  # 90th percentile around each seed
    for i, j, k in seeds:
        blk = a[
            max(0, k - rv[2]) : k + rv[2] + 1,
            max(0, j - rv[1]) : j + rv[1] + 1,
            max(0, i - rv[0]) : i + rv[0] + 1,
        ]
        vals.append(float(a[k, j, i]))
        highs.append(float(np.percentile(blk, 90)))
    img = to_sitk(a, v.geometry)
    ctx.report(0.1, "Region growing")
    lo = hi = 0.0
    if p["method"] in ("tol", "zakres"):
        if p["method"] == "tol":
            # grow over values similar to the clicked ones — no HU range to know beforehand
            lo, hi = min(vals) - p["tol"], max(max(vals), max(highs)) + p["tol"]
        else:
            lo, hi = sorted((p["lo"], p["hi"]))
        out = sitk.ConnectedThreshold(
            img, seedList=seeds, lower=float(lo), upper=float(hi), replaceValue=1
        )
    else:
        out = sitk.ConfidenceConnected(
            img,
            seedList=seeds,
            numberOfIterations=int(p["iterations"]),
            multiplier=float(p["multiplier"]),
            initialNeighborhoodRadius=1,
            replaceValue=1,
        )
    mask, _ = from_sitk(out)
    if not mask.any():
        shown = ", ".join(f"{x:g}" for x in vals[:3])
        why = f"poza zakresem {lo:g}–{hi:g}" if p["method"] == "zakres" else "nic podobnego wokół"
        raise GraphError(f"Pusty wynik: ziarno ma wartość {shown} — {why}")
    return {
        "out": _mask_out(
            # already 0/1 (replaceValue=1): no thresholded copy
            ctx,
            mask,
            v.geometry,
            _seg_info(f"Rozrost ({len(seeds)} ziaren)", _ref_of(v)),
        )
    }


register(
    NodeType(
        id="segmentacja/rozrost",
        label="Region growing",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Rośnie od klikniętych ziaren po sąsiednich wokselach. Tolerancja: wartości podobne do ziaren "
        "(± próg); zakres: w przedziale [od, do]; adaptacyjny: według statystyki wokół ziaren.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param("seeds", "Ziarna", "points", []),
            Param(
                "method",
                "Metoda",
                "select",
                "tol",
                options=(("tol", "Tolerancja"), ("zakres", "Zakres"), ("adapt", "Adaptacyjny")),
            ),
            Param("tol", "±", "number", 150.0, min=1, max=2000, step=1, show_if=("method", "tol")),
            Param(
                "lo",
                "Od",
                "number",
                150.0,
                min=-5000,
                max=50000,
                step=1,
                show_if=("method", "zakres"),
            ),
            Param(
                "hi",
                "Do",
                "number",
                600.0,
                min=-5000,
                max=50000,
                step=1,
                show_if=("method", "zakres"),
            ),
            Param(
                "multiplier",
                "Mnożnik",
                "number",
                2.5,
                min=0.5,
                max=6,
                step=0.1,
                show_if=("method", "adapt"),
            ),
            Param(
                "iterations",
                "Iteracje",
                "int",
                3,
                min=0,
                max=10,
                step=1,
                show_if=("method", "adapt"),
            ),
        ),
        run=_rozrost,
        widget="seeds",
    )
)


# ── Edycja (pędzel / gumka) ──────────────────────────────────────────────────────


def _paint(mask: np.ndarray, g: Geometry, center: list[float], r_mm: float, value: int) -> None:
    """Ellipsoid in voxel space = sphere of radius r_mm in the world (anisotropic voxels)."""
    rel = np.asarray(center, dtype=np.float64) - np.asarray(g.origin)
    c = (g.matrix.T @ rel) / np.asarray(g.spacing)  # continuous (i, j, k)
    rv = np.asarray([r_mm / s for s in g.spacing])
    lo = np.maximum(0, np.floor(c - rv)).astype(int)
    hi = np.minimum(np.asarray(g.size) - 1, np.ceil(c + rv)).astype(int)
    if np.any(hi < lo):
        return
    ii = (np.arange(lo[0], hi[0] + 1) - c[0]) / max(rv[0], 1e-9)
    jj = (np.arange(lo[1], hi[1] + 1) - c[1]) / max(rv[1], 1e-9)
    kk = (np.arange(lo[2], hi[2] + 1) - c[2]) / max(rv[2], 1e-9)
    inside = (kk[:, None, None] ** 2 + jj[None, :, None] ** 2 + ii[None, None, :] ** 2) <= 1.0
    view = mask[lo[2] : hi[2] + 1, lo[1] : hi[1] + 1, lo[0] : hi[0] + 1]
    view[inside] = value


def _poly_raster(
    poly: np.ndarray, cell: float | None = None, max_cells: int = 1024
) -> tuple[np.ndarray, np.ndarray, float]:
    """The polygon filled on a grid of its own plane: per-voxel tests become one array lookup
    instead of a point-in-polygon each. `cell` = wanted grid step (½ voxel for a 2-D cut in
    mm); the grid never exceeds max_cells per side (filling 2048² costs ~0.25 s)."""
    from skimage.draw import polygon2mask

    lo = poly.min(axis=0)
    span = float(max((poly.max(axis=0) - lo).max(), 1e-9))
    res = max(cell or 0.0, span / (max_cells - 1))
    n = (np.ceil((poly.max(axis=0) - lo) / res) + 1).astype(int)
    grid = polygon2mask((int(n[1]), int(n[0])), ((poly - lo) / res)[:, ::-1])
    return grid, lo, res


def _cut_extruded(
    mask: np.ndarray,
    g: Geometry,
    A: np.ndarray,
    b: np.ndarray,
    grid: np.ndarray,
    lo: np.ndarray,
    res: float,
    z: list[float] | None,
    mode: str,
) -> bool:
    """Fast path of a 2-D cut along an index axis (a view parallel to the volume's axes — the
    usual case): x, y don't depend on that axis, so the polygon is ONE 2-D mask applied to a
    range of slabs at once (~50 ms instead of ~1 s on 512²×621). False → not applicable."""
    eps = 1e-9
    for a in (2, 1, 0):  # ijk axis the cut extrudes along
        rest = [c for c in (0, 1, 2) if c != a]
        if abs(A[0, a]) > eps or abs(A[1, a]) > eps:
            continue
        if z is not None and (np.any(np.abs(A[2, rest]) > eps) or abs(A[2, a]) < eps):
            continue
        cols, rows = rest  # numpy order [k, j, i]: the larger ijk axis varies slowest
        cc = np.arange(g.size[cols], dtype=np.float64)
        rr = np.arange(g.size[rows], dtype=np.float64)
        x = A[0, cols] * cc[None, :] + A[0, rows] * rr[:, None] + b[0]
        y = A[1, cols] * cc[None, :] + A[1, rows] * rr[:, None] + b[1]
        xi = np.rint((x - lo[0]) / res).astype(np.int64)
        yi = np.rint((y - lo[1]) / res).astype(np.int64)
        ok = (xi >= 0) & (yi >= 0) & (xi < grid.shape[1]) & (yi < grid.shape[0])
        inside = np.zeros(ok.shape, dtype=bool)
        inside[ok] = grid[yi[ok], xi[ok]]
        n = g.size[a]
        t0, t1 = 0, n - 1
        if z is not None:  # z = A[2,a]·t + b[2] within [z0, z1]
            ta, tb = sorted(((z[0] - b[2]) / A[2, a], (z[1] - b[2]) / A[2, a]))
            t0, t1 = max(0, int(np.ceil(ta - 1e-9))), min(n - 1, int(np.floor(tb + 1e-9)))
        view = np.moveaxis(mask, 2 - a, 0)  # (along a, rows, cols)
        if mode == "keep":
            view[:t0] = 0
            view[t1 + 1 :] = 0
            if t0 <= t1:
                view[t0 : t1 + 1, ~inside] = 0
        elif t0 <= t1:
            view[t0 : t1 + 1, inside] = 1 if mode == "add" else 0
        return True
    return False


def _cut(mask: np.ndarray, g: Geometry, st: dict[str, Any]) -> None:
    """Scissors: voxels whose projection (M · world, divided by w) falls inside the polygon
    (and within the z range, if any) are filled (add), cleared (erase) — or everything
    OUTSIDE is cleared (keep). M is affine for a 2-D view, perspective for the 3-D view.

    Per slab k the map (i, j) → (x, y) is a homography; its inverse takes the polygon's
    bounding box back to the few voxels that can be inside, so a cut costs ~ its area, not
    the volume (full 512²×621 volume, unlimited depth: ~1.3 s → well under that)."""
    M = np.asarray(st["M"], dtype=np.float64).reshape(4, 4)
    poly = np.asarray(st["poly"], dtype=np.float64)
    affine = np.allclose(M[3], [0, 0, 0, 1])
    # a 2-D cut is in mm: half the smallest voxel is fine enough; 3-D (tangent space): max grid
    grid, lo, res = _poly_raster(poly, min(g.spacing) / 2 if affine else None)
    hi = lo + (np.asarray(grid.shape[::-1]) - 1) * res
    # world(i,j,k) = origin + D · (spacing ∘ ijk) → q = A · ijk + b (homogeneous)
    A = M[:, :3] @ g.matrix @ np.diag(g.spacing)
    b = M[:, :3] @ np.asarray(g.origin) + M[:, 3]
    ni, nj, nk = g.size
    z = st.get("z")
    keep = st["mode"] == "keep"
    value = 1 if st["mode"] == "add" else 0
    if affine and _cut_extruded(mask, g, A, b, grid, lo, res, z, st["mode"]):
        return
    box = np.array([[lo[0], lo[1], 1], [hi[0], lo[1], 1], [lo[0], hi[1], 1], [hi[0], hi[1], 1]])
    corners = np.array([[0, 0], [ni - 1, 0], [0, nj - 1], [ni - 1, nj - 1]], dtype=np.float64)
    A32 = A.astype(np.float32)
    for k in range(nk):
        if z is not None and affine:
            # one-slice cut: skip slabs entirely outside its depth (z affine → extremes at corners)
            zc = corners @ A[2, :2] + A[2, 2] * k + b[2]
            if zc.max() < z[0] or zc.min() > z[1]:
                if keep:
                    mask[k] = 0
                continue
        i0, i1, j0, j1 = 0, ni, 0, nj
        H = np.array(
            [
                [A[0, 0], A[0, 1], A[0, 2] * k + b[0]],
                [A[1, 0], A[1, 1], A[1, 2] * k + b[1]],
                [A[3, 0], A[3, 1], A[3, 2] * k + b[3]],
            ]
        )
        if abs(np.linalg.det(H)) > 1e-12:
            v = box @ np.linalg.inv(H).T  # bbox corners → (i, j, 1)·s
            if np.all(v[:, 2] > 1e-12):
                ij = v[:, :2] / v[:, 2:3]
                i0 = max(0, int(np.floor(ij[:, 0].min())) - 1)
                i1 = min(ni, int(np.ceil(ij[:, 0].max())) + 2)
                j0 = max(0, int(np.floor(ij[:, 1].min())) - 1)
                j1 = min(nj, int(np.ceil(ij[:, 1].max())) + 2)
        sl = mask[k]
        if i0 >= i1 or j0 >= j1:
            if keep:
                sl[:] = 0
            continue
        # float32 (offsets folded in per slab): ~2× faster than float64, exact enough
        ii = np.arange(i0, i1, dtype=np.float32)
        jj = np.arange(j0, j1, dtype=np.float32)
        q = (
            A32[:, 0][:, None, None] * ii[None, None, :]
            + A32[:, 1][:, None, None] * jj[None, :, None]
            + (A[:, 2] * k + b).astype(np.float32)[:, None, None]
        )  # (4, j, i)
        w = q[3]
        ok = w > 1e-9
        inv = np.float32(1 / res) / np.where(ok, w, np.float32(1))
        xi = np.rint(q[0] * inv - np.float32(lo[0] / res)).astype(np.int32)
        yi = np.rint(q[1] * inv - np.float32(lo[1] / res)).astype(np.int32)
        ok &= (xi >= 0) & (yi >= 0) & (xi < grid.shape[1]) & (yi < grid.shape[0])
        if z is not None:
            zz = q[2] / np.where(ok, w, np.float32(1))
            ok &= (zz >= z[0]) & (zz <= z[1])
        inside = np.zeros_like(ok)
        inside[ok] = grid[yi[ok], xi[ok]]
        sub = sl[j0:j1, i0:i1]
        if keep:
            sub[~inside] = 0
            sl[:j0] = 0
            sl[j1:] = 0
            sl[:, :i0] = 0
            sl[:, i1:] = 0
        else:
            sub[inside] = value


def _edycja(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    seg = _first(inputs, "in", SEG, required=False)
    vol = _first(inputs, "ref", VOL, required=False)
    if seg is not None:
        g, mask, ref = seg.geometry, seg.array().copy(), seg.info.get("ref", "")
    elif vol is not None:
        g, mask, ref = vol.geometry, np.zeros(vol.geometry.shape_kji, np.uint8), vol.ref
    else:
        raise GraphError("Podłącz segment do poprawy albo wolumen (pusty start)")
    # a cut costs about as much as a few hundred brush spheres
    n = sum(400 if st.get("kind") == "cut" else len(st["p"]) for st in p["strokes"]) or 1
    done = 0
    for st in p["strokes"]:
        if st.get("kind") == "cut":
            _cut(mask, g, st)
            done += 400
            ctx.report(done / n, "Nożyce")
            continue
        value = 0 if st["mode"] == "erase" else 1
        for pt in st["p"]:
            _paint(mask, g, pt, st["r"], value)
            done += 1
            if done % 256 == 0:
                ctx.report(done / n, "Pędzel")
    return {
        "out": _mask_out(
            ctx,
            mask,
            g,
            # `strokes`: how many strokes this result contains — the views draw only the newer
            # ones as pending (instant feedback without double-drawing)
            _seg_info(f"Edycja ({len(p['strokes'])} pociągnięć)", ref, strokes=len(p["strokes"])),
        )
    }


register(
    NodeType(
        id="segmentacja/edycja",
        label="Edycja pędzlem",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Ręczna poprawka: pędzel dodaje, gumka usuwa (kule o promieniu w mm). Pociągnięcia są zapisane w "
        "node'zie — po zmianie wejścia nakładają się ponownie.",
        inputs=(
            Port("in", "Segment", SEG, optional=True),
            Port("ref", "Wolumen (pusty start)", VOL, optional=True),
        ),
        outputs=(Port("out", "Segment", SEG),),
        params=(Param("strokes", "Pociągnięcia", "strokes", []),),
        run=_edycja,
        widget="brush",
        version=3,  # 2: info.strokes · 3: scissors cuts
    )
)


# ── Logika ─────────────────────────────────────────────────────────────────────

_OPS = {
    "or": (lambda a, b: a | b, "∪"),
    "and": (lambda a, b: a & b, "∩"),
    "sub": (lambda a, b: a & ~b, "−"),
    "xor": (lambda a, b: a ^ b, "⊕"),
}


def _logika(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    a = _first(inputs, "a", SEG)
    b = _first(inputs, "b", SEG)
    fn, sym = _OPS[p["op"]]
    out = fn(a.array() > 0, _on_grid(b, a.geometry) > 0)
    name = f"{a.info.get('name', 'A')} {sym} {b.info.get('name', 'B')}"
    return {"out": _mask_out(ctx, out, a.geometry, _seg_info(name, a.info.get("ref", "")))}


register(
    NodeType(
        id="segmentacja/logika",
        label="Logika",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Łączy dwa segmenty: suma (A ∪ B), część wspólna (A ∩ B), różnica (A − B), XOR. B jest dopasowywany do siatki A.",
        inputs=(Port("a", "A", SEG), Port("b", "B", SEG)),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "op",
                "Operacja",
                "select",
                "or",
                options=(("or", "∪"), ("and", "∩"), ("sub", "A−B"), ("xor", "⊕")),
            ),
        ),
        run=_logika,
    )
)


# ── Morfologia ─────────────────────────────────────────────────────────────────


def _morfologia(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", SEG)
    img = to_sitk((s.array() > 0).astype(np.uint8), s.geometry)
    rad = _radius_vox(s.geometry, p["radius"])
    op = p["op"]
    ctx.report(0.1, "Morfologia")
    if op == "fill":
        out = sitk.BinaryFillhole(img, fullyConnected=False, foregroundValue=1)
    elif not any(rad):
        out = img
    else:
        f = {
            "dilate": sitk.BinaryDilateImageFilter,
            "erode": sitk.BinaryErodeImageFilter,
            "open": sitk.BinaryMorphologicalOpeningImageFilter,
            "close": sitk.BinaryMorphologicalClosingImageFilter,
        }[op]()
        f.SetKernelRadius(rad)
        f.SetKernelType(sitk.sitkBall)
        f.SetForegroundValue(1)
        out = f.Execute(img)
    mask, _ = from_sitk(out)
    labels = {
        "dilate": "dylatacja",
        "erode": "erozja",
        "open": "otwarcie",
        "close": "zamknięcie",
        "fill": "wypełnienie",
    }
    return {
        "out": _mask_out(
            ctx,
            mask,
            s.geometry,
            _seg_info(
                f"{s.info.get('name', 'Segment')} · {labels[op]}",
                s.info.get("ref", ""),
                s.info.get("color", PALETTE[0]),
            ),
        )
    }


register(
    NodeType(
        id="segmentacja/morfologia",
        label="Morfologia",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Dylatacja (pogrubia), erozja (odchudza), otwarcie (usuwa drobne wypustki), zamknięcie (łata szczeliny), "
        "wypełnienie dziur (zamknięte jamy w środku).",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "op",
                "Operacja",
                "select",
                "close",
                options=(
                    ("dilate", "Dylatacja"),
                    ("erode", "Erozja"),
                    ("open", "Otwarcie"),
                    ("close", "Zamknięcie"),
                    ("fill", "Wypełnij dziury"),
                ),
            ),
            Param("radius", "Promień", "number", 1.0, min=0.1, max=15, step=0.1, unit="mm"),
        ),
        run=_morfologia,
    )
)


# ── Wyspy ──────────────────────────────────────────────────────────────────────


def _wyspy(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", SEG)
    # One copy into ITK, one uint32 label image (4 B/voxel), viewed — never copied — from
    # NumPy. Component sizes are counted in pieces and a keep-table per label picks the
    # result (no RelabelComponent: that was a second 4 B/voxel image, 2 GB on 512²×2000).
    img = to_sitk(s.array(), s.geometry)
    cc = sitk.ConnectedComponent(img, False)  # face connectivity (positional-only in SimpleITK)
    del img
    labels = sitk.GetArrayViewFromImage(cc)
    flat = labels.reshape(-1)
    sizes = np.zeros(1, np.int64)
    for q in range(0, flat.size, 1 << 24):
        c = np.bincount(flat[q : q + (1 << 24)])
        if c.size > sizes.size:
            sizes = np.pad(sizes, (0, c.size - sizes.size))
        sizes[: c.size] += c
    sizes[0] = 0  # background
    vox_mm3 = float(np.prod(s.geometry.spacing))
    keep = np.zeros(sizes.size, np.bool_)
    if p["mode"] == "largest":
        n = int(p["count"])
        top = np.argsort(sizes)[::-1][:n]
        keep[top[sizes[top] > 0]] = True
        tag = f"{n} największ{'a' if n == 1 else 'e'}"
    else:
        min_vox = max(1, int(np.ceil(p["min_mm3"] / vox_mm3)))
        keep[sizes >= min_vox] = True
        keep[0] = False
        tag = f"≥ {p['min_mm3']:g} mm³"
    mask = np.empty(labels.shape, np.bool_)
    for sl in _slabs(labels.shape[0]):
        np.take(keep, labels[sl], out=mask[sl])
    del labels, flat, cc
    return {
        "out": _mask_out(
            ctx,
            mask,
            s.geometry,
            _seg_info(
                f"{s.info.get('name', 'Segment')} · {tag}",
                s.info.get("ref", ""),
                s.info.get("color", PALETTE[0]),
            ),
        )
    }


register(
    NodeType(
        id="segmentacja/wyspy",
        label="Wyspy",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Usuwa drobne, niepołączone kawałki: zostaw N największych albo tylko te większe niż zadana objętość.",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "mode",
                "Tryb",
                "select",
                "largest",
                options=(("largest", "Największe"), ("min", "Min. objętość")),
            ),
            Param("count", "Ile", "int", 1, min=1, max=50, step=1, show_if=("mode", "largest")),
            Param(
                "min_mm3",
                "Min.",
                "number",
                100.0,
                min=1,
                max=1e6,
                step=10,
                unit="mm³",
                show_if=("mode", "min"),
            ),
        ),
        run=_wyspy,
    )
)


# ── Złóż / Rozłóż ───────────────────────────────────────────────────────────────


def _zloz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    segs = [v for v in inputs.get("in") or [] if isinstance(v, VolumeValue) and v.kind == SEG]
    if not segs:
        raise GraphError("Podłącz co najmniej jeden segment")
    g = segs[0].geometry
    lab = np.zeros(g.shape_kji, np.uint8)
    table = []
    for n, s in enumerate(segs[:255], start=1):
        lab[_on_grid(s, g) > 0] = n  # later inputs win where segments overlap
        table.append(
            {
                "id": n,
                "name": s.info.get("name", f"Segment {n}"),
                "color": PALETTE[(n - 1) % len(PALETTE)],
            }
        )
    info = {
        "name": f"Segmentacja ({len(table)})",
        "ref": segs[0].info.get("ref", ""),
        "labels": table,
    }
    return {"out": ctx.volume_result(lab, g, info, kind=LAB)}


register(
    NodeType(
        id="segmentacja/zloz",
        label="Złóż",
        domain="segmentacja",
        stage="wynik",
        description="Łączy kilka segmentów w jedną segmentację (mapę etykiet) — każdy dostaje własny kolor.",
        inputs=(Port("in", "Segmenty", SEG, multi=True),),
        outputs=(Port("out", "Segmentacja", LAB),),
        params=(),
        run=_zloz,
    )
)


def _rozloz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", LAB)
    lid = int(p["label"])
    entry = next(
        (e for e in s.info.get("labels", []) if e["id"] == lid),
        {"name": f"Etykieta {lid}", "color": PALETTE[0]},
    )
    mask = s.array() == lid
    return {
        "out": _mask_out(
            ctx, mask, s.geometry, _seg_info(entry["name"], s.info.get("ref", ""), entry["color"])
        )
    }


register(
    NodeType(
        id="segmentacja/rozloz",
        label="Rozłóż",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Wyciąga jeden segment (etykietę) z segmentacji.",
        inputs=(Port("in", "Segmentacja", LAB),),
        outputs=(Port("out", "Segment", SEG),),
        params=(Param("label", "Etykieta", "int", 1, min=1, max=255, step=1),),
        run=_rozloz,
    )
)


# ── Import labelmapy ───────────────────────────────────────────────────────────


def _import(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = ctx.source_volume(p["volume"], exact=True)  # labels must never be averaged: level 0
    a = v.array()
    if a.dtype.kind == "f" and not np.all(np.mod(a, 1) == 0):
        raise GraphError("To nie jest mapa etykiet (wartości niecałkowite)")
    ids = [int(x) for x in np.unique(a) if x > 0]
    if len(ids) > 255:
        raise GraphError(f"Za dużo etykiet ({len(ids)}) — maks. 255")
    lab = np.zeros(a.shape, np.uint8)
    names = {int(e["id"]): e["name"] for e in v.info.get("labels", [])}
    table = []
    for n, lid in enumerate(ids, start=1):
        lab[a == lid] = n
        table.append(
            {
                "id": n,
                "name": names.get(lid, f"Etykieta {lid}"),
                "color": PALETTE[(n - 1) % len(PALETTE)],
            }
        )
    ref = p.get("ref") or v.ref
    info = {"name": v.info.get("name", "Labelmapa"), "ref": ref, "labels": table}
    return {"out": ctx.volume_result(lab, v.geometry, info, kind=LAB)}


register(
    NodeType(
        id="segmentacja/import",
        label="Labelmapa",
        domain="segmentacja",
        stage="dane",
        description="Mapa etykiet z biblioteki (np. NIfTI z innego programu) jako segmentacja. Opcjonalnie wskaż obraz, "
        "na którym ma być pokazywana.",
        inputs=(),
        outputs=(Port("out", "Segmentacja", LAB),),
        params=(Param("volume", "Labelmapa", "volume", ""), Param("ref", "Tło", "volume", "")),
        run=_import,
    )
)
