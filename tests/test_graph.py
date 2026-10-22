from pathlib import Path

import numpy as np
import pytest

from pratrd import nodes  # noqa: F401
from pratrd.dicom.scan import scan
from pratrd.events import EventHub
from pratrd.graph.evaluator import Evaluator, GraphError
from pratrd.graph.types import REGISTRY
from pratrd.jobs import Job
from pratrd.volumes.geometry import Geometry
from pratrd.volumes.importer import import_candidate
from pratrd.volumes.library import Library

from .synth import ramp_volume, write_series


class Hub(EventHub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def publish(self, msg: dict) -> None:
        self.events.append(msg)


@pytest.fixture
def setup(tmp_path: Path):
    ws = tmp_path / "ws"
    for d in ("store", "series", "cache"):
        (ws / d).mkdir(parents=True)
    rng = np.random.default_rng(0)
    stored = (ramp_volume(40, 30, 130) % 2000 + rng.integers(0, 50, size=(40, 30, 130))).astype(
        np.uint16
    )
    write_series(tmp_path / "in", stored, spacing=(0.5, 0.5), slice_gap=1.0)
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    lib = Library()
    vid = import_candidate(Job("j", "i", "t", "w"), tmp_path, ws, lib, c, True)["vid"]
    hub = Hub()
    return Evaluator("w", ws, lib, hub), vid, stored.astype(np.int32) - 1024, hub


def run(ev: Evaluator, graph: dict, targets: list[str], quality="full") -> dict:
    return ev.evaluate(Job("j", "graph", "t", "w"), "g1", graph, targets, quality)


def node(nid: str, type_: str, **params) -> dict:
    return {"id": nid, "type": type_, "params": params}


def edge(a: str, b: str, fs="out", ts="in") -> dict:
    return {"from": a, "fromSocket": fs, "to": b, "toSocket": ts}


def world(g: Geometry, ijk) -> np.ndarray:
    return np.asarray(g.origin) + g.matrix @ (np.asarray(g.spacing) * np.asarray(ijk, float))


def test_schema_is_complete() -> None:
    for nt in REGISTRY.values():
        s = nt.schema()
        assert s["id"].startswith(s["domain"] + "/")
        assert s["description"]


def test_chain_and_cache(setup) -> None:
    ev, vid, data, hub = setup
    g = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wolumen/wygladz", sigma=1.5)],
        "edges": [edge("a", "b")],
    }
    res = run(ev, g, ["b"])
    assert res["b"]["state"] == "done"
    out = res["b"]["outputs"]["out"]
    assert len(out["ref"]) == 24 and out["info"]["modality"] == "CT"
    smoothed = ev.ws_dir / "cache" / f"{out['ref']}.zarr"
    assert smoothed.is_dir()

    hub.events.clear()
    res2 = run(ev, g, ["b"])
    assert res2["b"]["outputs"]["out"]["ref"] == out["ref"]
    assert all(e.get("cached") for e in hub.events if e["state"] == "done")

    # a fresh evaluator (new session) reuses results from disk
    ev2 = Evaluator("w", ev.ws_dir, ev.library, Hub())
    hub2 = ev2.hub
    run(ev2, g, ["b"])
    assert any(e["node"] == "b" and e.get("cached") for e in hub2.events)

    # changing a parameter → new key
    g["nodes"][1]["params"]["sigma"] = 2.0
    assert run(ev, g, ["b"])["b"]["outputs"]["out"]["ref"] != out["ref"]


def test_crop_keeps_world_position(setup) -> None:
    ev, vid, data, _ = setup
    g = {
        "nodes": [
            node("a", "wolumen/seria", volume=vid),
            node("c", "wolumen/przytnij", i0=20, i1=60, j0=10, j1=50, k0=25, k1=75),
        ],
        "edges": [edge("a", "c")],
    }
    out = run(ev, g, ["c"])["c"]["outputs"]["out"]
    src = ev.source_volume(vid)
    gc = Geometry.from_json(out["geometry"])
    lo = (26, 3, 10)  # floor(20%·130), floor(10%·30), floor(25%·40)
    assert gc.size == (52, 12, 20)
    np.testing.assert_allclose(world(gc, (0, 0, 0)), world(src.geometry, lo), atol=1e-6)
    arr = ev.source_volume(vid).array()
    from pratrd.graph.values import ARRAYS

    crop = ARRAYS.get(ev.ws_dir / "cache" / f"{out['ref']}.zarr", 0)
    np.testing.assert_array_equal(crop, arr[10:30, 3:15, 26:78])


def test_resample_keeps_physical_box(setup) -> None:
    ev, vid, _, _ = setup
    g = {
        "nodes": [
            node("a", "wolumen/seria", volume=vid),
            node("r", "wolumen/resampluj", spacing=1.0),
        ],
        "edges": [edge("a", "r")],
    }
    out = run(ev, g, ["r"])["r"]["outputs"]["out"]
    gr = Geometry.from_json(out["geometry"])
    src = ev.source_volume(vid).geometry
    assert gr.spacing == (1.0, 1.0, 1.0)
    assert gr.size == (65, 15, 40)
    # box corners: centre(0) − spacing/2 must coincide
    c_src = world(src, (-0.5, -0.5, -0.5))
    c_out = world(gr, (-0.5, -0.5, -0.5))
    np.testing.assert_allclose(c_src, c_out, atol=1e-6)


def test_preview_uses_coarser_level_and_differs_from_full(setup, monkeypatch) -> None:
    import pratrd.graph.evaluator as E

    ev, vid, _, _ = setup
    monkeypatch.setattr(E, "PREVIEW_VOXELS", 10_000)
    g = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wolumen/wygladz")],
        "edges": [edge("a", "b")],
    }
    prev = run(ev, g, ["b"], "preview")
    full = run(ev, g, ["b"], "full")
    assert prev["a"]["outputs"]["out"]["level"] > 0
    assert full["a"]["outputs"]["out"]["level"] == 0
    assert prev["b"]["outputs"]["out"]["ref"] != full["b"]["outputs"]["out"]["ref"]


def test_missing_input_blocks_only_its_branch(setup) -> None:
    ev, vid, _, hub = setup
    g = {
        "nodes": [
            node("a", "wolumen/seria", volume=vid),
            node("b", "wolumen/wygladz"),
            node("x", "wolumen/wygladz"),
            node("y", "wolumen/resampluj"),
        ],
        "edges": [edge("a", "b"), edge("x", "y")],
    }
    res = run(ev, g, ["b", "y"])
    assert res["b"]["state"] == "done"
    assert res["x"]["state"] == "blocked" and "Brak wejścia" in res["x"]["error"]
    assert res["y"]["state"] == "blocked"


def test_cycle_and_bad_edges(setup) -> None:
    ev, vid, _, _ = setup
    cyc = {
        "nodes": [node("p", "wolumen/wygladz"), node("q", "wolumen/wygladz")],
        "edges": [edge("p", "q"), edge("q", "p")],
    }
    with pytest.raises(GraphError):
        run(ev, cyc, ["q"])
    bad = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wolumen/wygladz")],
        "edges": [edge("a", "b", fs="nope")],
    }
    assert run(ev, bad, ["b"])["b"]["state"] == "blocked"


def test_node_error_is_reported(setup) -> None:
    ev, _, _, _ = setup
    g = {"nodes": [node("a", "wolumen/seria", volume="")], "edges": []}
    res = run(ev, g, ["a"])
    assert res["a"]["state"] == "error" and "Nie wybrano" in res["a"]["error"]


def test_params_are_clamped_and_defaulted() -> None:
    nt = REGISTRY["wolumen/wygladz"]
    assert nt.clean_params({"sigma": 999, "method": "bogus"}) == {
        "method": "gauss",
        "sigma": 10.0,
        "radius": 1.0,
    }
