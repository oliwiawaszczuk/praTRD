import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pratrd.api.app import create_app
from pratrd.config import Config
from pratrd.graph.evaluator import Evaluator
from pratrd.jobs import Job
from pratrd.meshes import io, ops
from pratrd.meshes.library import MeshLibrary
from pratrd.volumes.geometry import Geometry

from .test_graph import Hub, edge, node
from .test_segmentacja import arr, env, run  # noqa: F401 — fixture

GRID = Geometry(
    size=(150, 70, 80),
    spacing=(0.8, 0.9, 1.1),
    origin=(-10.0, 5.0, 3.0),
    direction=(1, 0, 0, 0, -1, 0, 0, 0, 1),  # left-handed: winding must still come out right
)


def sphere_mask(g: Geometry, c_ijk=(75, 35, 40), r_mm=25.0) -> np.ndarray:
    k, j, i = np.meshgrid(*(np.arange(s) for s in g.shape_kji), indexing="ij")
    sp = g.spacing
    d = (
        ((i - c_ijk[0]) * sp[0]) ** 2
        + ((j - c_ijk[1]) * sp[1]) ** 2
        + ((k - c_ijk[2]) * sp[2]) ** 2
    )
    return (d <= r_mm * r_mm).astype(np.uint8)


# ── ops ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sigma", [0.0, 0.5])
def test_surface_of_sphere_is_closed_outward_and_measures_right(sigma) -> None:
    mask = sphere_mask(GRID)
    v, f = ops.from_mask(mask, GRID, sigma)
    st = ops.surface_stats(v, f)
    assert st["closed"] and ops.signed_volume(v, f) > 0
    vox_ml = mask.sum() * np.prod(GRID.spacing) / 1000
    assert st["ml"] == pytest.approx(vox_ml, rel=0.01)
    assert st["area"] == pytest.approx(4 * math.pi * 25**2, rel=0.10 if sigma == 0 else 0.05)
    # outward normals: the vertex normal points away from the centre
    centre = ops.index_to_world(GRID, np.array([[75.0, 35.0, 40.0]]))[0]
    n = ops.vertex_normals(v, f)
    assert np.mean(np.einsum("ij,ij->i", n, v - centre) > 0) > 0.99


def test_slabs_weld_into_one_closed_surface(monkeypatch) -> None:
    mask = sphere_mask(GRID)
    whole = ops.from_mask(mask, GRID, 0.5)
    monkeypatch.setattr(ops, "_SLAB", 7)
    v, f = ops.from_mask(mask, GRID, 0.5)
    st = ops.surface_stats(v, f)
    assert st["closed"] and st["boundary"] == 0
    assert len(f) == len(whole[1]) and len(v) == len(whole[0])
    assert st["ml"] == pytest.approx(ops.surface_stats(*whole)["ml"], rel=1e-6)


def test_voxelize_inverts_marching_cubes() -> None:
    mask = sphere_mask(GRID)
    v, f = ops.from_mask(mask, GRID, 0.0)
    back = ops.voxelize(v, f, GRID)
    assert back.dtype == np.uint8 and back.shape == mask.shape
    assert np.count_nonzero(back != mask) == 0


def test_taubin_keeps_volume_laplace_shrinks() -> None:
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.0)
    ml = ops.surface_stats(v, f)["ml"]
    t = ops.surface_stats(ops.smooth(v, f, 30, "taubin"), f)
    lap = ops.surface_stats(ops.smooth(v, f, 30, "laplace"), f)
    assert t["ml"] == pytest.approx(ml, rel=0.01)
    assert lap["ml"] < ml * 0.99
    assert t["area"] < ops.surface_stats(v, f)["area"]  # the staircase is gone


def test_decimation_keeps_shape() -> None:
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    v2, f2 = ops.decimate(v, f, 0.1)
    st = ops.surface_stats(v2, f2)
    assert len(f2) == pytest.approx(len(f) * 0.1, rel=0.1)
    assert st["closed"] and ops.signed_volume(v2, f2) > 0
    assert st["ml"] == pytest.approx(ops.surface_stats(v, f)["ml"], rel=0.01)


def test_display_lod_is_made_once(tmp_path: Path) -> None:
    from pratrd.meshes import store as mesh_store

    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    p = tmp_path / "a.mesh"
    mesh_store.write_mesh(p, v, f, {"name": "kula"})
    assert mesh_store.display_path(p, max_faces=len(f)) == p
    lod = mesh_store.display_path(p, max_faces=len(f) // 10)
    assert lod == p / "lod" and mesh_store.read_meta(lod)["faces"] <= len(f) // 10 * 1.1
    mtime = (lod / "cells.bin").stat().st_mtime_ns
    assert mesh_store.display_path(p, max_faces=len(f) // 10) == lod
    assert (lod / "cells.bin").stat().st_mtime_ns == mtime


def test_thumbnail_draws_something() -> None:
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    img = ops.render_thumb(v, f, (176, 132), "#4db6ac")
    assert img.shape == (132, 176, 4) and 0.3 < (img[..., 3] > 0).mean() < 0.8


# ── file formats ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ext", [".stl", ".obj", ".ply"])
def test_file_roundtrip(tmp_path: Path, ext: str) -> None:
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    p = io.write_mesh_file(tmp_path / f"m{ext}", v, f, "LPS")
    v2, f2, space = io.read_mesh_file(p)
    assert space == "LPS" and len(f2) == len(f) and len(v2) == len(v)
    assert ops.surface_stats(v2, f2)["ml"] == pytest.approx(ops.surface_stats(v, f)["ml"], 1e-4)
    # RAS on export = x, y negated; the header says so and reading it back restores LPS
    io.write_mesh_file(tmp_path / f"r{ext}", v, f, "RAS")
    v3, _, sp3 = io.read_mesh_file(tmp_path / f"r{ext}")
    assert sp3 == "RAS"
    np.testing.assert_allclose(io.lps_to("RAS", v3).min(0), v.min(0), atol=1e-3)


def test_ascii_stl_and_ply(tmp_path: Path) -> None:
    tri = "facet normal 0 0 1\n outer loop\n" + "  vertex {} {} {}\n" * 3 + " endloop\nendfacet\n"
    # a tetrahedron, outward winding
    p = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)]
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    body = "".join(tri.format(*p[a], *p[b], *p[c]) for a, b, c in faces)
    (tmp_path / "t.stl").write_text(f"solid SPACE=RAS\n{body}endsolid\n")
    v, f, space = io.read_mesh_file(tmp_path / "t.stl")
    assert space == "RAS" and len(v) == 4 and len(f) == 4  # triangle soup welded
    st = ops.surface_stats(v, f)
    assert st["closed"] and st["volume"] == pytest.approx(1000 / 6, abs=1e-3)
    ply = "ply\nformat ascii 1.0\nelement vertex 4\n"
    ply += "property float x\nproperty float y\nproperty float z\n"
    ply += "element face 2\nproperty list uchar int vertex_indices\nend_header\n"
    ply += "0 0 0\n1 0 0\n1 1 0\n0 1 0\n4 0 1 2 3\n3 0 2 3\n"
    (tmp_path / "q.ply").write_text(ply)
    v, f, _ = io.read_mesh_file(tmp_path / "q.ply")
    assert len(v) == 4 and len(f) == 3  # quad fan-triangulated
    (tmp_path / "bad.stl").write_bytes(b"\x00" * 10)
    with pytest.raises(io.MeshFileError):
        io.read_mesh_file(tmp_path / "bad.stl")


# ── graph ────────────────────────────────────────────────────────────────────


def test_segment_to_mesh_chain_and_stats(env) -> None:  # noqa: F811
    ev, vid, parts, _ = env
    nodes_ = [
        node("s", "wolumen/seria", volume=vid),
        node("t", "segmentacja/prog", lo=500, hi=5000),
        node("w", "segmentacja/wyspy", mode="largest", count=1),
        node("m", "mesh/z_segmentu", smooth=0.5),
        node("g", "mesh/wygladz", iterations=10),
        node("d", "mesh/decymuj", keep=20),
        node("st", "mesh/statystyki"),
    ]
    edges_ = [edge("s", "t"), edge("t", "w"), edge("w", "m"), edge("m", "g"), edge("g", "d")]
    edges_ += [edge("m", "st"), edge("d", "st")]
    res = ev.evaluate(
        Job("j", "graph", "t", "w"), "g", {"nodes": nodes_, "edges": edges_}, ["st"], "full"
    )
    m = res["m"]["outputs"]["out"]
    assert m["kind"] == "mesh" and m["info"]["ref"] == vid and m["info"]["closed"]
    assert m["info"]["ml"] == pytest.approx(parts["big"].sum() / 1000, rel=0.03)
    d = res["d"]["outputs"]["out"]["info"]
    assert d["faces"] < m["info"]["faces"] * 0.25 and d["ref"] == vid
    rows = res["st"]["outputs"]["tab"]["value"]["rows"]
    assert [r["faces"] for r in rows] == [m["info"]["faces"], d["faces"]]
    assert (ev.ws_dir / "cache" / f"{m['ref']}.mesh" / "cells.bin").is_file()


def test_mesh_back_to_segment_and_cache_after_restart(env) -> None:  # noqa: F811
    ev, vid, parts, lib = env
    nodes_ = [
        node("s", "wolumen/seria", volume=vid),
        node("t", "segmentacja/prog", lo=500, hi=5000),
        node("w", "segmentacja/wyspy", mode="largest", count=1),
        node("m", "mesh/z_segmentu", smooth=0),
        node("v", "mesh/do_segmentu"),
    ]
    edges_ = [edge("s", "t"), edge("t", "w"), edge("w", "m"), edge("m", "v")]
    edges_.append(edge("s", "v", ts="vol"))
    out, _ = run(ev, nodes_, edges_, "v")
    assert out["kind"] == "segment" and out["info"]["ref"] == vid
    np.testing.assert_array_equal(arr(ev, out) > 0, parts["big"])
    # a fresh evaluator (restart): the mesh comes back from the cache manifest
    ev2 = Evaluator("w", ev.ws_dir, lib, Hub())
    nodes2 = nodes_ + [node("st", "mesh/statystyki")]
    edges2 = edges_ + [edge("m", "st")]
    res2 = ev2.evaluate(
        Job("j", "graph", "t", "w"), "g", {"nodes": nodes2, "edges": edges2}, ["st"], "full"
    )
    assert res2["m"]["outputs"]["out"]["kind"] == "mesh"
    assert res2["st"]["state"] == "done", res2["st"]  # the cached mesh reached the next node
    assert res2["st"]["outputs"]["tab"]["value"]["rows"][0]["faces"] > 0
    # removing the cached mesh files forces a recompute instead of a dangling handle
    ev3 = Evaluator("w", ev.ws_dir, lib, Hub())
    assert ev3.prune(0) > 0
    assert not list((ev.ws_dir / "cache").glob("*.mesh"))


def test_open_mesh_refuses_voxelization(env, tmp_path: Path) -> None:  # noqa: F811
    ev, vid, _, _ = env
    v = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
    io.write_mesh_file(tmp_path / "tri.stl", v, np.array([[0, 1, 2]]))
    mid = MeshLibrary().import_file(ev.ws_dir, tmp_path / "tri.stl")["id"]
    nodes_ = [
        node("s", "wolumen/seria", volume=vid),
        node("p", "mesh/plik", mesh=mid),
        node("v", "mesh/do_segmentu"),
    ]
    graph = {"nodes": nodes_, "edges": [edge("p", "v"), edge("s", "v", ts="vol")]}
    res = ev.evaluate(Job("j", "graph", "t", "w"), "g", graph, ["v"], "full")
    assert res["v"]["state"] == "error" and "zamknięty" in res["v"]["error"]


def test_imported_file_space_switch(env, tmp_path: Path) -> None:  # noqa: F811
    ev, vid, _, _ = env
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    io.write_mesh_file(tmp_path / "s.stl", v, f, "RAS")  # header says RAS
    lib = MeshLibrary()
    entry = lib.import_file(ev.ws_dir, tmp_path / "s.stl")
    assert entry["space"] == "RAS" and entry["spaceFromFile"] and entry["closed"]
    assert lib.import_file(ev.ws_dir, tmp_path / "s.stl")["id"] == entry["id"]  # no duplicate
    assert len(lib.list(ev.ws_dir)) == 1

    def bounds(space: str) -> list[float]:
        out, _ = run(ev, [node("p", "mesh/plik", mesh=entry["id"], space=space)], [], "p")
        return out["info"]["bounds"]

    lo, hi = v.min(0), v.max(0)
    auto = bounds("auto")  # RAS in the file → converted back to LPS = the original
    np.testing.assert_allclose(auto[0::2], lo, atol=1e-3)
    np.testing.assert_allclose(auto[1::2], hi, atol=1e-3)
    raw = bounds("LPS")  # taken as LPS: mirrored in x and y
    assert raw[0] == pytest.approx(-hi[0], abs=1e-3) and raw[4] == pytest.approx(lo[2], abs=1e-3)
    # background volume only lives in info: same library mesh, no copy
    out, _ = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("p", "mesh/plik", mesh=entry["id"], space="LPS"),
        ],
        [edge("s", "p", ts="vol")],
        "p",
    )
    assert out["ref"] == entry["id"] and out["info"]["ref"] == vid


# ── API ──────────────────────────────────────────────────────────────────────


def test_api_import_data_thumb_export(tmp_path: Path) -> None:
    v, f = ops.from_mask(sphere_mask(GRID), GRID, 0.5)
    io.write_mesh_file(tmp_path / "s.obj", v, f)
    with TestClient(create_app(Config(root=tmp_path / "root", port=0))) as c:
        wid = c.get("/workspaces").json()["active_id"]
        r = c.post(
            f"/workspaces/{wid}/meshes/import",
            json={"paths": [str(tmp_path / "s.obj"), "/nope.stl"]},
        )
        body = r.json()
        (entry,) = body["added"]
        assert len(body["errors"]) == 1 and entry["faces"] == len(f)
        mid = entry["id"]
        assert [e["id"] for e in c.get(f"/workspaces/{wid}/meshes").json()] == [mid]

        d = c.get(f"/workspaces/{wid}/meshes/{mid}/data")
        meta = json.loads(d.headers["X-Meta"])
        assert len(d.content) == meta["verts"] * 24 + meta["faces"] * 16
        cells = np.frombuffer(d.content, "<u4", offset=meta["verts"] * 24).reshape(-1, 4)
        assert (cells[:, 0] == 3).all() and cells[:, 1:].max() < meta["verts"]

        t = c.get(f"/workspaces/{wid}/meshes/{mid}/thumb.png")
        assert t.status_code == 200 and t.content[:4] == b"\x89PNG"

        out = tmp_path / "out.stl"
        r = c.post(
            f"/workspaces/{wid}/meshes/{mid}/export", json={"path": str(out), "space": "RAS"}
        )
        assert r.status_code == 200 and out.stat().st_size == 84 + 50 * len(f)
        assert io.read_mesh_file(out)[2] == "RAS"
        bad = c.post(f"/workspaces/{wid}/meshes/{mid}/export", json={"path": "rel.stl"})
        assert bad.status_code == 400

        assert (
            c.put(f"/workspaces/{wid}/meshes/{mid}", json={"name": "Kula"}).json()["name"] == "Kula"
        )
        assert c.delete(f"/workspaces/{wid}/meshes/{mid}").json()["ok"]
        assert c.get(f"/workspaces/{wid}/meshes/{mid}/data").status_code == 404
        assert c.get(f"/workspaces/{wid}/meshes").json() == []
