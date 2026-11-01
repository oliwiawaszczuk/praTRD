"""Test run of a node draft (not saved yet) on a phantom, a library series or a node of the
active graph. Runs through the normal evaluator, so the result is exactly what the node
would produce in a graph — plus prints, output stats and automatic checks."""

from typing import Any

import numpy as np

from ..graph.evaluator import EvalContext, Evaluator
from ..graph.types import NodeType, Port
from ..jobs import Job
from ..volumes.geometry import Geometry
from . import manifest as mf
from .store import build

TEST_ID = "wlasne/__test__"
PHANTOM_ID = "kreator/fantom"
GID = "__kreator__"
SLOW_MS = 3000

# phantom grid: anisotropic on purpose (catches code that ignores spacing)
_SIZE = (72, 64, 40)
_SPACING = (0.8, 0.8, 1.5)


def _phantom_geometry() -> Geometry:
    half = [(n - 1) * s / 2 for n, s in zip(_SIZE, _SPACING, strict=True)]
    return Geometry(
        size=_SIZE,
        spacing=_SPACING,
        origin=(-half[0], -half[1], -half[2]),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    )


def _phantom(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    from ..graph.values import DataValue
    from ..meshes import ops
    from ..nodes.pomiary import table
    from ..nodes.segmentacja import PALETTE

    g = _phantom_geometry()
    nk, nj, ni = g.shape_kji
    k, j, i = np.ogrid[:nk, :nj, :ni]
    x = g.origin[0] + i * g.spacing[0]
    y = g.origin[1] + j * g.spacing[1]
    z = g.origin[2] + k * g.spacing[2]
    body = (x / 26) ** 2 + (y / 22) ** 2 + (z / 26) ** 2 <= 1
    big_c, big_r = (6.0, -4.0, 4.0), 8.0
    small_c, small_r = (-10.0, 6.0, -6.0), 4.0
    big = (x - big_c[0]) ** 2 + (y - big_c[1]) ** 2 + (z - big_c[2]) ** 2 <= big_r**2
    small = (x - small_c[0]) ** 2 + (y - small_c[1]) ** 2 + (z - small_c[2]) ** 2 <= small_r**2
    hu = np.where(body, 40, -1000).astype(np.int16)
    hu[big] = 300
    hu[small] = 150
    noise = np.random.default_rng(7).normal(0, 12, hu.shape)
    hu = np.clip(hu + noise, -1024, 3000).astype(np.int16)
    info = {"name": "Fantom", "modality": "CT", "window": {"center": 40, "width": 600}}
    vol = ctx.volume_result(hu, g, info, socket="wolumen")
    seg = ctx.volume_result(
        big.astype(np.uint8),
        g,
        {"name": "Fantom · kula", "ref": vol.ref, "color": PALETTE[0]},
        socket="segment",
        kind="segment",
    )
    lab = np.zeros(hu.shape, np.uint8)
    lab[big] = 1
    lab[small] = 2
    labels = [
        {"id": 1, "name": "Kula", "color": PALETTE[0]},
        {"id": 2, "name": "Mała kula", "color": PALETTE[1]},
    ]
    seg2 = ctx.volume_result(
        lab,
        g,
        {"name": "Fantom · etykiety", "ref": vol.ref, "labels": labels},
        socket="segmentacja",
        kind="segmentacja",
    )
    v, f = ops.from_mask(big.astype(np.uint8), g, 0.8)
    mesh = ctx.mesh_result(
        v, f, {"name": "Fantom · kula", "ref": vol.ref, "color": PALETTE[5]}, socket="mesh"
    )
    vox_ml = float(np.prod(g.spacing)) / 1000
    rows = [
        {"name": n, "ml": round(float(np.count_nonzero(m)) * vox_ml, 3), "hu": float(hu[m].mean())}
        for n, m in (("Ciało", body), ("Kula", big), ("Mała kula", small))
    ]
    tab = table(
        [("name", "Obszar", ""), ("ml", "Objętość", "ml"), ("hu", "Średnia", "HU")],
        rows,
        chart={"type": "bars", "label": "name", "value": "ml"},
        title="Fantom",
    )
    a = [big_c[0] - 15, big_c[1], big_c[2]]
    b = [big_c[0] + 15, big_c[1], big_c[2]]
    pts = DataValue(
        "punkty",
        {
            "items": [
                {
                    "id": "l1",
                    "type": "line",
                    "name": "Linijka",
                    "p": [a, b],
                    "value": 30.0,
                    "unit": "mm",
                }
            ]
        },
    )
    return {
        "wolumen": vol,
        "segment": seg,
        "segmentacja": seg2,
        "mesh": mesh,
        "tabela": tab,
        "liczba": 42.0,
        "punkty": pts,
    }


PHANTOM = NodeType(
    id=PHANTOM_ID,
    label="Fantom",
    domain="wlasne",
    stage="dane",
    description="Syntetyczne dane testowe Kreatora.",
    inputs=(),
    outputs=tuple(Port(k, k, k) for k in mf.PORT_KINDS),  # type: ignore[arg-type]
    params=(),
    run=_phantom,
    version=1,
)


def run_test(job: Job, ev: Evaluator, body: dict[str, Any]) -> dict[str, Any]:
    m = mf.clean(body.get("manifest"))
    code = str(body.get("code") or "")
    nt, rt = build(m, code, test=True, type_id=TEST_ID)

    syntax = rt.check_code()
    if syntax:
        return _result("error", rt, syntax_error=syntax)

    sources = body.get("inputs") or {}
    nodes: list[dict[str, Any]] = [{"id": "test", "type": TEST_ID, "params": body.get("params")}]
    edges: list[dict[str, Any]] = []
    used_graph = False
    feeds: dict[str, tuple[str, str]] = {}
    for port in m["inputs"]:
        src = sources.get(port["id"]) or {"source": "fantom"}
        kind = src.get("source")
        if kind == "brak":
            continue
        if kind == "seria" and port["kind"] == "wolumen" and src.get("vid"):
            nid = f"s:{port['id']}"
            nodes.append({"id": nid, "type": "wolumen/seria", "params": {"volume": src["vid"]}})
            feeds[port["id"]] = (nid, "out")
        elif kind == "graf" and src.get("node"):
            used_graph = True
            feeds[port["id"]] = (f"g:{src['node']}", str(src.get("socket") or "out"))
        else:
            if not any(n["id"] == "fantom" for n in nodes):
                nodes.append({"id": "fantom", "type": PHANTOM_ID, "params": {}})
            feeds[port["id"]] = ("fantom", port["kind"])
    for pid, (nid, sock) in feeds.items():
        edges.append({"from": nid, "fromSocket": sock, "to": "test", "toSocket": pid})
    if used_graph:
        g = body.get("graph") or {}
        for n in g.get("nodes", []):
            nodes.append({**n, "id": f"g:{n['id']}"})
        for e in g.get("edges", []):
            edges.append({**e, "from": f"g:{e['from']}", "to": f"g:{e['to']}"})

    res = ev.evaluate(
        job,
        GID,
        {"nodes": nodes, "edges": edges},
        ["test"],
        "preview",
        extra_types={TEST_ID: nt, PHANTOM_ID: PHANTOM},
        fresh=frozenset({"test"}),
    )
    out = res.get("test", {})
    inputs_json = {}
    for pid, (nid, sock) in feeds.items():
        o = res.get(nid, {}).get("outputs", {}).get(sock)
        if o is not None:
            inputs_json[pid] = o
    return _result(out.get("state", "error"), rt, out, inputs_json)


def _result(
    state: str,
    rt: Any,
    out: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    syntax_error: Any = None,
) -> dict[str, Any]:
    out = out or {}
    err = syntax_error or rt.error
    error = None
    if state != "done":
        if err is not None:
            error = {
                "message": err.message,
                "line": err.line,
                "trace": err.trace,
                "module": getattr(err, "module", None),
            }
        else:
            error = {
                "message": out.get("error") or "Nie udało się uruchomić",
                "line": None,
                "trace": "",
            }
    checks: list[dict[str, Any]] = [
        {
            "id": "code",
            "label": "Kod",
            "level": "fail" if syntax_error else "ok",
            "message": syntax_error.message if syntax_error else "",
            "line": syntax_error.line if syntax_error else None,
        },
    ]
    if not syntax_error:
        checks.append(
            {
                "id": "run",
                "label": "run() i wyjścia",
                "level": "ok" if state == "done" else "fail",
                "message": "" if state == "done" else (error or {}).get("message", ""),
                "line": (error or {}).get("line"),
            }
        )
    checks += rt.checks
    if state == "done" and rt.ms > SLOW_MS:
        checks.append(
            {
                "id": "time",
                "label": "Czas",
                "level": "warn",
                "message": f"{rt.ms} ms na małych danych — na pełnym będzie wolno",
            }
        )
    return {
        "state": state,
        "error": error,
        "outputs": out.get("outputs", {}),
        "inputs": inputs or {},
        "logs": rt.logs,
        "stats": rt.stats,
        "checks": checks,
        "ms": rt.ms,
    }
