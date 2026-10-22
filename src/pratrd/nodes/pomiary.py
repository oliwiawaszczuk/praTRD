"""Domain "Pomiary i statystyki": markups placed in the views, segment statistics,
histograms and intensity profiles. Results are tables ("tabela": columns + rows, optionally
a chart hint for the node card) that the UI shows and exports to CSV.

Volumes are physical: voxel count × voxel volume (what Slicer's Segment Statistics reports
as "Volume"), surface from marching cubes, lengths and angles in world LPS mm.
"""

import math
from typing import Any

import numpy as np

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import DataValue, VolumeValue, resample_onto
from ..volumes.geometry import Geometry

VOL, SEG, LAB, PTS, TAB = "wolumen", "segment", "segmentacja", "punkty", "tabela"


def table(
    columns: list[tuple[str, str, str]],
    rows: list[dict[str, Any]],
    chart: dict[str, Any] | None = None,
    title: str = "",
) -> DataValue:
    """columns: (key, label, unit). Floats rounded for the UI/CSV (no false precision)."""
    clean = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    return DataValue(
        TAB,
        {
            "title": title,
            "columns": [{"key": k, "label": lbl, "unit": u} for k, lbl, u in columns],
            "rows": clean,
            "chart": chart,
        },
    )


def _first(inputs: dict, port: str) -> Any:
    vals = inputs.get(port) or []
    return vals[0] if vals else None


# ── Markupy ─────────────────────────────────────────────────────────────────────

MARKUP_LABEL = {"point": "Punkt", "line": "Linijka", "angle": "Kąt", "roi": "ROI"}


def markup_measure(m: dict[str, Any]) -> tuple[float | None, str]:
    """The headline number of a markup: length, angle or ROI volume."""
    p = np.asarray(m["p"], dtype=np.float64)
    if m["type"] == "line":
        return float(np.linalg.norm(p[1] - p[0])), "mm"
    if m["type"] == "angle":
        a, b = p[0] - p[1], p[2] - p[1]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0, "°"
        return math.degrees(math.acos(float(np.clip(a @ b / (na * nb), -1, 1)))), "°"
    if m["type"] == "roi":
        return float(np.prod(np.abs(p[1] - p[0]))) / 1000.0, "ml"
    return None, ""


def _markupy(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    items, rows = [], []
    for n, m in enumerate(p["items"], 1):
        value, unit = markup_measure(m)
        name = m["name"] or f"{MARKUP_LABEL[m['type']]} {n}"
        items.append({**m, "name": name, "value": value, "unit": unit})
        c = np.mean(np.asarray(m["p"]), axis=0)
        size = (
            np.abs(np.asarray(m["p"][-1]) - np.asarray(m["p"][0])) if m["type"] == "roi" else None
        )
        rows.append(
            {
                "name": name,
                "type": MARKUP_LABEL[m["type"]],
                "value": value,
                "unit": unit,
                "x": float(c[0]),
                "y": float(c[1]),
                "z": float(c[2]),
                "size": " × ".join(f"{s:.1f}" for s in size) if size is not None else "",
            }
        )
    tab = table(
        [
            ("name", "Nazwa", ""),
            ("type", "Typ", ""),
            ("value", "Wartość", ""),
            ("unit", "Jedn.", ""),
            ("x", "L", "mm"),
            ("y", "P", "mm"),
            ("z", "S", "mm"),
            ("size", "Wymiary ROI", "mm"),
        ],
        rows,
        title="Markupy",
    )
    return {"out": DataValue(PTS, {"items": items}), "tab": tab}


register(
    NodeType(
        id="pomiary/markupy",
        label="Markupy",
        domain="pomiary",
        stage="dane",
        description="Punkty, linijki (odległość), kąty i pudełka ROI stawiane w widokach. Pozycje w mm (LPS) — "
        "przeżywają zmianę wolumenu. Wyjścia: punkty (np. linia dla profilu) i tabela pomiarów.",
        inputs=(),
        outputs=(Port("out", "Punkty", PTS), Port("tab", "Tabela", TAB)),
        params=(Param("items", "Markupy", "markups", []),),
        run=_markupy,
        widget="markups",
    )
)


# ── Statystyki segmentu ─────────────────────────────────────────────────────────


def _labels_of(inputs: dict) -> tuple[VolumeValue, list[dict[str, Any]]]:
    seg = _first(inputs, "seg")
    lab = _first(inputs, "lab")
    v = seg or lab
    if not isinstance(v, VolumeValue):
        raise GraphError("Podłącz segment albo segmentację")
    if v.kind == SEG:
        return v, [
            {"id": 1, "name": v.info.get("name", "Segment"), "color": v.info.get("color", "")}
        ]
    labels = v.info.get("labels") or []
    if not labels:
        ids = np.unique(v.array())
        labels = [{"id": int(i), "name": f"Segment {int(i)}", "color": ""} for i in ids if i]
    return v, labels


def _surface_mm2(mask: np.ndarray, g: Geometry) -> float:
    """Marching cubes on the label's bounding box (padded so the surface is closed). A light
    Gaussian (σ 0.6 voxel, like Slicer's surface smoothing) removes the voxel staircase,
    which alone overestimates the area by 3–9 %; σ 0.6 stays within ±4 % from 4 mm to 30 mm
    spheres without shrinking small objects."""
    from scipy.ndimage import gaussian_filter
    from skimage.measure import marching_cubes, mesh_surface_area

    idx = np.nonzero(mask)
    if not idx[0].size:
        return 0.0
    lo = [int(a.min()) for a in idx]
    hi = [int(a.max()) + 1 for a in idx]
    sub = gaussian_filter(
        np.pad(mask[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]], 2).astype(np.float32), 0.6
    )
    verts, faces, _, _ = marching_cubes(
        sub, 0.5, spacing=(g.spacing[2], g.spacing[1], g.spacing[0])
    )
    return float(mesh_surface_area(verts, faces))


def _statystyki(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v, labels = _labels_of(inputs)
    g = v.geometry
    lab = v.array()
    intensity = _first(inputs, "vol")
    if intensity is None and v.info.get("ref"):
        intensity = ctx.volume_by_ref(v.info["ref"])
    vals = resample_onto(intensity, g, linear=True) if intensity is not None else None
    vox_mm3 = float(np.prod(g.spacing))
    rows = []
    for n, lb in enumerate(labels):
        ctx.report(n / max(len(labels), 1), "Statystyki")
        m = lab == lb["id"]
        count = int(m.sum())
        row: dict[str, Any] = {
            "name": lb["name"],
            "color": lb.get("color", ""),
            "voxels": count,
            "mm3": count * vox_mm3,
            "ml": count * vox_mm3 / 1000.0,
            "surface": _surface_mm2(m, g) if p["surface"] else None,
        }
        if vals is not None and count:
            x = vals[m].astype(np.float64)
            row |= {
                "min": float(x.min()),
                "max": float(x.max()),
                "mean": float(x.mean()),
                "sd": float(x.std()),
                "median": float(np.median(x)),
            }
        rows.append(row)
    cols = [
        ("name", "Segment", ""),
        ("voxels", "Woksele", ""),
        ("mm3", "Objętość", "mm³"),
        ("ml", "Objętość", "ml"),
        ("surface", "Powierzchnia", "mm²"),
        ("min", "Min", ""),
        ("max", "Max", ""),
        ("mean", "Średnia", ""),
        ("sd", "SD", ""),
        ("median", "Mediana", ""),
    ]
    chart = {"type": "bars", "label": "name", "value": "ml", "color": "color"}
    return {"tab": table(cols, rows, chart, title="Statystyki segmentów")}


register(
    NodeType(
        id="pomiary/statystyki",
        label="Statystyki segmentu",
        domain="pomiary",
        stage="wynik",
        description="Objętość (mm³, ml), liczba wokseli, powierzchnia i statystyki intensywności (min, max, średnia, "
        "SD, mediana) dla segmentu lub każdej etykiety segmentacji. Intensywność: podłączony wolumen albo tło segmentu.",
        inputs=(
            Port("seg", "Segment", SEG, optional=True),
            Port("lab", "Segmentacja", LAB, optional=True),
            Port("vol", "Wolumen (intensywność)", VOL, optional=True),
        ),
        outputs=(Port("tab", "Tabela", TAB),),
        params=(Param("surface", "Powierzchnia", "bool", True),),
        run=_statystyki,
        cost="heavy",
    )
)


# ── Histogram ───────────────────────────────────────────────────────────────────


def _histogram(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "vol")
    if not isinstance(v, VolumeValue):
        raise GraphError("Brak wejścia")
    a = v.array()
    seg = _first(inputs, "seg")
    x = a[resample_onto(seg, v.geometry, linear=False) > 0] if seg is not None else a.ravel()
    if not x.size:
        raise GraphError("Pusty segment — brak wokseli do policzenia")
    lo, hi = float(x.min()), float(x.max())
    if p["auto"] == "p":  # robust range: ignores air / metal outliers
        lo, hi = (float(q) for q in np.percentile(x, [0.5, 99.5]))
    if hi <= lo:
        hi = lo + 1
    counts, edges = np.histogram(x, bins=p["bins"], range=(lo, hi))
    rows = [
        {"from": float(edges[n]), "to": float(edges[n + 1]), "count": int(c)}
        for n, c in enumerate(counts)
    ]
    cols = [("from", "Od", ""), ("to", "Do", ""), ("count", "Liczba", "vox")]
    chart = {"type": "histogram", "x": "from", "y": "count"}
    return {"tab": table(cols, rows, chart, title="Histogram")}


register(
    NodeType(
        id="pomiary/histogram",
        label="Histogram",
        domain="pomiary",
        stage="wynik",
        description="Rozkład wartości wolumenu — całego albo tylko wewnątrz segmentu.",
        inputs=(Port("vol", "Wolumen", VOL), Port("seg", "Segment (maska)", SEG, optional=True)),
        outputs=(Port("tab", "Tabela", TAB),),
        params=(
            Param("bins", "Koszyki", "int", 128, min=8, max=1024, step=8),
            Param(
                "auto",
                "Zakres",
                "select",
                "p",
                options=(("p", "0,5–99,5 percentyl"), ("minmax", "Min–max")),
            ),
        ),
        run=_histogram,
    )
)


# ── Profil ──────────────────────────────────────────────────────────────────────


def _profil(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    from scipy.ndimage import map_coordinates

    v = _first(inputs, "vol")
    pts = _first(inputs, "pts")
    if not isinstance(v, VolumeValue) or pts is None:
        raise GraphError("Brak wejścia")
    lines = [m for m in pts.value.get("items", []) if m["type"] == "line"]
    if not lines:
        raise GraphError("Postaw linijkę w node'zie Markupy")
    m = lines[min(p["line"], len(lines)) - 1]
    a_w, b_w = np.asarray(m["p"][0], dtype=np.float64), np.asarray(m["p"][1], dtype=np.float64)
    length = float(np.linalg.norm(b_w - a_w))
    g = v.geometry
    step = min(g.spacing) / 2
    n = int(min(4000, max(2, math.ceil(length / step) + 1)))
    t = np.linspace(0.0, 1.0, n)
    world = a_w[None, :] + t[:, None] * (b_w - a_w)[None, :]
    ijk = ((world - np.asarray(g.origin)) @ g.matrix) / np.asarray(g.spacing)  # (n, 3) i,j,k
    vals = map_coordinates(v.array(), [ijk[:, 2], ijk[:, 1], ijk[:, 0]], order=1, mode="nearest")
    inside = np.all((ijk > -0.5) & (ijk < np.asarray(g.size) - 0.5), axis=1)
    rows = [
        {"mm": float(tt * length), "value": float(val) if ok else None}
        for tt, val, ok in zip(t, vals, inside, strict=True)
    ]
    cols = [("mm", "Odległość", "mm"), ("value", "Wartość", "")]
    chart = {"type": "line", "x": "mm", "y": "value"}
    return {"tab": table(cols, rows, chart, title=f"Profil: {m['name'] or 'linijka'}")}


register(
    NodeType(
        id="pomiary/profil",
        label="Profil",
        domain="pomiary",
        stage="wynik",
        description="Wartości wolumenu wzdłuż linijki z node'a Markupy (interpolacja liniowa co ½ woksela).",
        inputs=(Port("vol", "Wolumen", VOL), Port("pts", "Punkty", PTS)),
        outputs=(Port("tab", "Tabela", TAB),),
        params=(Param("line", "Linijka nr", "int", 1, min=1, max=50, step=1),),
        run=_profil,
    )
)
