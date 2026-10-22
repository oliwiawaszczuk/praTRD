"""Frames of one series/orientation → ordered stack(s) with geometry, dtype and warnings.

Sorting is by the position projected on the slice normal (never by InstanceNumber, which
scanners do not fill consistently). Frames repeating the same position are phases
(time / echo / b-value) and become separate volumes.
"""

from dataclasses import dataclass, field

import numpy as np

from ..volumes.geometry import Geometry, orthonormal
from .frames import Frame

_POS_TOL_MM = 1e-3
_TILT_WARN_DEG = 0.5


@dataclass
class PixelFormat:
    bits_stored: int
    signed: bool
    samples: int  # 1 = grey, 3 = RGB


@dataclass
class Stack:
    frames: list[Frame]
    geometry: Geometry
    dtype: np.dtype
    rgb: bool
    warnings: list[str] = field(default_factory=list)
    phase: int = 0
    n_phases: int = 1


def output_dtype(frames: list[Frame], fmt: PixelFormat) -> np.dtype:
    """Smallest dtype that holds stored*slope+intercept for every frame without loss."""
    if fmt.samples == 3:
        return np.dtype(np.uint8)
    lo_s = -(1 << (fmt.bits_stored - 1)) if fmt.signed else 0
    hi_s = (1 << (fmt.bits_stored - 1)) - 1 if fmt.signed else (1 << fmt.bits_stored) - 1
    integer = all(f.slope == int(f.slope) and f.intercept == int(f.intercept) for f in frames)
    if not integer:
        return np.dtype(np.float32)
    lo = min(min(lo_s * f.slope, hi_s * f.slope) + f.intercept for f in frames)
    hi = max(max(lo_s * f.slope, hi_s * f.slope) + f.intercept for f in frames)
    for dt in (np.uint8, np.int16, np.uint16, np.int32):
        info = np.iinfo(dt)
        if info.min <= lo and hi <= info.max:
            # uint8 only for genuinely 8-bit data (keeps CT/MR in 16-bit even if a scanner
            # declares fewer bits stored).
            if dt is np.uint8 and fmt.bits_stored > 8:
                continue
            return np.dtype(dt)
    return np.dtype(np.float32)


def build_stacks(frames: list[Frame], fmt: PixelFormat) -> list[Stack]:
    f0 = frames[0]
    rgb = fmt.samples == 3
    dtype = output_dtype(frames, fmt)
    warnings: list[str] = []
    if rgb:
        warnings.append("Obraz kolorowy (RGB) — zapisany jako skala szarości (luminancja).")

    spacing_rc = f0.pixel_spacing
    if spacing_rc is None:
        warnings.append("Brak PixelSpacing — przyjęto 1 mm.")
        spacing_rc = (1.0, 1.0)

    have_geometry = f0.orientation is not None and all(f.position is not None for f in frames)
    if not have_geometry:
        return [_stack_without_geometry(frames, spacing_rc, dtype, rgb, warnings)]

    iop = np.asarray(f0.orientation, dtype=np.float64)
    i_ax, j_ax = iop[:3], iop[3:]
    normal = np.cross(i_ax, j_ax)
    normal /= np.linalg.norm(normal)
    dist = np.array([float(np.dot(f.position, normal)) for f in frames])  # type: ignore[arg-type]
    order = sorted(
        range(len(frames)), key=lambda n: (round(dist[n] / _POS_TOL_MM), frames[n].order)
    )

    # Group equal positions; the m-th frame at each position belongs to phase m.
    positions: list[list[int]] = []
    for n in order:
        if positions and abs(dist[n] - dist[positions[-1][0]]) < _POS_TOL_MM:
            positions[-1].append(n)
        else:
            positions.append([n])
    counts = {len(p) for p in positions}
    n_phases = min(counts)
    if len(counts) > 1:
        warnings.append(
            f"Niekompletna seria wielofazowa ({min(counts)}–{max(counts)} ramek na pozycję) — "
            f"zaimportowano {n_phases} pełn{'ą fazę' if n_phases == 1 else 'e fazy'}."
        )

    stacks = []
    for phase in range(n_phases):
        idx = [p[phase] for p in positions]
        stacks.append(
            _stack_with_geometry(
                [frames[n] for n in idx],
                dist[idx],
                i_ax,
                j_ax,
                normal,
                spacing_rc,
                dtype,
                rgb,
                list(warnings),
                phase,
                n_phases,
            )
        )
    return stacks


def _stack_with_geometry(
    frames: list[Frame],
    dist: np.ndarray,
    i_ax: np.ndarray,
    j_ax: np.ndarray,
    normal: np.ndarray,
    spacing_rc: tuple[float, float],
    dtype: np.dtype,
    rgb: bool,
    warnings: list[str],
    phase: int,
    n_phases: int,
) -> Stack:
    nk = len(frames)
    if nk > 1:
        gaps = np.diff(dist)
        sk = float(np.median(gaps))
        dev = np.abs(gaps - sk)
        if float(dev.max()) > max(0.01 * sk, 0.01):
            missing = int(np.sum(gaps > 1.5 * sk))
            msg = (
                f"Nierówne odstępy warstw ({gaps.min():.3f}–{gaps.max():.3f} mm, "
                f"mediana {sk:.3f} mm)"
            )
            if missing:
                msg += f", prawdopodobnie brakuje {missing} warstw"
            warnings.append(msg + " — przyjęto medianę.")
        p0 = np.asarray(frames[0].position)
        p1 = np.asarray(frames[-1].position)
        along = (p1 - p0) / np.linalg.norm(p1 - p0)
        tilt = float(np.degrees(np.arccos(np.clip(abs(along @ normal), -1, 1))))
        if tilt > _TILT_WARN_DEG:
            warnings.append(
                f"Pochylenie gantry {tilt:.1f}° — geometria wyprostowana (bez korekty)."
            )
    else:
        sk = frames[0].thickness or 1.0

    geom = Geometry(
        size=(frames[0].cols, frames[0].rows, nk),
        spacing=(float(spacing_rc[1]), float(spacing_rc[0]), float(sk)),
        origin=tuple(float(x) for x in frames[0].position),  # type: ignore[arg-type]
        direction=orthonormal(i_ax, j_ax),
    )
    return Stack(frames, geom, dtype, rgb, warnings, phase, n_phases)


def _stack_without_geometry(
    frames: list[Frame],
    spacing_rc: tuple[float, float],
    dtype: np.dtype,
    rgb: bool,
    warnings: list[str],
) -> Stack:
    warnings.append("Brak geometrii przestrzennej (pozycja/orientacja) — ramki ułożone kolejno.")
    frames = sorted(frames, key=lambda f: f.order)
    geom = Geometry(
        size=(frames[0].cols, frames[0].rows, len(frames)),
        spacing=(float(spacing_rc[1]), float(spacing_rc[0]), float(frames[0].thickness or 1.0)),
        origin=(0.0, 0.0, 0.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    )
    return Stack(frames, geom, dtype, rgb, warnings)
