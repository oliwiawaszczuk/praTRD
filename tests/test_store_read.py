from pathlib import Path

import numpy as np
import pytest
import zarr

from pratrd.volumes import store
from pratrd.volumes.geometry import Geometry


def _volume(tmp: Path, shape_kji=(70, 45, 130), dtype=np.int16) -> tuple[Path, np.ndarray]:
    rng = np.random.default_rng(3)
    data = rng.integers(-1000, 3000, size=shape_kji).astype(dtype)
    g = Geometry(
        size=shape_kji[::-1],
        spacing=(1, 1, 1),
        origin=(0, 0, 0),
        direction=(1, 0, 0, 0, 1, 0, 0, 0, 1),
    )
    w = store.VolumeWriter(tmp / "v.zarr", g, data.dtype)
    w.append(data)
    w.finish(lambda p: None, {})
    return tmp / "v.zarr", data


@pytest.mark.parametrize("budget", [512 << 20, 300_000])  # roomy / forces constant eviction
def test_chunk_cache_slices_match(tmp_path: Path, budget: int) -> None:
    path, data = _volume(tmp_path)
    cache = store.ChunkCache(budget)
    for axis in "kji":
        a = "kji".index(axis)
        for idx in (0, 1, 63, 64, 65, data.shape[a] - 1, 10_000):
            got = cache.read_slice(path, 0, axis, idx)
            want = np.take(data, min(idx, data.shape[a] - 1), axis=a)
            np.testing.assert_array_equal(got, want)
    assert (
        cache._bytes <= max(budget, 0) or budget < 64**3 * 2
    )  # bounded (one chunk may exceed tiny budgets)


def test_level_stream_roundtrip(tmp_path: Path) -> None:
    path, data = _volume(tmp_path, (9, 33, 130), np.uint16)  # edge > 64 → has level 1
    meta, total, gen = store.iter_level_bytes(path, 0)
    raw = b"".join(gen)
    assert total == len(raw) == data.nbytes and meta["shape"] == [9, 33, 130]
    np.testing.assert_array_equal(np.frombuffer(raw, dtype="<u2").reshape(data.shape), data)
    lvl1 = zarr.open_array(path / "1", mode="r")
    _, total1, gen1 = store.iter_level_bytes(path, 1)
    assert len(b"".join(gen1)) == total1 == lvl1.nbytes
