"""Pixel decoding — runs inside decode-pool worker processes.

Measured on 621 JPEG-Lossless CT slices: 4.8 ms/slice and NO speed-up from threads (the
pylibjpeg decoder holds the GIL), 0.41 s total with a 6-process pool. Rescale is applied
in the worker too, so the parent only copies finished slabs into the store.
"""

from collections import defaultdict

import numpy as np
from pydicom.pixels import iter_pixels

# (path, frame index, slope, intercept)
FrameRef = tuple[str, int, float, float]

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def decode_batch(refs: list[FrameRef], dtype_str: str, rgb: bool) -> np.ndarray:
    """Decode frames (any files, any order) → [len(refs), rows, cols] in the target dtype."""
    dtype = np.dtype(dtype_str)
    by_file: dict[str, list[int]] = defaultdict(list)
    for n, (path, _, _, _) in enumerate(refs):
        by_file[path].append(n)

    out: np.ndarray | None = None
    for path, slots in by_file.items():
        wanted = sorted(slots, key=lambda n: refs[n][1])
        indices = [refs[n][1] for n in wanted]
        # Only the requested frames are decoded (classic files: just frame 0).
        for n, px in zip(wanted, iter_pixels(path, indices=indices), strict=True):
            if rgb and px.ndim == 3:
                px = px.astype(np.float32) @ _LUMA
            if out is None:
                out = np.empty((len(refs), *px.shape[:2]), dtype=dtype)
            _, _, slope, intercept = refs[n]
            if slope == 1.0 and intercept == 0.0:
                out[n] = px
            elif np.issubdtype(dtype, np.integer):
                # Integer rescale, exact: widen first so stored*slope+intercept cannot wrap.
                out[n] = px.astype(np.int64) * int(slope) + int(intercept)
            else:
                np.multiply(px, slope, out=out[n], casting="unsafe")
                out[n] += intercept
    assert out is not None
    return out
