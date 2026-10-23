"""Domain "Mesh": surfaces of segments, smoothing, decimation, imported STL/OBJ/PLY and the way
back to a segment. Vertices are world LPS mm, so a mesh lines up with every volume in the
scene whatever grid it came from; parameters are physical (mm, %), never voxels.

Export (STL / OBJ / PLY) is a button on the node card, like CSV for tables — not a node.
"""

from typing import Any

import numpy as np

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import MeshValue, VolumeValue
from ..meshes import io, ops
from .pomiary import table

VOL, SEG, MESH, TAB = "wolumen", "segment", "mesh", "tabela"


def _mesh(inputs: dict, port: str = "in") -> MeshValue:
    for v in inputs.get(port) or []:
        if isinstance(v, MeshValue):
            return v
    raise GraphError("Brak mesha na wejściu")


def _carry(m: MeshValue, suffix: str) -> dict[str, Any]:
    """Identity of the surface that flows on (name, colour, background) — not its stats."""
    info = {k: m.info[k] for k in ("name", "color", "ref", "source", "space") if k in m.info}
    info["name"] = f"{m.info.get('name', 'Mesh')} · {suffix}"
    return info


# ── Z segmentu ─────────────────────────────────────────────────────────────────


def _z_segmentu(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    seg = next((v for v in inputs.get("in") or [] if isinstance(v, VolumeValue)), None)
    if seg is None or seg.kind != SEG:
        raise GraphError("Podłącz segment")
    mask = seg.array()
    verts, faces = ops.from_mask(mask, seg.geometry, p["smooth"], lambda f: ctx.report(0.9 * f))
    if not len(faces):
        raise GraphError("Segment jest pusty")
    info = {
        "name": f"{seg.info.get('name', 'Segment')} · mesh",
        "color": seg.info.get("color", "#7bc47f"),
        "ref": seg.info.get("ref", ""),
    }
    return {"out": ctx.mesh_result(verts, faces, info)}


register(
    NodeType(
        id="mesh/z_segmentu",
        label="Mesh z segmentu",
        domain="mesh",
        stage="przetwarzanie",
        description="Powierzchnia segmentu (marching cubes na poziomie 0,5) po wygładzeniu maski filtrem Gaussa o σ w mm — "
        "bez schodków wokseli. 0 mm = surowe woksele. Mesh jest zamknięty i zorientowany na zewnątrz; jego objętość "
        "zwykle mieści się w 1% objętości segmentu. Cienkie struktury (1–2 woksele) większe σ wygładza kosztem "
        "objętości — wtedy zmniejsz σ.",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Mesh", MESH),),
        params=(
            Param(
                "smooth",
                "Wygładź σ",
                "number",
                0.3,
                min=0,
                max=3,
                step=0.1,
                unit="mm",
                help="Gauss na masce przed marching cubes; 0 = schodki wokseli",
            ),
        ),  # fmt: skip
        run=_z_segmentu,
        cost="heavy",
    )
)


# ── Wygładź ────────────────────────────────────────────────────────────────────


def _wygladz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    m = _mesh(inputs)
    v, f = m.arrays()
    out = ops.smooth(v, f, p["iterations"], p["method"], p["strength"], lambda x: ctx.report(x))
    return {"out": ctx.mesh_result(out, f, _carry(m, "wygładzony"))}


register(
    NodeType(
        id="mesh/wygladz",
        label="Wygładź mesh",
        domain="mesh",
        stage="przetwarzanie",
        description="Wygładzanie powierzchni bez zmiany liczby trójkątów. **Taubin** (domyślnie) na przemian wygładza i "
        "„pompuje” z powrotem — objętość prawie się nie zmienia. **Laplace** jest mocniejszy, ale kurczy obiekt.",
        inputs=(Port("in", "Mesh", MESH),),
        outputs=(Port("out", "Mesh", MESH),),
        params=(
            Param(
                "method",
                "Metoda",
                "select",
                "taubin",
                options=(("taubin", "Taubin"), ("laplace", "Laplace")),
            ),
            Param("iterations", "Iteracje", "int", 20, min=0, max=200, step=1),
            Param("strength", "Siła", "number", 0.5, min=0.05, max=0.9, step=0.05),
        ),
        run=_wygladz,
    )
)


# ── Decymacja ──────────────────────────────────────────────────────────────────


def _decymuj(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    m = _mesh(inputs)
    v, f = m.arrays()
    ctx.report(0.1, "Decymacja")
    v2, f2 = ops.decimate(v, f, p["keep"] / 100.0)
    return {"out": ctx.mesh_result(v2, f2, _carry(m, f"{p['keep']:g}%"))}


register(
    NodeType(
        id="mesh/decymuj",
        label="Decymacja",
        domain="mesh",
        stage="przetwarzanie",
        description="Mniej trójkątów przy tym samym kształcie (zwijanie krawędzi z błędem kwadrykowym). Lżejszy plik STL "
        "i płynniejszy widok 3D; 10–25% zwykle nie zmienia wyglądu ani objętości.",
        inputs=(Port("in", "Mesh", MESH),),
        outputs=(Port("out", "Mesh", MESH),),
        params=(
            Param(
                "keep",
                "Zostaw",
                "number",
                25,
                min=1,
                max=100,
                step=1,
                unit="%",
                help="Docelowy odsetek trójkątów",
            ),
        ),  # fmt: skip
        run=_decymuj,
        cost="heavy",
    )
)


# ── Plik mesha (import) ──────────────────────────────────────────────────────────


def _plik(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    m = ctx.library_mesh(p["mesh"])
    bg = next((v for v in inputs.get("vol") or [] if isinstance(v, VolumeValue)), None)
    space = m.info.get("space", "LPS") if p["space"] == "auto" else p["space"]
    ref = bg.ref if bg is not None else ""
    if space == "LPS":  # the library mesh itself (the background only lives in `info`)
        return {"out": MeshValue(ref=m.ref, path=m.path, info={**m.info, "ref": ref})}
    v, f = m.arrays()
    info = {k: m.info[k] for k in ("name", "color", "source") if k in m.info}
    info |= {"space": "LPS", "ref": ref}
    return {"out": ctx.mesh_result(io.lps_to(space, np.asarray(v, np.float64)), f, info)}


register(
    NodeType(
        id="mesh/plik",
        label="Plik mesha",
        domain="mesh",
        stage="dane",
        description="Mesh z pliku STL, OBJ lub PLY (np. model ze Slicera albo z drukarki 3D). Układ współrzędnych: "
        "„auto” czyta nagłówek pliku (Slicer zapisuje SPACE=LPS/RAS), bez nagłówka przyjmuje LPS. "
        "Jeśli mesh jest odbity względem obrazu, przełącz na RAS. Opcjonalne tło = wolumen pokazywany pod meshem.",
        inputs=(Port("vol", "Tło", VOL, optional=True),),
        outputs=(Port("out", "Mesh", MESH),),
        params=(
            Param("mesh", "Plik", "mesh", ""),
            Param(
                "space",
                "Układ",
                "select",
                "auto",
                options=(("auto", "auto"), ("LPS", "LPS"), ("RAS", "RAS")),
                help="LPS: DICOM / ITK / Slicer ≥ 4.11; RAS: starsze pliki Slicera, FreeSurfer",
            ),
        ),  # fmt: skip
        run=_plik,
    )
)


# ── Do segmentu (wokselizacja) ───────────────────────────────────────────────────


def _do_segmentu(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    m = _mesh(inputs)
    grid = next((v for v in inputs.get("vol") or [] if isinstance(v, VolumeValue)), None)
    if grid is None:
        raise GraphError("Podłącz wolumen (siatka wokseli)")
    if not m.info.get("closed", True):
        raise GraphError(
            f"Mesh nie jest zamknięty ({m.info.get('boundary', '?')} otwartych krawędzi) — "
            "wnętrze jest nieokreślone"
        )
    v, f = m.arrays()
    mask = ops.voxelize(v, f, grid.geometry, lambda x: ctx.report(0.8 * x))
    ref = grid.ref if grid.kind == VOL else grid.info.get("ref", "")
    info = {"name": m.info.get("name", "Mesh"), "color": m.info.get("color", "#e8c547"), "ref": ref}
    return {"out": ctx.volume_result(mask, grid.geometry, info, kind=SEG)}


register(
    NodeType(
        id="mesh/do_segmentu",
        label="Mesh → segment",
        domain="mesh",
        stage="przetwarzanie",
        description="Wnętrze zamkniętego mesha jako segment na siatce podłączonego wolumenu (woksel należy do segmentu, "
        "gdy jego środek leży w środku mesha). Np. model STL → objętość, statystyki intensywności, maska do edycji.",
        inputs=(Port("in", "Mesh", MESH), Port("vol", "Siatka (wolumen)", VOL)),
        outputs=(Port("out", "Segment", SEG),),
        params=(),
        run=_do_segmentu,
        cost="heavy",
    )
)


# ── Statystyki mesha ───────────────────────────────────────────────────────────


def _statystyki(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    meshes = [v for v in inputs.get("in") or [] if isinstance(v, MeshValue)]
    if not meshes:
        raise GraphError("Brak mesha na wejściu")
    rows = []
    for m in meshes:
        i = m.info
        b = i.get("bounds") or [0.0] * 6
        rows.append(
            {
                "name": i.get("name", "Mesh"),
                "color": i.get("color", ""),
                "faces": i.get("faces", 0),
                "verts": i.get("verts", 0),
                "area": float(i.get("area", 0.0)),
                "ml": float(i.get("ml", 0.0)) if i.get("closed") else None,
                "closed": "tak" if i.get("closed") else f"nie ({i.get('boundary', 0)} krawędzi)",
                "size": " × ".join(f"{b[2 * n + 1] - b[2 * n]:.1f}" for n in range(3)),
            }
        )
    cols = [
        ("name", "Mesh", ""),
        ("faces", "Trójkąty", ""),
        ("verts", "Wierzchołki", ""),
        ("area", "Powierzchnia", "mm²"),
        ("ml", "Objętość", "ml"),
        ("closed", "Zamknięty", ""),
        ("size", "Wymiary L × P × S", "mm"),
    ]
    chart = {"type": "bars", "label": "name", "value": "area", "color": "color"}
    return {"tab": table(cols, rows, chart, title="Statystyki meshy")}


register(
    NodeType(
        id="mesh/statystyki",
        label="Statystyki mesha",
        domain="mesh",
        stage="wynik",
        description="Liczba trójkątów i wierzchołków, powierzchnia (mm²), objętość (ml — tylko dla zamkniętego mesha, "
        "z twierdzenia o dywergencji) i wymiary pudełka. Można podłączyć kilka meshy.",
        inputs=(Port("in", "Mesh", MESH, multi=True),),
        outputs=(Port("tab", "Tabela", TAB),),
        params=(),
        run=_statystyki,
    )
)
