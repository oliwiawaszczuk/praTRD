"""NIfTI / NRRD / MetaImage sources: header probe + slab iterator in [k, j, i] order.

NIfTI is streamed slab by slab through nibabel's array proxy (memory = one slab).
ITK formats go through SimpleITK, which reads NRRD as a whole (its NRRD IO cannot
stream) — acceptable because these files are single images that already fit in RAM
on the machine that wrote them.
"""

from collections.abc import Iterator

import numpy as np

from .geometry import Geometry

_RAS_TO_LPS = np.diag([-1.0, -1.0, 1.0])


def _geometry_from_affine(
    affine: np.ndarray, size: tuple[int, int, int]
) -> tuple[Geometry, list[str]]:
    warnings: list[str] = []
    m = _RAS_TO_LPS @ affine[:3, :3]
    spacing = np.linalg.norm(m, axis=0)
    spacing[spacing == 0] = 1.0
    d = m / spacing
    # Sheared affines are rare (and not representable as origin+spacing+rotation): snap
    # to the nearest rotation via SVD and say so.
    if not np.allclose(d.T @ d, np.eye(3), atol=1e-4):
        u, _, vt = np.linalg.svd(d)
        d = u @ vt
        warnings.append("Macierz affine ze ścięciem — przybliżona najbliższą rotacją.")
    origin = _RAS_TO_LPS @ affine[:3, 3]
    geom = Geometry(
        size=size,
        spacing=tuple(float(s) for s in spacing),
        origin=tuple(float(o) for o in origin),
        direction=tuple(float(x) for x in d.ravel()),
    )
    return geom, warnings


def _nifti(path: str):  # noqa: ANN202
    import nibabel as nib

    img = nib.load(path)
    shape = img.shape
    warnings: list[str] = []
    if len(shape) > 3 and int(np.prod(shape[3:])) > 1:
        warnings.append(f"Obraz {len(shape)}D {shape} — zaimportowano pierwszy wolumen (t = 0).")
    size = (
        int(shape[0]),
        int(shape[1]) if len(shape) > 1 else 1,
        int(shape[2]) if len(shape) > 2 else 1,
    )
    geom, w = _geometry_from_affine(img.affine, size)
    warnings += w
    raw = np.dtype(img.get_data_dtype())
    if raw.kind == "c" or raw.names is not None:
        raise ValueError("Obrazy zespolone / RGB w NIfTI nie są obsługiwane")
    # nibabel normalises missing/NaN scl_slope to 1 and scl_inter to 0.
    slope, inter = float(img.dataobj.slope), float(img.dataobj.inter)
    scaled = (slope, inter) != (1.0, 0.0)
    # Any scaling → float32 (scaled ints may not fit the raw integer type).
    dtype = raw if raw.kind in "iuf" and not scaled and raw != np.float64 else np.dtype(np.float32)
    if raw == np.float64:
        warnings.append("Dane float64 zapisane jako float32.")
    return img, geom, dtype, warnings


def _itk_reader(path: str):  # noqa: ANN202
    import SimpleITK as sitk

    r = sitk.ImageFileReader()
    r.SetFileName(path)
    r.ReadImageInformation()
    return r


def probe(path: str, kind: str) -> tuple[Geometry, np.dtype, list[str]]:
    if kind == "nifti":
        _, geom, dtype, warnings = _nifti(path)
        return geom, dtype, warnings
    import SimpleITK as sitk

    r = _itk_reader(path)
    if r.GetNumberOfComponents() != 1:
        raise ValueError("Obrazy wektorowe nie są obsługiwane")
    if r.GetDimension() not in (2, 3):
        raise ValueError(f"Obraz {r.GetDimension()}D nie jest obsługiwany")
    size = tuple(r.GetSize()) + (1,) * (3 - r.GetDimension())
    spacing = tuple(r.GetSpacing()) + (1.0,) * (3 - r.GetDimension())
    origin = tuple(r.GetOrigin()) + (0.0,) * (3 - r.GetDimension())
    d = np.eye(3)
    nd = r.GetDimension()
    d[:nd, :nd] = np.asarray(r.GetDirection()).reshape(nd, nd)
    dtype = np.dtype(sitk.GetArrayViewFromImage(sitk.Image([1] * nd, r.GetPixelID())).dtype)
    if dtype == np.float64:
        dtype = np.dtype(np.float32)
    geom = Geometry(
        size=tuple(int(s) for s in size),  # type: ignore[arg-type]
        spacing=tuple(float(s) for s in spacing),  # type: ignore[arg-type]
        origin=tuple(float(o) for o in origin),  # type: ignore[arg-type]
        direction=tuple(float(x) for x in d.ravel()),
    )
    return geom, dtype, []


def iter_slabs(path: str, kind: str, slab: int) -> Iterator[np.ndarray]:
    """Yield [dk, nj, ni] slabs in increasing k."""
    if kind == "nifti":
        img, geom, dtype, _ = _nifti(path)
        ni, nj, nk = geom.size
        proxy = img.dataobj
        nd = len(img.shape)
        for k0 in range(0, nk, slab):
            k1 = min(nk, k0 + slab)
            if nd == 2:
                block = np.asarray(proxy[:, :])[:, :, None]
            elif nd == 3:
                block = np.asarray(proxy[:, :, k0:k1])
            else:
                block = np.asarray(
                    proxy[(slice(None), slice(None), slice(k0, k1)) + (0,) * (nd - 3)]
                )
            yield np.ascontiguousarray(block.transpose(2, 1, 0), dtype=dtype)
        return

    import SimpleITK as sitk

    image = sitk.ReadImage(path)
    arr = sitk.GetArrayViewFromImage(image)  # [k, j, i] (or [j, i] for 2-D)
    if arr.ndim == 2:
        arr = arr[None]
    dtype = np.float32 if arr.dtype == np.float64 else arr.dtype
    for k0 in range(0, arr.shape[0], slab):
        yield np.ascontiguousarray(arr[k0 : k0 + slab], dtype=dtype)


def read_seg(path: str) -> tuple[np.ndarray, Geometry, list[dict]]:
    """DICOM-SEG → (uint8 label map [k, j, i], geometry, [{id, name}]).

    highdicom's Volume indexes its array as (slice, row, column) with an affine mapping those
    indices to LPS — i.e. its axes 0/1/2 are our k/j/i. Overlapping segments: later wins."""
    import highdicom as hd

    seg = hd.seg.segread(path)
    vol = seg.get_volume(
        combine_segments=True, relabel=True, dtype=np.uint8, skip_overlap_checks=True
    )
    a = np.ascontiguousarray(vol.array)
    if a.ndim == 2:
        a = a[None]
    aff = np.asarray(vol.affine, dtype=np.float64)
    cols = [aff[:3, 2], aff[:3, 1], aff[:3, 0]]  # i, j, k
    origin = aff[:3, 3].copy()
    # same convention as our DICOM series: k runs along (row × column) — highdicom may
    # return the slice axis reversed; flip so a SEG shares the exact grid of its series
    if a.shape[0] > 1 and float(np.dot(np.cross(cols[0], cols[1]), cols[2])) < 0:
        origin = origin + cols[2] * (a.shape[0] - 1)
        cols[2] = -cols[2]
        a = np.ascontiguousarray(a[::-1])
    spacing = [float(np.linalg.norm(c)) or 1.0 for c in cols]
    d = np.column_stack([c / s for c, s in zip(cols, spacing, strict=True)])
    geom = Geometry(
        size=(int(a.shape[2]), int(a.shape[1]), int(a.shape[0])),
        spacing=tuple(spacing),  # type: ignore[arg-type]
        origin=tuple(float(x) for x in origin),  # type: ignore[arg-type]
        direction=tuple(float(x) for x in d.ravel()),
    )
    labels = [
        {"id": n, "name": str(getattr(sd, "SegmentLabel", f"Segment {n}"))}
        for n, sd in enumerate(seg.SegmentSequence, start=1)
    ]
    return a, geom, labels
