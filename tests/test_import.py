import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from pratrd.dicom.scan import scan
from pratrd.jobs import Job
from pratrd.volumes import store
from pratrd.volumes.geometry import Geometry
from pratrd.volumes.importer import import_candidate
from pratrd.volumes.library import Library

from .synth import ramp_volume, write_nifti, write_series


def _ws(tmp: Path) -> Path:
    ws = tmp / "ws"
    (ws / "store").mkdir(parents=True)
    (ws / "series").mkdir()
    return ws


def _import(tmp: Path, cand, anonymize=True):
    ws = _ws(tmp) if not (tmp / "ws").exists() else tmp / "ws"
    lib = Library()
    r = import_candidate(Job("j", "import", "t", "w"), tmp, ws, lib, cand, anonymize)
    path = lib.volume_path(ws, r["vid"])
    return ws, lib, r["vid"], path


def _world(g: Geometry, ijk) -> np.ndarray:
    return np.asarray(g.origin) + g.matrix @ (np.asarray(g.spacing) * np.asarray(ijk, float))


def test_dicom_roundtrip_values_and_geometry(tmp_path: Path) -> None:
    stored = ramp_volume(9, 6, 5)
    write_series(tmp_path / "in", stored, rle=True)
    cands = scan([str(tmp_path / "in")], lambda p, m: None)
    assert len(cands) == 1
    c = cands[0]
    assert c.dtype == np.int16  # 12-bit unsigned + intercept -1024 → [-1024, 3071]
    ws, lib, vid, path = _import(tmp_path, c)

    vol = zarr.open_array(path / "0", mode="r")[:]
    np.testing.assert_array_equal(vol, stored.astype(np.int32) - 1024)

    g = Geometry.from_json(store.read_meta(path)["levels"][0])
    assert g.size == (5, 6, 9)
    assert g.spacing == pytest.approx((0.7, 0.5, 1.25))
    assert g.origin == pytest.approx((-10.0, 20.0, 30.0))
    np.testing.assert_allclose(g.matrix, np.eye(3), atol=1e-9)


def test_output_dtype_widens_when_needed(tmp_path: Path) -> None:
    # 16-bit unsigned full range + intercept -1024 does not fit int16.
    stored = ramp_volume(3, 4, 4)
    stored[0, 0, 0] = 65535
    write_series(tmp_path / "in", stored, bits_stored=16)
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    assert c.dtype == np.int32


def test_oblique_orientation_and_reverse_order(tmp_path: Path) -> None:
    a = np.radians(30)
    iop = (np.cos(a), np.sin(a), 0.0, 0.0, 0.0, -1.0)  # rotated, rows go towards feet
    stored = ramp_volume(5, 4, 3)
    write_series(tmp_path / "in", stored, iop=iop, origin=(1.0, 2.0, 3.0), slice_gap=2.0)
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    _, _, _, path = _import(tmp_path, c)
    g = Geometry.from_json(store.read_meta(path)["levels"][0])
    vol = zarr.open_array(path / "0", mode="r")[:]
    np.testing.assert_array_equal(vol, stored.astype(np.int32) - 1024)
    # Voxel (i, j, k) must land where the generator put it.
    row, col = np.asarray(iop[:3]), np.asarray(iop[3:])
    normal = np.cross(row, col)
    for ijk in [(0, 0, 0), (2, 3, 4), (1, 0, 3)]:
        expect = np.array([1.0, 2.0, 3.0]) + row * 0.7 * ijk[0] + col * 0.5 * ijk[1]
        expect += normal * 2.0 * ijk[2]
        np.testing.assert_allclose(_world(g, ijk), expect, atol=1e-6)


def test_phases_split_into_separate_volumes(tmp_path: Path) -> None:
    uid = "1.2.826.0.1.99"
    write_series(tmp_path / "in", ramp_volume(4, 3, 3), series_uid=uid, temporal=1)
    write_series(tmp_path / "in", ramp_volume(4, 3, 3) + 7, series_uid=uid, temporal=2)
    cands = scan([str(tmp_path / "in")], lambda p, m: None)
    assert len(cands) == 2
    assert {c.name.split("—")[-1].strip() for c in cands} == {"faza 1/2", "faza 2/2"}
    first = min(cands, key=lambda c: c.name)
    _, _, _, path = _import(tmp_path, first)
    vol = zarr.open_array(path / "0", mode="r")[:]
    np.testing.assert_array_equal(vol, ramp_volume(4, 3, 3).astype(np.int32) - 1024)


def test_uneven_spacing_warns(tmp_path: Path) -> None:
    write_series(tmp_path / "in", ramp_volume(5, 3, 3), gaps=[1.0, 1.0, 3.0, 1.0])
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    assert any("Nierówne odstępy" in w and "brakuje 1" in w for w in c.warnings)
    assert c.geometry.spacing[2] == pytest.approx(1.0)


def test_pyramid_geometry_and_values(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    stored = rng.integers(0, 3000, size=(70, 130, 129)).astype(np.uint16)
    write_series(tmp_path / "in", stored, spacing=(0.5, 0.5), slice_gap=0.5, intercept=0)
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    _, _, _, path = _import(tmp_path, c)
    meta = store.read_meta(path)
    assert len(meta["levels"]) >= 2
    g0, g1 = (Geometry.from_json(m) for m in meta["levels"][:2])
    assert g1.size == (65, 65, 35)
    # Voxel-0 centre of level 1 = centre of the 2×2×2 block it averages.
    np.testing.assert_allclose(_world(g1, (0, 0, 0)), _world(g0, (0.5, 0.5, 0.5)), atol=1e-9)
    l1 = zarr.open_array(path / "1", mode="r")[:]
    blk = stored[:2, :2, :2].astype(np.float64).mean()
    assert abs(int(l1[0, 0, 0]) - blk) <= 0.5 + 1e-9
    assert meta["stats"]["min"] == stored.min() and meta["stats"]["max"] == stored.max()


def test_anonymization(tmp_path: Path) -> None:
    write_series(tmp_path / "in", ramp_volume(3, 3, 3))
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    ws, lib, vid, _ = _import(tmp_path, c, anonymize=True)
    tags = json.loads((lib.series_dir(ws, vid) / "tags.json").read_text())
    names = {t["name"] for t in tags}
    assert "PatientName" not in names and "PatientID" not in names
    assert "InstitutionName" not in names and "StudyDate" not in names
    assert "PatientSex" in names and "PatientAge" in names  # retained characteristics
    uids = {t["name"] for t in tags if t["vr"] == "UI"}
    assert uids <= {"SOPClassUID"}, uids  # no instance UIDs survive
    e = lib.get(ws, vid)
    assert e["patientName"].startswith("ANON-") and "Kowalska" not in json.dumps(e)
    assert e["sourcePath"] is None
    # Same patient → same pseudonym.
    write_series(tmp_path / "in2", ramp_volume(3, 3, 3))
    (c2,) = scan([str(tmp_path / "in2")], lambda p, m: None)
    _, _, vid2, _ = _import(tmp_path, c2, anonymize=True)
    assert lib.get(ws, vid2)["patientName"] == e["patientName"]


def test_not_anonymized_keeps_identity(tmp_path: Path) -> None:
    write_series(tmp_path / "in", ramp_volume(3, 3, 3))
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    ws, lib, vid, _ = _import(tmp_path, c, anonymize=False)
    e = lib.get(ws, vid)
    assert e["patientName"] == "Kowalska^Anna" and e["sourcePath"]


def test_nifti_ras_to_lps(tmp_path: Path) -> None:
    data = np.arange(4 * 5 * 6, dtype=np.int16).reshape(4, 5, 6)  # [i, j, k]
    affine = np.array(
        [[-0.8, 0, 0, 50.0], [0, 0.9, 0, -20.0], [0, 0, 1.5, 7.0], [0, 0, 0, 1]], dtype=float
    )
    write_nifti(tmp_path / "v.nii.gz", data, affine)
    (c,) = scan([str(tmp_path)], lambda p, m: None)
    assert c.kind == "nifti" and c.name == "v"
    _, _, _, path = _import(tmp_path, c)
    g = Geometry.from_json(store.read_meta(path)["levels"][0])
    vol = zarr.open_array(path / "0", mode="r")[:]
    for ijk in [(0, 0, 0), (3, 4, 5), (1, 2, 3)]:
        ras = affine @ np.array([*ijk, 1.0])
        lps = np.array([-ras[0], -ras[1], ras[2]])
        np.testing.assert_allclose(_world(g, ijk), lps, atol=1e-5)
        assert vol[ijk[2], ijk[1], ijk[0]] == data[ijk]


def test_cancel_leaves_nothing(tmp_path: Path) -> None:
    write_series(tmp_path / "in", ramp_volume(40, 8, 8))
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    ws = _ws(tmp_path)
    job = Job("j", "import", "t", "w")
    job._cancel.set()
    from pratrd.jobs import Cancelled

    with pytest.raises(Cancelled):
        import_candidate(job, tmp_path, ws, Library(), c, True)
    assert list((ws / "store").iterdir()) == []
    assert Library().list(ws) == []


def test_large_series_uses_pool_and_matches(tmp_path: Path) -> None:
    stored = ramp_volume(80, 16, 16)  # > inline threshold → process pool path; max 7965
    write_series(tmp_path / "in", stored, rle=True, bits_stored=16, intercept=0)
    (c,) = scan([str(tmp_path / "in")], lambda p, m: None)
    assert c.dtype == np.uint16
    _, _, _, path = _import(tmp_path, c)
    np.testing.assert_array_equal(zarr.open_array(path / "0", mode="r")[:], stored)
