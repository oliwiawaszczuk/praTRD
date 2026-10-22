import math

import pytest

from pratrd.graph.types import REGISTRY
from pratrd.jobs import Job

from .test_graph import edge, node, world
from .test_segmentacja import env  # noqa: F401 — fixture

THR = [
    node("s", "wolumen/seria"),
    node("t", "segmentacja/prog", lo=500, hi=5000),
    node("w", "segmentacja/wyspy", mode="largest", count=1),
]


def ev_run(ev, nodes_, edges_, target):
    res = ev.evaluate(
        Job("j", "graph", "t", "w"), "g", {"nodes": nodes_, "edges": edges_}, [target], "full"
    )
    assert res[target]["state"] == "done", res[target]
    return res[target]["outputs"], res


def with_vid(vid):
    return [{**n, "params": {**n["params"], "volume": vid}} if n["id"] == "s" else n for n in THR]


def test_segment_statistics_match_voxel_count(env) -> None:  # noqa: F811
    ev, vid, parts, _ = env
    ns = [*with_vid(vid), node("st", "pomiary/statystyki")]
    es = [edge("s", "t"), edge("t", "w"), edge("w", "st", ts="seg")]
    out, _ = ev_run(ev, ns, es, "st")
    tab = out["tab"]
    assert tab["kind"] == "tabela"
    (row,) = tab["value"]["rows"]
    big = int(parts["big"].sum())
    # the E5 criterion: volume = voxel count × voxel volume (Slicer's "Volume"), 1 mm³ voxels
    assert (
        row["voxels"] == big
        and row["mm3"] == pytest.approx(big)
        and row["ml"] == pytest.approx(big / 1000)
    )
    # sphere r = 12 mm: 4πr² ≈ 1810 mm²
    assert row["surface"] == pytest.approx(4 * math.pi * 144, rel=0.04)
    # intensity comes from the segment's background (info.ref) without a volume input
    assert row["min"] == 1000 and row["max"] == 1000 and row["sd"] == 0


def test_statistics_per_label(env) -> None:  # noqa: F811
    ev, vid, parts, _ = env
    ns = [
        *with_vid(vid),
        node("x", "segmentacja/logika", op="sub"),
        node("z", "segmentacja/zloz"),
        node("st", "pomiary/statystyki", surface=False),
    ]
    es = [
        edge("s", "t"),
        edge("t", "w"),
        edge("t", "x", ts="a"),
        edge("w", "x", ts="b"),
        edge("w", "z"),
        edge("x", "z"),
        edge("z", "st", ts="lab"),
        edge("s", "st", ts="vol"),
    ]
    out, _ = ev_run(ev, ns, es, "st")
    rows = out["tab"]["value"]["rows"]
    assert [r["voxels"] for r in rows] == [
        int(parts["big"].sum()),
        int((parts["small"] | parts["shell"]).sum()),
    ]
    assert rows[0]["surface"] is None and rows[0]["color"]


def test_histogram_inside_segment(env) -> None:  # noqa: F811
    ev, vid, parts, _ = env
    ns = [*with_vid(vid), node("h", "pomiary/histogram", bins=16, auto="minmax")]
    es = [edge("s", "t"), edge("t", "w"), edge("s", "h", ts="vol"), edge("w", "h", ts="seg")]
    out, _ = ev_run(ev, ns, es, "h")
    rows = out["tab"]["value"]["rows"]
    assert len(rows) == 16 and sum(r["count"] for r in rows) == int(parts["big"].sum())
    out_all, _ = ev_run(ev, ns[:1] + [ns[-1]], [edge("s", "h", ts="vol")], "h")
    assert sum(r["count"] for r in out_all["tab"]["value"]["rows"]) == 60 * 60 * 90


def test_markups_and_profile(env) -> None:  # noqa: F811
    ev, vid, _, _ = env
    g = ev.source_volume(vid).geometry
    a, b = world(g, (0, 30, 30)), world(g, (50, 30, 30))  # through the big sphere (i 13..37)
    c = world(g, (0, 0, 30))
    items = [
        {"id": "l1", "type": "line", "p": [list(a), list(b)]},
        {"id": "a1", "type": "angle", "p": [list(c), list(a), list(b)]},
        {"id": "r1", "type": "roi", "p": [[0, 0, 0], [10, 20, 30]]},
        {"id": "bad", "type": "angle", "p": [list(a)]},  # unfinished → dropped
        {"id": "p1", "type": "point", "p": [list(c)]},
    ]
    ns = [
        node("s", "wolumen/seria", volume=vid),
        node("m", "pomiary/markupy", items=items),
        node("pr", "pomiary/profil"),
    ]
    es = [edge("s", "pr", ts="vol"), edge("m", "pr", ts="pts")]
    out, res = ev_run(ev, ns, es, "pr")
    pts = res["m"]["outputs"]["out"]["value"]["items"]
    assert [m["id"] for m in pts] == ["l1", "a1", "r1", "p1"]
    assert pts[0]["value"] == pytest.approx(50) and pts[0]["unit"] == "mm"
    assert pts[1]["value"] == pytest.approx(90)
    assert pts[2]["value"] == pytest.approx(6.0)  # 10 × 20 × 30 mm = 6 ml
    assert res["m"]["outputs"]["tab"]["value"]["rows"][0]["name"] == "Linijka 1"
    rows = out["tab"]["value"]["rows"]
    assert rows[-1]["mm"] == pytest.approx(50)
    mid = [r["value"] for r in rows if 15 <= r["mm"] <= 35]
    edge_ = [r["value"] for r in rows if r["mm"] <= 8]
    assert min(mid) > 900 and max(edge_) < 100


def test_profile_needs_a_line(env) -> None:  # noqa: F811
    ev, vid, _, _ = env
    ns = [
        node("s", "wolumen/seria", volume=vid),
        node("m", "pomiary/markupy"),
        node("pr", "pomiary/profil"),
    ]
    res = ev.evaluate(
        Job("j", "graph", "t", "w"),
        "g",
        {"nodes": ns, "edges": [edge("s", "pr", ts="vol"), edge("m", "pr", ts="pts")]},
        ["pr"],
        "full",
    )
    assert res["pr"]["state"] == "error" and "linijk" in res["pr"]["error"]


def test_measurement_nodes_registered() -> None:
    for t in ("pomiary/markupy", "pomiary/statystyki", "pomiary/histogram", "pomiary/profil"):
        assert REGISTRY[t].domain == "pomiary"
