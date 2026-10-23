from pathlib import Path

import numpy as np
import pytest

from pratrd import nodes  # noqa: F401
from pratrd.dicom.scan import scan
from pratrd.graph.evaluator import Evaluator
from pratrd.graph.values import ARRAYS
from pratrd.jobs import Job
from pratrd.volumes import store
from pratrd.volumes.geometry import Geometry
from pratrd.volumes.importer import import_candidate
from pratrd.volumes.library import Library

from .synth import write_series
from .test_graph import Hub, edge, node, world

SP = 1.0  # isotropic 1 mm voxels → voxel counts are mm³


def phantom(n=(60, 60, 90)) -> tuple[np.ndarray, dict]:
    """[k, j, i]: big sphere r=12 at (30,30,25), small sphere r=4 at (30,30,70),
    hollow sphere (shell r 8..11) at (30, 30, 50) — inside value 0 — plus mild noise."""
    k, j, i = np.meshgrid(*(np.arange(s) for s in n), indexing="ij")
    vol = np.random.default_rng(0).integers(0, 40, size=n).astype(np.uint16)

    def ball(c, r):
        return (i - c[0]) ** 2 + (j - c[1]) ** 2 + (k - c[2]) ** 2 <= r * r

    big = ball((25, 30, 30), 12)
    small = ball((70, 30, 30), 4)
    shell = ball((50, 30, 30), 11) & ~ball((50, 30, 30), 8)
    vol[big | small | shell] = 1000
    return vol, {"big": big, "small": small, "shell": shell}


@pytest.fixture
def env(tmp_path: Path):
    ws = tmp_path / "ws"
    for d in ("store", "series", "cache"):
        (ws / d).mkdir(parents=True)
    vol, parts = phantom()
    write_series(
        tmp_path / "in", vol, spacing=(SP, SP), slice_gap=SP, intercept=0, origin=(0, 0, 0)
    )
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    lib = Library()
    vid = import_candidate(Job("j", "i", "t", "w"), tmp_path, ws, lib, c, True)["vid"]
    return Evaluator("w", ws, lib, Hub()), vid, parts, lib


def run(ev, nodes_, edges_, target):
    res = ev.evaluate(
        Job("j", "graph", "t", "w"), "g", {"nodes": nodes_, "edges": edges_}, [target], "full"
    )
    assert res[target]["state"] == "done", res[target]
    return res[target]["outputs"]["out"], res


def arr(ev, out):
    return ARRAYS.get(ev.ws_dir / "cache" / f"{out['ref']}.zarr", 0)


def test_threshold_counts_and_ml(env) -> None:
    ev, vid, parts, _ = env
    out, _ = run(
        ev,
        [node("s", "wolumen/seria", volume=vid), node("t", "segmentacja/prog", lo=500, hi=5000)],
        [edge("s", "t")],
        "t",
    )
    want = int((parts["big"] | parts["small"] | parts["shell"]).sum())
    assert out["kind"] == "segment" and out["info"]["voxels"] == want
    assert out["info"]["ml"] == pytest.approx(want / 1000, abs=1e-3)
    assert out["info"]["ref"] == vid  # background for the overlay
    np.testing.assert_array_equal(arr(ev, out) > 0, parts["big"] | parts["small"] | parts["shell"])


def test_islands_largest_and_min_volume(env) -> None:
    ev, vid, parts, _ = env
    base = [node("s", "wolumen/seria", volume=vid), node("t", "segmentacja/prog", lo=500, hi=5000)]
    out, _ = run(
        ev,
        base + [node("w", "segmentacja/wyspy", mode="largest", count=1)],
        [edge("s", "t"), edge("t", "w")],
        "w",
    )
    np.testing.assert_array_equal(arr(ev, out) > 0, parts["big"])
    small_mm3 = int(parts["small"].sum())
    out2, _ = run(
        ev,
        base + [node("w2", "segmentacja/wyspy", mode="min", min_mm3=small_mm3 + 1)],
        [edge("s", "t"), edge("t", "w2")],
        "w2",
    )
    np.testing.assert_array_equal(arr(ev, out2) > 0, parts["big"] | parts["shell"])


def test_morphology_fill_and_dilate(env) -> None:
    ev, vid, parts, _ = env
    base = [node("s", "wolumen/seria", volume=vid), node("t", "segmentacja/prog", lo=500, hi=5000)]
    out, _ = run(
        ev,
        base + [node("f", "segmentacja/morfologia", op="fill")],
        [edge("s", "t"), edge("t", "f")],
        "f",
    )
    filled = arr(ev, out) > 0
    k, j, i = np.meshgrid(*(np.arange(s) for s in filled.shape), indexing="ij")
    centre_of_shell = (k == 30) & (j == 30) & (i == 50)
    assert filled[centre_of_shell].all()  # cavity inside the shell is filled
    out2, _ = run(
        ev,
        base + [node("d", "segmentacja/morfologia", op="dilate", radius=2)],
        [edge("s", "t"), edge("t", "d")],
        "d",
    )
    assert out2["info"]["voxels"] > (parts["big"] | parts["small"] | parts["shell"]).sum()


def test_region_growing_from_seed(env) -> None:
    ev, vid, parts, _ = env
    g = Geometry.from_json(ev.source_volume(vid).geometry.to_json())
    seed = list(world(g, (70, 30, 30)))  # centre of the small sphere
    out, _ = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("r", "segmentacja/rozrost", seeds=[seed], method="zakres", lo=500, hi=5000),
        ],
        [edge("s", "r")],
        "r",
    )
    np.testing.assert_array_equal(arr(ev, out) > 0, parts["small"])
    # default "tolerance" method: no HU range needed
    out2, _ = run(
        ev,
        [node("s", "wolumen/seria", volume=vid), node("r2", "segmentacja/rozrost", seeds=[seed])],
        [edge("s", "r2")],
        "r2",
    )
    np.testing.assert_array_equal(arr(ev, out2) > 0, parts["small"])
    # a seed outside the range explains itself
    res = ev.evaluate(
        Job("j", "graph", "t", "w"),
        "g",
        {
            "nodes": [
                node("s", "wolumen/seria", volume=vid),
                node("r3", "segmentacja/rozrost", seeds=[seed], method="zakres", lo=2000, hi=3000),
            ],
            "edges": [edge("s", "r3")],
        },
        ["r3"],
        "full",
    )
    assert res["r3"]["state"] == "error"
    assert "1000" in res["r3"]["error"] and "poza zakresem" in res["r3"]["error"]


def test_brush_add_and_erase(env) -> None:
    ev, vid, parts, _ = env
    g = ev.source_volume(vid).geometry
    p = list(world(g, (10, 10, 10)))
    strokes = [{"p": [p], "r": 5.0, "mode": "add"}]
    out, _ = run(
        ev,
        [node("s", "wolumen/seria", volume=vid), node("e", "segmentacja/edycja", strokes=strokes)],
        [edge("s", "e", ts="ref")],
        "e",
    )
    assert out["info"]["voxels"] == pytest.approx(4 / 3 * np.pi * 125, rel=0.08)
    strokes.append({"p": [p], "r": 3.0, "mode": "erase"})
    out2, _ = run(
        ev,
        [node("s", "wolumen/seria", volume=vid), node("e", "segmentacja/edycja", strokes=strokes)],
        [edge("s", "e", ts="ref")],
        "e",
    )
    assert out2["info"]["voxels"] == pytest.approx(4 / 3 * np.pi * (125 - 27), rel=0.12)


def test_cached_segment_feeds_downstream_after_restart(env) -> None:
    """A restart empties the in-memory memo: the threshold result then comes from the disk
    cache and must still arrive downstream as a segment (it used to arrive as None)."""
    ev, vid, parts, lib = env
    g = ev.source_volume(vid).geometry
    strokes = [{"p": [list(world(g, (25, 30, 30)))], "r": 4.0, "mode": "erase"}]
    graph = (
        [
            node("s", "wolumen/seria", volume=vid),
            node("t", "segmentacja/prog", lo=500, hi=5000),
            node("e", "segmentacja/edycja", strokes=strokes),
        ],
        [edge("s", "t"), edge("t", "e")],
    )
    first, _ = run(ev, *graph, "e")
    fresh = Evaluator("w", ev.ws_dir, lib, Hub())
    fresh_graph = (
        graph[0][:2] + [node("e", "segmentacja/edycja", strokes=strokes + strokes)],
        graph[1],
    )
    again, _ = run(fresh, *fresh_graph, "e")  # the threshold node is a disk-cache hit here
    assert again["info"]["voxels"] == first["info"]["voxels"]


def test_logic_and_compose(env) -> None:
    ev, vid, parts, _ = env
    ns = [
        node("s", "wolumen/seria", volume=vid),
        node("t", "segmentacja/prog", lo=500, hi=5000),
        node("w", "segmentacja/wyspy", mode="largest", count=1),
        node("x", "segmentacja/logika", op="sub"),
        node("z", "segmentacja/zloz"),
        node("u", "segmentacja/rozloz", label=2),
    ]
    es = [
        edge("s", "t"),
        edge("t", "w"),
        edge("t", "x", ts="a"),
        edge("w", "x", ts="b"),
        edge("w", "z"),
        edge("x", "z"),
        edge("z", "u"),
    ]
    out, res = run(ev, ns, es, "u")
    np.testing.assert_array_equal(
        arr(ev, res["x"]["outputs"]["out"]) > 0, parts["small"] | parts["shell"]
    )
    lab = res["z"]["outputs"]["out"]
    assert lab["kind"] == "segmentacja" and [x["id"] for x in lab["info"]["labels"]] == [1, 2]
    np.testing.assert_array_equal(arr(ev, out) > 0, parts["small"] | parts["shell"])


def test_otsu_separates_objects(env) -> None:
    ev, vid, parts, _ = env
    _, res = run(
        ev,
        [node("s", "wolumen/seria", volume=vid), node("o", "segmentacja/otsu")],
        [edge("s", "o")],
        "o",
    )
    t = res["o"]["outputs"]["prog"]["value"]
    assert 30 < t < 1000  # just above the noise (0–39), far below the objects
    assert (
        res["o"]["outputs"]["out"]["info"]["voxels"]
        == (parts["big"] | parts["small"] | parts["shell"]).sum()
    )


def test_label_pyramid_keeps_thin_structures(tmp_path: Path) -> None:
    lab = np.zeros((8, 130, 130), np.uint8)
    lab[:, 64, :] = 1  # one-voxel-thin line
    g = Geometry(
        size=(130, 130, 8),
        spacing=(1, 1, 1),
        origin=(0, 0, 0),
        direction=(1, 0, 0, 0, 1, 0, 0, 0, 1),
    )
    w = store.VolumeWriter(tmp_path / "l.zarr", g, np.uint8, label=True)
    w.append(lab)
    meta = w.finish(lambda p: None, {})
    l1 = store.open_level(tmp_path / "l.zarr", 1)[:]
    assert l1.max() == 1 and l1[:, 32, :].all()  # survives (a mean pyramid would round it away)
    assert meta["stats"]["labels"] == {"1": 8 * 130}


def test_dicom_seg_import_aligns_with_series(tmp_path: Path) -> None:
    import highdicom as hd
    import pydicom
    from pydicom.sr.codedict import codes

    vol, parts = phantom((20, 30, 40))
    write_series(
        tmp_path / "in", vol, spacing=(0.8, 0.6), slice_gap=1.5, intercept=0, origin=(5, -7, 11)
    )
    srcs = sorted(
        (pydicom.dcmread(p) for p in (tmp_path / "in").glob("*.dcm")),
        key=lambda d: float(d.ImagePositionPatient[2]),
    )
    frame = hd.UID()
    for d in srcs:  # type-2 attributes highdicom requires on source images (may be empty)
        d.PatientBirthDate = ""
        d.StudyTime = ""
        d.ReferringPhysicianName = ""
        d.StudyID = ""
        d.AccessionNumber = ""
        d.FrameOfReferenceUID = frame
        d.PositionReferenceIndicator = ""
    mask = (vol >= 1000).astype(np.uint8)  # [k, j, i] in slice order of `srcs`
    desc = hd.seg.SegmentDescription(
        segment_number=1,
        segment_label="Aneurysm",
        segmented_property_category=codes.SCT.Tissue,
        segmented_property_type=codes.SCT.Tissue,
        algorithm_type=hd.seg.SegmentAlgorithmTypeValues.MANUAL,
    )
    seg = hd.seg.Segmentation(
        source_images=srcs,
        pixel_array=mask,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=[desc],
        series_instance_uid=hd.UID(),
        series_number=99,
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer="test",
        manufacturer_model_name="t",
        software_versions="1",
        device_serial_number="1",
        omit_empty_frames=False,
    )
    (tmp_path / "seg").mkdir()
    seg.save_as(tmp_path / "seg" / "seg.dcm")

    cands = scan([str(tmp_path / "in"), str(tmp_path / "seg")], lambda p, m: None)
    series = next(c for c in cands if c.kind == "dicom")
    segc = next(c for c in cands if c.kind == "seg")
    assert segc.geometry.size == series.geometry.size
    np.testing.assert_allclose(segc.geometry.spacing, series.geometry.spacing, atol=1e-6)
    np.testing.assert_allclose(segc.geometry.origin, series.geometry.origin, atol=1e-4)
    np.testing.assert_allclose(segc.geometry.direction, series.geometry.direction, atol=1e-6)

    ws = tmp_path / "ws"
    for d in ("store", "series", "cache"):
        (ws / d).mkdir(parents=True)
    lib = Library()
    vid = import_candidate(Job("j", "i", "t", "w"), tmp_path, ws, lib, segc, True)["vid"]
    entry = lib.get(ws, vid)
    assert entry["kind"] == "labelmap" and entry["labels"][0]["name"] == "Aneurysm"
    np.testing.assert_array_equal(store.open_level(lib.volume_path(ws, vid), 0)[:], mask)

    ev = Evaluator("w", ws, lib, Hub())
    out, _ = run(ev, [node("l", "segmentacja/import", volume=vid)], [], "l")
    assert out["kind"] == "segmentacja" and out["info"]["labels"][0]["name"] == "Aneurysm"


def _cut_run(ev, vid, cut):
    out, _ = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("t", "segmentacja/prog", lo=500, hi=5000),
            node("e", "segmentacja/edycja", strokes=[cut]),
        ],
        [edge("s", "t"), edge("t", "e")],
        "e",
    )
    return arr(ev, out) > 0


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
AROUND_BIG = [[10, 15], [37.5, 15], [37.5, 45], [10, 45]]  # x (= i) 10..37.5, y (= j) 15..45


def test_scissors_2d_through_all_slices(env) -> None:
    ev, vid, parts, _ = env
    m = _cut_run(
        ev, vid, {"kind": "cut", "mode": "erase", "M": IDENTITY, "poly": AROUND_BIG, "z": None}
    )
    np.testing.assert_array_equal(m, parts["small"] | parts["shell"])


def test_scissors_one_slice_and_keep(env) -> None:
    ev, vid, parts, _ = env
    one = _cut_run(
        ev,
        vid,
        {"kind": "cut", "mode": "erase", "M": IDENTITY, "poly": AROUND_BIG, "z": [29.5, 30.5]},
    )
    want = parts["big"] | parts["small"] | parts["shell"]
    want[30] &= ~parts["big"][30]  # only slice k = 30 of the big sphere is cut
    np.testing.assert_array_equal(one, want)
    keep = _cut_run(
        ev,
        vid,
        {
            "kind": "cut",
            "mode": "keep",
            "M": IDENTITY,
            "poly": [[64, 24], [77, 24], [77, 37], [64, 37]],
            "z": None,
        },
    )
    np.testing.assert_array_equal(keep, parts["small"])


def test_scissors_perspective_from_3d_view(env) -> None:
    ev, vid, parts, _ = env
    # camera at (25, -100, 30) looking along +y, up +z: x_cam = x - 25, y_cam = z - 30, w = y + 100
    M = [1, 0, 0, -25, 0, 0, 1, -30, 0, 1, 0, 100, 0, 1, 0, 100]
    poly = [[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]]
    m = _cut_run(ev, vid, {"kind": "cut", "mode": "erase", "M": M, "poly": poly, "z": None})
    np.testing.assert_array_equal(m, parts["small"] | parts["shell"])
