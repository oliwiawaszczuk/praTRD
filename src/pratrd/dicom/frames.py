"""Per-frame geometry extracted from DICOM headers (no pixel data is read here).

Classic files contribute one frame each; enhanced multi-frame files (MR/CT/PET "Enhanced")
contribute one frame per entry of PerFrameFunctionalGroupsSequence. Everything downstream
(grouping, sorting, geometry, decoding) works on this flat Frame list.
"""

from dataclasses import dataclass
from typing import Any

from pydicom.dataset import Dataset


@dataclass(slots=True)
class Frame:
    path: str
    index: int  # frame index inside the file (0 for classic single-frame)
    rows: int
    cols: int
    position: tuple[float, float, float] | None  # ImagePositionPatient
    orientation: tuple[float, ...] | None  # ImageOrientationPatient (6)
    pixel_spacing: tuple[float, float] | None  # (row spacing, col spacing)
    thickness: float | None
    slope: float
    intercept: float
    order: tuple[Any, ...]  # tie-breaker for frames sharing a position (phases / echoes)


def _floats(v: Any, n: int) -> tuple[float, ...] | None:
    try:
        vals = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        return None
    return vals if len(vals) == n else None


def _num(v: Any, default: float | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _seq_item(ds: Dataset | None, keyword: str) -> Dataset | None:
    if ds is None:
        return None
    seq = getattr(ds, keyword, None)
    return seq[0] if seq else None


def frames_from_header(ds: Dataset, path: str) -> list[Frame]:
    rows = int(getattr(ds, "Rows", 0) or 0)
    cols = int(getattr(ds, "Columns", 0) or 0)
    if not rows or not cols:
        return []
    n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    per_frame = getattr(ds, "PerFrameFunctionalGroupsSequence", None)
    if n_frames > 1 and per_frame:
        return _enhanced_frames(ds, path, rows, cols, n_frames, per_frame)

    position = _floats(getattr(ds, "ImagePositionPatient", None), 3)
    orientation = _floats(getattr(ds, "ImageOrientationPatient", None), 6)
    spacing = _floats(getattr(ds, "PixelSpacing", None), 2) or _floats(
        getattr(ds, "ImagerPixelSpacing", None), 2
    )
    thickness = _num(getattr(ds, "SpacingBetweenSlices", None), None) or _num(
        getattr(ds, "SliceThickness", None), None
    )
    order = (
        _num(getattr(ds, "TemporalPositionIdentifier", None), 0),
        _num(getattr(ds, "AcquisitionNumber", None), 0),
        _num(getattr(ds, "EchoNumbers", None), 0),
        _num(getattr(ds, "TriggerTime", None), 0),
        str(getattr(ds, "AcquisitionTime", "") or ""),
        _num(getattr(ds, "InstanceNumber", None), 0),
    )
    slope = _num(getattr(ds, "RescaleSlope", None), 1.0) or 1.0
    intercept = _num(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0
    if n_frames > 1:
        # Multi-frame without per-frame geometry (US cine, XA): frames stacked along the normal.
        return [
            Frame(
                path, f, rows, cols, None, orientation, spacing, thickness, slope, intercept, (f,)
            )
            for f in range(n_frames)
        ]
    return [
        Frame(
            path, 0, rows, cols, position, orientation, spacing, thickness, slope, intercept, order
        )
    ]


def _enhanced_frames(
    ds: Dataset, path: str, rows: int, cols: int, n_frames: int, per_frame: Any
) -> list[Frame]:
    shared = _seq_item(ds, "SharedFunctionalGroupsSequence")

    def lookup(fg: Dataset | None, seq: str, attr: str) -> Any:
        for src in (fg, shared):
            item = _seq_item(src, seq)
            if item is not None and attr in item:
                return item.get(attr)
        return None

    frames: list[Frame] = []
    for f in range(min(n_frames, len(per_frame))):
        fg = per_frame[f]
        position = _floats(lookup(fg, "PlanePositionSequence", "ImagePositionPatient"), 3)
        orientation = _floats(lookup(fg, "PlaneOrientationSequence", "ImageOrientationPatient"), 6)
        spacing = _floats(lookup(fg, "PixelMeasuresSequence", "PixelSpacing"), 2)
        thickness = _num(lookup(fg, "PixelMeasuresSequence", "SpacingBetweenSlices"), None) or _num(
            lookup(fg, "PixelMeasuresSequence", "SliceThickness"), None
        )
        slope = _num(lookup(fg, "PixelValueTransformationSequence", "RescaleSlope"), None)
        intercept = _num(lookup(fg, "PixelValueTransformationSequence", "RescaleIntercept"), None)
        if slope is None:
            slope = _num(getattr(ds, "RescaleSlope", None), 1.0) or 1.0
        if intercept is None:
            intercept = _num(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0
        content = _seq_item(fg, "FrameContentSequence")
        idx = tuple(getattr(content, "DimensionIndexValues", ()) or ()) if content else ()
        order = (
            _num(getattr(content, "TemporalPositionIndex", None), 0) if content else 0,
            *[_num(v, 0) for v in idx[1:]],
            f,
        )
        frames.append(
            Frame(
                path,
                f,
                rows,
                cols,
                position,
                orientation,
                spacing,
                thickness,
                slope,
                intercept,
                order,
            )
        )
    return frames
