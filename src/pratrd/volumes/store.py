"""Chunked multiscale volume store (Zarr v3).

Layout of one volume:  store/<vid>.zarr/{0,1,2,…}  + group attributes "pratrd"
  * level 0 = full resolution, every next level halves the finer axes (pyramid_factors);
  * chunks 64³, Blosc zstd-1 + bitshuffle — measured on a 621×512² CT: 326 MB raw → 137 MB,
    full-volume read 0.12 s, one axial slice 12 ms;
  * written into `<vid>.zarr.partial` and renamed on success, so a crash or cancel never
    leaves a half volume that looks valid.

Memory is bounded by one 64-slice slab (+ one 128-slice slab while building the pyramid),
independent of the number of slices.
"""

import shutil
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import zarr
from zarr.codecs import BloscCodec

from .geometry import Geometry, pyramid_factors

CHUNK = 64
SLAB_BUDGET = 128 << 20  # bytes of the level-0 write buffer
MIN_LEVEL_EDGE = 64  # stop the pyramid once the largest edge is ≤ this
HIST_BINS = 256
_HIST_PIECE = 1 << 22  # voxels per histogram step (32 MB of intp)
PARTIAL_SUFFIX = ".partial"
FORMAT_VERSION = 1


def _codec() -> BloscCodec:
    return BloscCodec(cname="zstd", clevel=1, shuffle="bitshuffle")


def chunks_for(shape_kji: tuple[int, int, int], itemsize: int) -> tuple[int, int, int]:
    """64³ chunks, except that the k-depth shrinks (down to 16) for very large slices so the
    one-slab write buffer stays ≤ SLAB_BUDGET (512² int16: 64 → 33 MB; 2048²: 16 → 128 MB)."""
    nk, nj, ni = shape_kji
    ck = CHUNK
    while ck > 16 and ck * nj * ni * itemsize > SLAB_BUDGET:
        ck //= 2
    return (max(1, min(ck, nk)), max(1, min(CHUNK, nj)), max(1, min(CHUNK, ni)))


def _create_level(
    group: zarr.Group, level: int, shape: tuple[int, int, int], dtype: np.dtype
) -> Any:
    return group.create_array(
        name=str(level),
        shape=shape,
        chunks=chunks_for(shape, np.dtype(dtype).itemsize),
        dtype=dtype,
        compressors=_codec(),
        fill_value=0,
        dimension_names=("k", "j", "i"),
    )


def _block_mean(slab: np.ndarray, f: tuple[int, int, int], out_dtype: np.dtype) -> np.ndarray:
    """Mean over (fk, fj, fi) blocks of a [k, j, i] slab; edges are padded by replication.

    Sums the fk·fj·fi strided sub-grids into an output-sized accumulator (int32 for ≤16-bit
    ints, else float64/float32): 4× faster than reshape(...).mean() and no slab-sized
    temporary. Integer results round half up (≤ 1 unit from round-half-even).
    """
    fi, fj, fk = f
    pad = [(0, (-n) % fac) for n, fac in zip(slab.shape, (fk, fj, fi), strict=True)]
    if any(p[1] for p in pad):
        slab = np.pad(slab, pad, mode="edge")
    if slab.dtype.kind in "iu" and slab.dtype.itemsize <= 2:
        acc_dtype = np.int32
    elif slab.dtype.kind in "iu":
        acc_dtype = np.float64
    else:
        acc_dtype = np.float32
    acc: np.ndarray | None = None
    for dk in range(fk):
        for dj in range(fj):
            for di in range(fi):
                sub = slab[dk::fk, dj::fj, di::fi]
                if acc is None:
                    acc = sub.astype(acc_dtype)
                else:
                    acc += sub
    assert acc is not None
    n = fi * fj * fk
    if n == 1:
        return acc.astype(out_dtype, copy=False)
    if acc_dtype is np.int32:
        acc += n // 2
        acc //= n
        return acc.astype(out_dtype, copy=False)
    acc /= n
    if np.issubdtype(out_dtype, np.integer):
        np.rint(acc, out=acc)
    return acc.astype(out_dtype, copy=False)


def _block_max(slab: np.ndarray, f: tuple[int, int, int]) -> np.ndarray:
    """Max over (fk, fj, fi) blocks — for label maps: a thin structure (vessel, 1 voxel) must
    survive on coarse levels instead of being averaged away; labels never blend."""
    fi, fj, fk = f
    pad = [(0, (-n) % fac) for n, fac in zip(slab.shape, (fk, fj, fi), strict=True)]
    if any(p[1] for p in pad):
        slab = np.pad(slab, pad, mode="edge")
    out: np.ndarray | None = None
    for dk in range(fk):
        for dj in range(fj):
            for di in range(fi):
                sub = slab[dk::fk, dj::fj, di::fi]
                out = sub.copy() if out is None else np.maximum(out, sub, out=out)
    assert out is not None
    return out


class _Histogram:
    """Exact integer histogram via bincount (fast, no binning error), float via np.histogram."""

    def __init__(self, vmin: float, vmax: float, integer: bool) -> None:
        self.vmin, self.vmax, self.integer = vmin, vmax, integer
        if integer:
            self.counts = np.zeros(int(vmax - vmin) + 1, dtype=np.int64)
        else:
            self.counts = np.zeros(4096, dtype=np.int64)

    def add(self, slab: np.ndarray) -> None:
        if self.integer and self.counts.size == 2:
            # only two values (a binary mask): counting the upper one is enough, and
            # count_nonzero is ~100× faster than bincount
            hi = np.count_nonzero(slab) if self.vmin == 0 else np.count_nonzero(slab == self.vmax)
            self.counts += (slab.size - hi, hi)
            return
        # Piecewise: bincount needs an intp copy of its input — on a whole 128-slice slab
        # that alone was a 268 MB spike.
        flat = slab.reshape(-1)
        for p in range(0, flat.size, _HIST_PIECE):
            piece = flat[p : p + _HIST_PIECE]
            if self.integer:
                idx = piece.astype(np.intp) - int(self.vmin)
                self.counts += np.bincount(idx, minlength=self.counts.size)
            else:
                h, _ = np.histogram(
                    piece, bins=self.counts.size, range=(self.vmin, self.vmax or 1.0)
                )
                self.counts += h

    def percentile(self, q: float) -> float:
        cdf = np.cumsum(self.counts)
        if cdf[-1] == 0:
            return self.vmin
        idx = int(np.searchsorted(cdf, q / 100 * cdf[-1]))
        width = (self.vmax - self.vmin) / max(self.counts.size - (1 if self.integer else 0), 1)
        return float(self.vmin + idx * width)

    def coarse(self) -> list[int]:
        """HIST_BINS-bin view for the UI."""
        edges = np.linspace(0, self.counts.size, HIST_BINS + 1).astype(np.int64)
        return [int(x) for x in np.add.reduceat(self.counts, edges[:-1])]


class VolumeWriter:
    """Streams slices in k order into level 0, then builds the pyramid and statistics.

    Usage:  w = VolumeWriter(path, geom, dtype); w.append(frames)...; info = w.finish(report)
    """

    def __init__(
        self, final_path: Path, geometry: Geometry, dtype: np.dtype, label: bool = False
    ) -> None:
        self.label = label  # label map: max-pyramid + per-label voxel counts
        self.final_path = final_path
        self.path = final_path.with_name(final_path.name + PARTIAL_SUFFIX)
        shutil.rmtree(self.path, ignore_errors=True)
        self.geometry = geometry
        self.dtype = np.dtype(dtype)
        self.group = zarr.open_group(self.path, mode="w", zarr_format=3)
        self.level0 = _create_level(self.group, 0, geometry.shape_kji, self.dtype)
        nk, nj, ni = geometry.shape_kji
        self._buf = np.empty((self.level0.chunks[0], nj, ni), dtype=self.dtype)
        self._fill = 0
        self._k = 0
        self._min = np.inf
        self._max = -np.inf

    @property
    def written(self) -> int:
        return self._k + self._fill

    def append(self, frames: np.ndarray) -> None:
        """frames: [n, nj, ni] in increasing k; any n. Flushes full 64-slice slabs."""
        if frames.ndim == 2:
            frames = frames[None]
        pos = 0
        while pos < frames.shape[0]:
            take = min(self._buf.shape[0] - self._fill, frames.shape[0] - pos)
            self._buf[self._fill : self._fill + take] = frames[pos : pos + take]
            self._fill += take
            pos += take
            if self._fill == self._buf.shape[0]:
                self._flush()

    def _flush(self) -> None:
        if not self._fill:
            return
        slab = self._buf[: self._fill]
        self.level0[self._k : self._k + self._fill] = slab
        self._min = min(self._min, float(slab.min()))
        self._max = max(self._max, float(slab.max()))
        self._k += self._fill
        self._fill = 0

    def abort(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def finish(
        self,
        report: Callable[[float], None],
        attrs: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Pyramid + stats + attributes, then atomically publish. report(0..1).
        `attrs` may be a function of the computed stats (e.g. a label census in the info)."""
        self._flush()
        nk = self.geometry.shape_kji[0]
        if self._k != nk:
            raise RuntimeError(f"Zapisano {self._k} z {nk} warstw")

        integer = np.issubdtype(self.dtype, np.integer)
        hist = _Histogram(self._min, self._max, integer and (self._max - self._min) <= 1 << 20)
        if integer and not hist.integer:
            hist = _Histogram(self._min, self._max, False)

        levels = [self.geometry]
        # Level 0 is read once: histogram + level 1 in the same pass.
        src, src_geom, level = self.level0, self.geometry, 0
        total_work = max(1, nk)
        done = 0
        while True:
            need_next = max(src_geom.size) > MIN_LEVEL_EDGE
            f = pyramid_factors(src_geom.spacing, src_geom.size) if need_next else (1, 1, 1)
            dst_geom = src_geom.downsampled(f) if need_next else None
            dst = (
                _create_level(self.group, level + 1, dst_geom.shape_kji, self.dtype)
                if dst_geom
                else None
            )
            if dst is None and level > 0:
                break
            _, fj, fk = f
            snk, snj, _ = src_geom.shape_kji
            # Tiles in (k, j) that map exactly onto whole destination chunks, so every
            # write is chunk-aligned and memory stays ~ (ck·fk)·(64·fj)·ni whatever the size.
            ck, cj = (dst.chunks[0], dst.chunks[1]) if dst is not None else src.chunks[:2]
            kstep, jstep = ck * fk, cj * fj
            for k0 in range(0, snk, kstep):
                for j0 in range(0, snj, jstep):
                    tile = src[k0 : k0 + kstep, j0 : j0 + jstep]
                    if level == 0:
                        hist.add(tile)
                    if dst is not None:
                        out = (
                            _block_max(tile, f) if self.label else _block_mean(tile, f, self.dtype)
                        )
                        dst[
                            k0 // fk : k0 // fk + out.shape[0], j0 // fj : j0 // fj + out.shape[1]
                        ] = out
                    del tile  # free before reading the next one
                if level == 0:
                    done = min(nk, k0 + kstep)
                    report(0.9 * done / total_work)
            if dst is None:
                break
            levels.append(dst_geom)
            src, src_geom, level = dst, dst_geom, level + 1

        stats = {
            "min": self._min,
            "max": self._max,
            "p1": hist.percentile(1),
            "p99": hist.percentile(99),
            "p0_5": hist.percentile(0.5),
            "p99_5": hist.percentile(99.5),
            "histogram": hist.coarse(),
        }
        if self.label and hist.integer:
            # exact voxel count per label value (the histogram IS the label census)
            stats["labels"] = {
                str(int(self._min) + n): int(c)
                for n, c in enumerate(hist.counts)
                if c and int(self._min) + n
            }
        meta = {
            "formatVersion": FORMAT_VERSION,
            "dtype": self.dtype.str,
            "levels": [g.to_json() for g in levels],
            "stats": stats,
            **(attrs(stats) if callable(attrs) else attrs),
        }
        self.group.attrs["pratrd"] = meta
        report(1.0)
        shutil.rmtree(self.final_path, ignore_errors=True)
        self.path.rename(self.final_path)
        return meta


def cleanup_partials(store_dir: Path) -> None:
    """Remove imports interrupted by a crash or kill (called at startup)."""
    if store_dir.is_dir():
        for p in store_dir.glob(f"*{PARTIAL_SUFFIX}"):
            shutil.rmtree(p, ignore_errors=True)


# ── reading ──────────────────────────────────────────────────────────────────

_OPEN_MAX = 32
_open_lock = threading.Lock()
_open: "OrderedDict[tuple[str, int], Any]" = OrderedDict()


def open_level(path: Path, level: int) -> Any:
    """Cached zarr array handle (metadata parsed once per volume/level)."""
    key = (str(path), level)
    with _open_lock:
        arr = _open.get(key)
        if arr is not None:
            _open.move_to_end(key)
            return arr
    arr = zarr.open_array(path / str(level), mode="r")
    with _open_lock:
        _open[key] = arr
        while len(_open) > _OPEN_MAX:
            _open.popitem(last=False)
    return arr


def forget(path: Path) -> None:
    with _open_lock:
        for key in [k for k in _open if k[0] == str(path)]:
            del _open[key]
    CHUNK_CACHE.forget(path)


def read_meta(path: Path) -> dict[str, Any]:
    return dict(zarr.open_group(path, mode="r").attrs["pratrd"])


class ChunkCache:
    """Byte-bounded LRU of decoded chunks for slice reads.

    Without it every slice decompresses its whole 64-deep chunk layer (axial 512² int16:
    33 MB → ~12 ms) and the next slice decompresses the same layer again. With it, the
    first slice of a layer pays once and the other 63 are assembled from memory.
    Chunks are stored individually (not as layers) so the bound holds for any volume size.
    """

    _READ_BYTES = 64 << 20  # max bytes per zarr read while filling a layer

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._map: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._bytes = 0

    def _get(self, key: tuple) -> np.ndarray | None:
        with self._lock:
            c = self._map.get(key)
            if c is not None:
                self._map.move_to_end(key)
            return c

    def _put(self, key: tuple, chunk: np.ndarray) -> None:
        with self._lock:
            if key in self._map:
                return
            self._map[key] = chunk
            self._bytes += chunk.nbytes
            while self._bytes > self.max_bytes and self._map:
                _, old = self._map.popitem(last=False)
                self._bytes -= old.nbytes

    def forget(self, path: Path) -> None:
        p = str(path)
        with self._lock:
            for key in [k for k in self._map if k[0] == p]:
                self._bytes -= self._map.pop(key).nbytes

    def read_slice(self, path: Path, level: int, axis: str, index: int) -> np.ndarray:
        arr = open_level(path, level)
        shape = arr.shape
        cs = arr.chunks
        a = "kji".index(axis)
        index = min(max(index, 0), shape[a] - 1)
        ca, within = divmod(index, cs[a])
        others = [d for d in range(3) if d != a]
        grid = [range(-(-shape[d] // cs[d])) for d in others]
        out_shape = tuple(shape[d] for d in others)
        out = np.empty(out_shape, dtype=arr.dtype)
        p = str(path)

        def key(c0: int, c1: int) -> tuple:
            coord = [0, 0, 0]
            coord[a], coord[others[0]], coord[others[1]] = ca, c0, c1
            return (p, level, *coord)

        # Hold every needed chunk locally: assembly must not depend on what the LRU keeps
        # (a small budget may evict a chunk read a moment ago).
        chunks: dict[tuple[int, int], np.ndarray] = {}
        missing: set[int] = set()
        for c0 in grid[0]:
            for c1 in grid[1]:
                c = self._get(key(c0, c1))
                if c is None:
                    missing.add(c0)
                else:
                    chunks[(c0, c1)] = c
        if missing:
            chunks.update(self._fill(arr, a, ca, others, sorted(missing), grid[1], key))

        for (c0, c1), chunk in chunks.items():
            plane = np.take(chunk, within, axis=a)
            s0 = c0 * cs[others[0]]
            s1 = c1 * cs[others[1]]
            out[s0 : s0 + plane.shape[0], s1 : s1 + plane.shape[1]] = plane
        return out

    def _fill(
        self, arr: Any, a: int, ca: int, others: list[int], rows: list[int], cols: range, key
    ) -> dict[tuple[int, int], np.ndarray]:  # noqa: ANN001
        """Read chunk rows of the layer in ≤ _READ_BYTES zarr calls; cache and return them."""
        got: dict[tuple[int, int], np.ndarray] = {}
        cs = arr.chunks
        row_bytes = cs[a] * cs[others[0]] * arr.shape[others[1]] * arr.dtype.itemsize
        per_read = max(1, self._READ_BYTES // max(row_bytes, 1))
        for g in range(0, len(rows), per_read):
            group = rows[g : g + per_read]
            # contiguous runs only (missing rows may have gaps)
            r0, r1 = group[0], group[-1] + 1
            sel: list[slice] = [slice(None)] * 3
            sel[a] = slice(ca * cs[a], (ca + 1) * cs[a])
            sel[others[0]] = slice(r0 * cs[others[0]], r1 * cs[others[0]])
            block = np.asarray(arr[tuple(sel)])
            for c0 in range(r0, r1):
                for c1 in cols:
                    csel: list[slice] = [slice(None)] * 3
                    csel[others[0]] = slice(
                        (c0 - r0) * cs[others[0]], (c0 - r0 + 1) * cs[others[0]]
                    )
                    csel[others[1]] = slice(c1 * cs[others[1]], (c1 + 1) * cs[others[1]])
                    # copy: a view would pin the whole block in memory after eviction
                    chunk = block[tuple(csel)].copy()
                    self._put(key(c0, c1), chunk)
                    got[(c0, c1)] = chunk
        return got


CHUNK_CACHE = ChunkCache(512 << 20)


def read_slice(path: Path, level: int, axis: str, index: int) -> np.ndarray:
    """2-D slice of a level. axis "k" → [j, i], "j" → [k, i], "i" → [k, j]."""
    if axis not in ("i", "j", "k"):
        raise ValueError(f"axis must be i/j/k, got {axis!r}")
    return CHUNK_CACHE.read_slice(path, level, axis, index)


def iter_level_bytes(path: Path, level: int) -> tuple[dict[str, Any], int, Any]:
    """(meta, total bytes, generator of little-endian slabs) for streaming a whole level.
    Memory = one chunk layer at a time, whatever the level size."""
    arr = open_level(path, level)
    le = arr.dtype.newbyteorder("<")
    total = int(np.prod(arr.shape)) * arr.dtype.itemsize
    meta = {"shape": list(arr.shape), "dtype": arr.dtype.name, "level": level}

    def gen():  # noqa: ANN202
        ck = arr.chunks[0]
        for k0 in range(0, arr.shape[0], ck):
            yield np.ascontiguousarray(arr[k0 : k0 + ck], dtype=le).tobytes()

    return meta, total, gen()
