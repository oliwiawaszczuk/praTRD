"""Domain "Wolumen": source + the minimum segmentation needs (crop, resample, smooth).

Parameters are physical (mm), never voxels: the same graph gives the same physical result
on the preview level and at full resolution.
"""

from typing import Any

import numpy as np
import SimpleITK as sitk

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import VolumeValue, from_sitk, to_sitk
from ..volumes.geometry import Geometry

VOL = "wolumen"


def _one(inputs: dict[str, list[Any]], port: str) -> VolumeValue:
    vals = inputs.get(port) or []
    if not vals or not isinstance(vals[0], VolumeValue):
        raise GraphError("Brak wolumenu na wejściu")
    return vals[0]


def _info(v: VolumeValue, suffix: str) -> dict[str, Any]:
    info = dict(v.info)
    info["name"] = f"{v.info.get('name', 'Wolumen')} · {suffix}"
    return info


# ── Seria ──────────────────────────────────────────────────────────────────────


def _seria(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    return {"out": ctx.source_volume(p["volume"])}


register(
    NodeType(
        id="wolumen/seria",
        label="Seria",
        domain="wolumen",
        stage="dane",
        description=(
            "Wolumen z biblioteki workspace'u (zakładka Dane). W podglądzie używany jest "
            "poziom piramidy ≤ ~16 M wokseli, w pełnej rozdzielczości — oryginał."
        ),
        inputs=(),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(Param("volume", "Seria", "volume", ""),),
        run=_seria,
    )
)


# ── Przytnij ───────────────────────────────────────────────────────────────────


def _przytnij(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _one(inputs, "in")
    g = v.geometry
    lo, hi = [], []
    for ax, n in zip("ijk", g.size, strict=True):
        a, b = sorted((p[f"{ax}0"], p[f"{ax}1"]))
        i0 = int(np.floor(a / 100 * n))
        i1 = max(i0 + 1, int(np.ceil(b / 100 * n)))
        lo.append(min(i0, n - 1))
        hi.append(min(i1, n))
    arr = v.array()[lo[2] : hi[2], lo[1] : hi[1], lo[0] : hi[0]]
    origin = np.asarray(g.origin) + g.matrix @ (np.asarray(g.spacing) * np.asarray(lo))
    out_g = Geometry(
        size=(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]),
        spacing=g.spacing,
        origin=tuple(float(x) for x in origin),
        direction=g.direction,
    )
    return {"out": ctx.volume_result(arr, out_g, _info(v, "przycięty"))}


_crop_params = tuple(
    Param(
        f"{ax}{e}",
        f"{name} {'od' if e == '0' else 'do'}",
        "number",
        0.0 if e == "0" else 100.0,
        min=0,
        max=100,
        step=0.5,
        unit="%",
    )
    for ax, name in (("i", "Oś i"), ("j", "Oś j"), ("k", "Oś k"))
    for e in ("0", "1")
)

register(
    NodeType(
        id="wolumen/przytnij",
        label="Przytnij",
        domain="wolumen",
        stage="przetwarzanie",
        description=(
            "Wycina prostopadłościenny obszar (ROI). Box ustawiasz w 3D, przeciągając ściany. "
            "Mniejszy wolumen = szybsze kolejne operacje."
        ),
        widget="cropbox",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=_crop_params,
        run=_przytnij,
    )
)


# ── Resampluj ──────────────────────────────────────────────────────────────────

_INTERP = {
    "linear": sitk.sitkLinear,
    "nearest": sitk.sitkNearestNeighbor,
    "bspline": sitk.sitkBSpline,
}


def _resampluj(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _one(inputs, "in")
    g = v.geometry
    target = float(p["spacing"])
    if ctx.quality == "preview":
        # never upsample a preview level — that would cost more than full resolution
        target = max(target, min(g.spacing))
    extent = np.asarray(g.size) * np.asarray(g.spacing)
    size = [max(1, int(round(e / target))) for e in extent]
    # keep the physical box: first voxel centre moves by half the size change
    first = np.asarray(g.origin) + g.matrix @ ((np.full(3, target) - np.asarray(g.spacing)) / 2)
    ref = sitk.Image(size, sitk.sitkFloat32)
    ref.SetSpacing([target] * 3)
    ref.SetOrigin([float(x) for x in first])
    ref.SetDirection(g.direction)
    ctx.report(0.1, "Resampling")
    img = to_sitk(v.array(), g)
    out = sitk.Resample(
        img,
        ref,
        sitk.Transform(),
        _INTERP[p["interpolation"]],
        float(v.array().min()),
        img.GetPixelID(),
    )
    arr, out_g = from_sitk(out)
    return {"out": ctx.volume_result(arr, out_g, _info(v, f"{target:g} mm"))}


register(
    NodeType(
        id="wolumen/resampluj",
        label="Resampluj",
        domain="wolumen",
        stage="przetwarzanie",
        description=(
            "Zmienia rozdzielczość na izotropową (ten sam rozmiar woksela w każdej osi). "
            "Przydatne przed operacjami morfologicznymi i do zrównania serii."
        ),
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param("spacing", "Woksel", "number", 1.0, min=0.1, max=10, step=0.05, unit="mm"),
            Param(
                "interpolation",
                "Interpolacja",
                "select",
                "linear",
                options=(
                    ("linear", "Liniowa"),
                    ("bspline", "B-spline"),
                    ("nearest", "Najbliższy sąsiad"),
                ),
            ),
        ),
        run=_resampluj,
    )
)


# ── Wygładź ────────────────────────────────────────────────────────────────────


def _cast_like(arr: np.ndarray, like: np.dtype) -> np.ndarray:
    if np.issubdtype(like, np.integer):
        info = np.iinfo(like)
        return np.clip(np.rint(arr), info.min, info.max).astype(like)
    return arr.astype(like, copy=False)


def _wygladz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _one(inputs, "in")
    g = v.geometry
    src = v.array()
    img = to_sitk(src, g)
    ctx.report(0.05, "Wygładzanie")
    if p["method"] == "gauss":
        out = sitk.SmoothingRecursiveGaussian(sitk.Cast(img, sitk.sitkFloat32), float(p["sigma"]))
        suffix = f"Gauss σ {p['sigma']:g} mm"
    else:
        # radius in mm → voxels per axis (≥ 0), so preview and full match physically
        rad = [int(round(float(p["radius"]) / s)) for s in g.spacing]
        out = sitk.Median(img, rad) if any(rad) else img
        suffix = f"mediana r {p['radius']:g} mm"
    arr, _ = from_sitk(out)
    return {"out": ctx.volume_result(_cast_like(arr, src.dtype), g, _info(v, suffix))}


register(
    NodeType(
        id="wolumen/wygladz",
        label="Wygładź",
        domain="wolumen",
        stage="przetwarzanie",
        description=(
            "Redukcja szumu przed progowaniem. Gauss — szybki, rozmywa krawędzie; mediana — "
            "zachowuje krawędzie, usuwa szum typu sól-pieprz, wolniejsza."
        ),
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "method",
                "Metoda",
                "select",
                "gauss",
                options=(("gauss", "Gauss"), ("median", "Mediana")),
            ),
            Param(
                "sigma",
                "σ",
                "number",
                1.0,
                min=0.1,
                max=10,
                step=0.1,
                unit="mm",
                show_if=("method", "gauss"),
            ),
            Param(
                "radius",
                "Promień",
                "number",
                1.0,
                min=0.1,
                max=10,
                step=0.1,
                unit="mm",
                show_if=("method", "median"),
            ),
        ),
        run=_wygladz,
    )
)
