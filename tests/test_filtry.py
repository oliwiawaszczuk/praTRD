import shutil
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from pratrd import nodes  # noqa: F401
from pratrd.dicom.scan import scan
from pratrd.graph.evaluator import Evaluator
from pratrd.graph.values import ARRAYS
from pratrd.jobs import Cancelled, Job
from pratrd.nodes import filtry
from pratrd.volumes.importer import import_candidate
from pratrd.volumes.library import Library

from .synth import write_series
from .test_graph import Hub, edge, node

N = (48, 64, 64)  # k, j, i


def phantom() -> np.ndarray:
    """Stored values (HU + 1024): tubes along k (r 1, 2, 3.5 vox), a ball, a slow bias
    across i (×0.8 … ×1.2) on soft tissue, plus noise."""
    k, j, i = np.meshgrid(*(np.arange(s) for s in N), indexing="ij")
    hu = np.full(N, 40.0)
    for cx, cy, r in [(14, 14, 1.0), (40, 14, 2.0), (20, 44, 3.5)]:
        hu[((i - cx) ** 2 + (j - cy) ** 2) <= r * r] = 300
    hu[((i - 46) ** 2 + (j - 46) ** 2 + (k - 24) ** 2) <= 25] = 300
    hu += np.random.default_rng(0).normal(0, 15, N)
    return np.clip(hu + 1024, 0, 4095).astype(np.uint16)


@pytest.fixture
def fenv(tmp_path: Path):
    ws = tmp_path / "ws"
    for d in ("store", "series", "cache"):
        (ws / d).mkdir(parents=True)
    write_series(tmp_path / "in", phantom(), spacing=(1.0, 1.0), slice_gap=1.0, origin=(0, 0, 0))
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    lib = Library()
    vid = import_candidate(Job("j", "i", "t", "w"), tmp_path, ws, lib, c, True)["vid"]
    return Evaluator("w", ws, lib, Hub()), vid


def run(ev, nodes_, edges_, target):
    res = ev.evaluate(
        Job("j", "graph", "t", "w"), "g", {"nodes": nodes_, "edges": edges_}, [target], "full"
    )
    assert res[target]["state"] == "done", res[target]
    out = res[target]["outputs"]["out"]
    return out, ARRAYS.get(ev.ws_dir / "cache" / f"{out['ref']}.zarr", 0)


def src_hu(ev, vid):
    return ARRAYS.get(ev.ws_dir / "store" / f"{vid}.zarr", 0).astype(np.float32)


LOCAL = [
    ("filtry/krawedzie", {"method": "gradient", "sigma": 1.5}),
    ("filtry/krawedzie", {"method": "log", "sigma": 1.0}),
    ("filtry/naczyniowosc", {"sigma_min": 1.0, "sigma_max": 3.0, "steps": 3}),
    ("filtry/wyostrz", {"sigma": 1.0, "amount": 1.0}),
    ("filtry/morfologia_szarosci", {"op": "tophat", "radius": 3.0}),
]


@pytest.mark.parametrize(("type_", "params"), LOCAL)
def test_slabs_equal_whole_volume(fenv, monkeypatch, type_, params) -> None:
    ev, vid = fenv
    graph = [node("s", "wolumen/seria", volume=vid), node("f", type_, **params)]
    monkeypatch.setattr(filtry, "SLAB_VOXELS", 1 << 40)  # one slab = the whole volume
    _, whole = run(ev, graph, [edge("s", "f")], "f")
    whole = np.array(whole)
    for p in ev.ws_dir.joinpath("cache").glob("*"):  # recompute, not a cache hit
        p.unlink() if p.is_file() else shutil.rmtree(p)
    ev._memo.clear()
    monkeypatch.setattr(filtry, "SLAB_VOXELS", 64 * 64 * 9)  # 9-slice slabs
    _, slabbed = run(ev, graph, [edge("s", "f")], "f")
    # integer outputs: float noise of ~1e-4 may round the other way (±1)
    tol = 1.0 if whole.dtype.kind in "iu" else 1e-3 * float(np.abs(whole).max() or 1)
    np.testing.assert_allclose(slabbed.astype(np.float64), whole.astype(np.float64), atol=tol)


def test_vesselness_finds_tubes_not_balls(fenv) -> None:
    ev, vid = fenv
    out, a = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("f", "filtry/naczyniowosc", sigma_min=0.7, sigma_max=3.0, steps=4, contrast=260),
        ],
        [edge("s", "f")],
        "f",
    )
    assert a.dtype == np.float32 and out["info"]["modality"] == ""
    tubes = [a[24, cy, cx] for cx, cy in [(14, 14), (40, 14), (20, 44)]]
    assert min(tubes) > 0.4, tubes
    assert a[24, 46, 46] < 0.25 * min(tubes)  # a ball is not a tube
    assert np.percentile(a[:, 54:, :8], 99) < 0.05  # background noise


def test_distance_map_of_ball(fenv) -> None:
    ev, vid = fenv
    _, d = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("t", "segmentacja/prog", lo=250, hi=5000),
            node("w", "segmentacja/wyspy", mode="largest", count=1),  # the r 3.5 tube
            node("d", "filtry/mapa_odleglosci"),
        ],
        [edge("s", "t"), edge("t", "w"), edge("w", "d")],
        "d",
    )
    # ITK measures to the boundary voxels (±½ voxel of the drawn radius 3.5 mm)
    assert -3.6 < d[24, 44, 20] < -1.9  # centre: inside, negative
    assert d[24, 44, 30] == pytest.approx(10 - 3.5, abs=1.0)  # 10 mm from the axis
    assert np.all(np.diff(d[24, 44, 24:40]) > 0.9)  # grows 1 mm per mm outwards


def test_mask_and_arithmetic(fenv) -> None:
    ev, vid = fenv
    base = [
        node("s", "wolumen/seria", volume=vid),
        node("t", "segmentacja/prog", lo=250, hi=5000),
        node("m", "filtry/maskuj", mode="inside", fill="min"),
    ]
    edges = [edge("s", "t"), edge("s", "m"), edge("t", "m", ts="seg")]
    _, m = run(ev, base, edges, "m")
    src = src_hu(ev, vid)
    inside = src >= 250
    np.testing.assert_array_equal(m[inside], src[inside])
    assert (m[~inside] == src.min()).all()
    # difference of the volume with itself on a cropped grid: 0 everywhere
    _, z = run(
        ev,
        [*base, node("a", "filtry/arytmetyka", op="absdiff")],
        [*edges, edge("s", "a", ts="a"), edge("m", "a", ts="b")],
        "a",
    )
    assert z.dtype == np.float32
    np.testing.assert_allclose(z[inside], 0, atol=1e-3)
    np.testing.assert_allclose(z[~inside], src[~inside] - src.min(), atol=1e-2)


@pytest.mark.parametrize("method", ["curvature", "gradient"])
def test_diffusion_denoises_and_keeps_edges(fenv, method) -> None:
    ev, vid = fenv
    _, a = run(
        ev,
        [
            node("s", "wolumen/seria", volume=vid),
            node("f", "filtry/odszumianie", method=method, iterations=8, conductance=1.5),
        ],
        [edge("s", "f")],
        "f",
    )
    src = src_hu(ev, vid)
    flat = (slice(None), slice(54, 64), slice(0, 8))
    assert a[flat].std() < 0.5 * src[flat].std()
    # the edge of the big tube stays sharp: inside − outside contrast kept
    assert a[24, 44, 20] - a[24, 44, 27] > 0.85 * (300 - 40)


def test_n4_flattens_a_bias_field(tmp_path: Path) -> None:
    k, j, i = np.meshgrid(*(np.arange(s) for s in (40, 48, 48)), indexing="ij")
    tissue = 100 + np.random.default_rng(1).normal(0, 2, i.shape)
    biased = (tissue * (0.75 + 0.5 * i / 47)).astype(np.float32)
    img = sitk.GetImageFromArray(biased)
    ws = tmp_path / "ws"
    for d in ("store", "series", "cache"):
        (ws / d).mkdir(parents=True)

    class Ctx:
        def report(self, *_a, **_k):
            pass

        def volume_result(self, arr, g, info, **_k):
            return arr

    from pratrd.graph.values import VolumeValue, from_sitk

    arr, g = from_sitk(img)
    v = VolumeValue("x" * 12, ws, 0, g, {"name": "MR"})
    v.array = lambda: arr  # type: ignore[method-assign]
    out = filtry._n4(Ctx(), {"in": [v]}, {"shrink": 2, "iterations": 30})["out"]
    cv = lambda a: float(a.std() / a.mean())  # noqa: E731
    assert cv(out) < 0.4 * cv(biased)


def test_itk_filter_is_aborted_on_cancel() -> None:
    class Ctx:
        calls = 0

        def report(self, *_a, **_k):
            Ctx.calls += 1
            if Ctx.calls > 2:
                raise Cancelled

    img = sitk.GetImageFromArray(np.random.default_rng(0).random((40, 64, 64)).astype(np.float32))
    f = sitk.CurvatureAnisotropicDiffusionImageFilter()
    f.SetNumberOfIterations(200)
    f.SetTimeStep(0.0625)
    with pytest.raises(Cancelled):
        filtry.run_filter(Ctx(), f, img)


def test_frangi_scales_are_geometric() -> None:
    s = filtry.frangi_scales(0.5, 4.0, 4)
    assert s[0] == pytest.approx(0.5) and s[-1] == pytest.approx(4.0)
    assert s[1] / s[0] == pytest.approx(s[2] / s[1])
    assert filtry.frangi_scales(1.0, 1.0, 5) == [1.0]


def test_vesselness_is_finite_on_flat_air(fenv) -> None:
    ev, vid = fenv

    class Ctx:
        def report(self, *_a, **_k):
            pass

        def volume_result(self, arr, g, info, **_k):
            return arr, info

    from pratrd.graph.values import VolumeValue
    from pratrd.volumes.geometry import Geometry

    flat = np.full((24, 32, 32), -1000, np.int16)  # air outside the field of view
    flat[8:16, 8:24, 14:18] = 300
    v = VolumeValue(
        "a" * 12,
        ev.ws_dir,
        0,
        Geometry((32, 32, 24), (1, 1, 1), (0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1)),
        {},
    )
    v.array = lambda: flat  # type: ignore[method-assign]
    params = {
        "sigma_min": 0.5,
        "sigma_max": 2.0,
        "steps": 2,
        "contrast": 200,
        "shape": "tube",
        "bright": True,
    }
    arr, info = filtry._naczynia(Ctx(), {"in": [v]}, params)["out"]
    assert np.isfinite(arr).all() and arr[0, 0, 0] == 0
    assert all(np.isfinite(x) for x in info["window"].values())
