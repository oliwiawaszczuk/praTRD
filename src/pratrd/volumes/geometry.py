"""Volume geometry in DICOM patient space (LPS, millimetres).

Conventions used everywhere in praTRD:
  * voxel arrays are C-ordered [k, j, i] (slice, row, column) — i varies fastest;
  * spacing / direction columns / sizes are given in (i, j, k) order, like ITK;
  * world_LPS = origin + D @ (spacing * [i, j, k]), D columns = unit axes of i, j, k;
  * origin is the CENTRE of voxel (0, 0, 0).
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Geometry:
    size: tuple[int, int, int]  # (ni, nj, nk)
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    direction: tuple[float, ...]  # 3×3 row-major, columns = i, j, k axes

    @property
    def shape_kji(self) -> tuple[int, int, int]:
        return (self.size[2], self.size[1], self.size[0])

    @property
    def matrix(self) -> np.ndarray:
        return np.asarray(self.direction, dtype=np.float64).reshape(3, 3)

    def to_json(self) -> dict:
        return {
            "size": list(self.size),
            "spacing": [round(s, 6) for s in self.spacing],
            "origin": [round(o, 6) for o in self.origin],
            "direction": [round(d, 8) for d in self.direction],
        }

    @staticmethod
    def from_json(d: dict) -> "Geometry":
        return Geometry(
            size=tuple(d["size"]),
            spacing=tuple(d["spacing"]),
            origin=tuple(d["origin"]),
            direction=tuple(d["direction"]),
        )

    def downsampled(self, factors: tuple[int, int, int]) -> "Geometry":
        """Geometry of a block-mean downsample by integer (fi, fj, fk) factors.

        Block (0..f-1) averages to its centre, so the new voxel-0 centre moves by
        (f-1)/2 old voxels along each axis.
        """
        f = np.asarray(factors, dtype=np.float64)
        sp = np.asarray(self.spacing)
        shift = self.matrix @ ((f - 1) / 2 * sp)
        size = tuple(int(-(-n // int(fi))) for n, fi in zip(self.size, factors, strict=True))
        return Geometry(
            size=size,
            spacing=tuple(float(x) for x in sp * f),
            origin=tuple(float(x) for x in np.asarray(self.origin) + shift),
            direction=self.direction,
        )


def orthonormal(i_axis: np.ndarray, j_axis: np.ndarray) -> tuple[float, ...]:
    """Row-major 3×3 with columns i, j, k = i × j (right-handed)."""
    i_axis = i_axis / np.linalg.norm(i_axis)
    j_axis = j_axis - i_axis * float(i_axis @ j_axis)
    j_axis = j_axis / np.linalg.norm(j_axis)
    k_axis = np.cross(i_axis, j_axis)
    return tuple(float(x) for x in np.column_stack([i_axis, j_axis, k_axis]).ravel())


def pyramid_factors(
    spacing: tuple[float, float, float], size: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Per-axis factor (1 or 2) for the next pyramid level.

    Anisotropic data (e.g. CT 0.39 × 0.39 × 0.9 mm) first halves only the fine axes, so
    coarse levels approach isotropic voxels — what volume rendering wants — instead of
    making the coarse axis even coarser. Axes of size 1 are never halved.
    """
    coarsest = max(s for s, n in zip(spacing, size, strict=True) if n > 1) if max(size) > 1 else 1.0
    f = tuple(
        2 if n > 1 and s * 2 <= coarsest * 1.5 else 1 for s, n in zip(spacing, size, strict=True)
    )
    if f == (1, 1, 1):
        f = tuple(2 if n > 1 else 1 for n in size)
    return f  # type: ignore[return-value]
