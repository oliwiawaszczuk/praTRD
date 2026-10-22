"""Folder/file scan → importable candidates (DICOM stacks and NIfTI/NRRD/MHA volumes).

Headers only, read sequentially: 621 headers take 0.2 s and threads make it SLOWER
(pure-Python parsing holds the GIL), so no pool here.
"""

import hashlib
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

from ..volumes.geometry import Geometry
from .frames import Frame, frames_from_header
from .stack import PixelFormat, Stack, build_stacks

NIFTI_EXT = (".nii", ".nii.gz")
ITK_EXT = (".nrrd", ".nhdr", ".mha", ".mhd")
SEG_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.66.4"
_SKIP_SOP_CLASSES = {
    "1.2.840.10008.1.3.10",  # Media Storage Directory (DICOMDIR)
    "1.2.840.10008.5.1.4.1.1.481.3",  # RT Structure Set (E4)
}


@dataclass
class Candidate:
    id: int
    kind: str  # "dicom" | "nifti" | "itk"
    name: str
    geometry: Geometry
    dtype: np.dtype
    warnings: list[str]
    fingerprint: str
    info: dict[str, Any] = field(default_factory=dict)  # modality, patient, study, …
    stack: Stack | None = None
    header_path: str = ""  # representative DICOM file (tags, window)
    file_path: str = ""  # NIfTI / ITK source
    rgb: bool = False

    def summary(self, imported: set[str]) -> dict[str, Any]:
        nbytes = int(np.prod(self.geometry.size)) * self.dtype.itemsize
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "size": list(self.geometry.size),
            "spacing": [round(s, 4) for s in self.geometry.spacing],
            "dtype": self.dtype.name,
            "rawBytes": nbytes,
            "warnings": self.warnings,
            "alreadyImported": self.fingerprint in imported,
            **self.info,
        }


def _is_volume_file(name: str) -> str | None:
    low = name.lower()
    if low.endswith(NIFTI_EXT):
        return "nifti"
    if low.endswith(ITK_EXT):
        return "itk"
    return None


def _walk(paths: Iterable[str]) -> list[str]:
    files: list[str] = []
    stack = [Path(p) for p in paths]
    while stack:
        p = stack.pop()
        if p.is_dir():
            try:
                with os.scandir(p) as it:
                    for e in it:
                        if e.name.startswith("."):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file():
                            files.append(e.path)
            except PermissionError:
                continue
        elif p.is_file():
            files.append(str(p))
    files.sort()
    return files


def _str(ds: pydicom.Dataset, kw: str) -> str:
    v = getattr(ds, kw, "")
    return str(v).strip() if v is not None else ""


def _fmt_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d


def scan(paths: list[str], report: Callable[[float, str], None]) -> list[Candidate]:
    files = _walk(paths)
    report(0.0, f"Znaleziono {len(files)} plików")
    groups: dict[tuple, list[Frame]] = defaultdict(list)
    headers: dict[tuple, pydicom.Dataset] = {}
    header_paths: dict[tuple, str] = {}
    volume_files: list[tuple[str, str]] = []
    seg_files: list[str] = []

    for n, path in enumerate(files):
        if n % 32 == 0:
            report(0.9 * n / max(len(files), 1), f"Nagłówki {n}/{len(files)}")
        kind = _is_volume_file(path)
        if kind:
            volume_files.append((path, kind))
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except (InvalidDicomError, OSError, ValueError, EOFError, KeyError, TypeError):
            continue
        sop = str(getattr(ds, "SOPClassUID", ""))
        if sop in _SKIP_SOP_CLASSES:
            continue
        if sop == SEG_SOP_CLASS:
            seg_files.append(path)
            continue
        frames = frames_from_header(ds, path)
        if not frames:
            continue
        f0 = frames[0]
        key = (
            _str(ds, "SeriesInstanceUID") or path,
            tuple(round(x, 3) for x in f0.orientation) if f0.orientation else None,
            f0.rows,
            f0.cols,
            int(getattr(ds, "SamplesPerPixel", 1) or 1),
        )
        groups[key].extend(frames)
        if key not in headers:
            headers[key] = ds
            header_paths[key] = path

    candidates: list[Candidate] = []
    for key, frames in groups.items():
        ds = headers[key]
        fmt = PixelFormat(
            bits_stored=int(getattr(ds, "BitsStored", 16) or 16),
            signed=int(getattr(ds, "PixelRepresentation", 0) or 0) == 1,
            samples=int(getattr(ds, "SamplesPerPixel", 1) or 1),
        )
        for stack in build_stacks(frames, fmt):
            candidates.append(_dicom_candidate(len(candidates), ds, header_paths[key], stack))

    for path, kind in volume_files:
        try:
            candidates.append(_volume_file_candidate(len(candidates), path, kind))
        except Exception:  # noqa: BLE001 — unreadable file: just not a candidate
            continue

    for path in seg_files:
        try:
            candidates.append(_seg_candidate(len(candidates), path))
        except Exception:  # noqa: BLE001 — unreadable SEG: just not a candidate
            continue

    report(1.0, f"{len(candidates)} serii")
    return candidates


def _dicom_candidate(cid: int, ds: pydicom.Dataset, header_path: str, stack: Stack) -> Candidate:
    series_uid = _str(ds, "SeriesInstanceUID")
    modality = _str(ds, "Modality")
    desc = _str(ds, "SeriesDescription")
    number = _str(ds, "SeriesNumber")
    name = (
        desc if desc and desc.upper() != "ANONYMOUS" else f"{modality or 'Seria'} {number}".strip()
    )
    if stack.n_phases > 1:
        name += f" — faza {stack.phase + 1}/{stack.n_phases}"
    g = stack.geometry
    p0 = stack.frames[0].position
    pn = stack.frames[-1].position
    fp = hashlib.sha1(f"{series_uid}|{stack.phase}|{g.size}|{p0}|{pn}".encode()).hexdigest()
    windows = _window(ds)
    info = {
        "modality": modality,
        "patientName": str(getattr(ds, "PatientName", "") or ""),
        "patientId": _str(ds, "PatientID"),
        "patientSex": _str(ds, "PatientSex"),
        "patientAge": _str(ds, "PatientAge"),
        "studyDescription": _str(ds, "StudyDescription"),
        "studyDate": _fmt_date(_str(ds, "StudyDate")),
        "seriesNumber": number,
        "bodyPart": _str(ds, "BodyPartExamined"),
        "manufacturer": _str(ds, "Manufacturer"),
        "transferSyntax": str(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "")),
        "photometric": _str(ds, "PhotometricInterpretation"),
        "nFiles": len({f.path for f in stack.frames}),
        "window": windows,
    }
    return Candidate(
        id=cid,
        kind="dicom",
        name=name,
        geometry=g,
        dtype=stack.dtype,
        warnings=stack.warnings,
        fingerprint=fp,
        info=info,
        stack=stack,
        header_path=header_path,
        rgb=stack.rgb,
    )


def _window(ds: pydicom.Dataset) -> dict[str, float] | None:
    c, w = getattr(ds, "WindowCenter", None), getattr(ds, "WindowWidth", None)
    try:
        c = float(c[0] if isinstance(c, (list, pydicom.multival.MultiValue)) else c)
        w = float(w[0] if isinstance(w, (list, pydicom.multival.MultiValue)) else w)
    except (TypeError, ValueError, IndexError):
        return None
    return {"center": c, "width": w} if w > 0 else None


def _volume_file_candidate(cid: int, path: str, kind: str) -> Candidate:
    from ..volumes.files import probe

    geom, dtype, warnings = probe(path, kind)
    fp = hashlib.sha1(
        f"{kind}|{os.path.abspath(path)}|{os.path.getsize(path)}".encode()
    ).hexdigest()
    base = os.path.basename(path)
    for ext in (*NIFTI_EXT, *ITK_EXT):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
            break
    return Candidate(
        id=cid,
        kind=kind,
        name=base,
        geometry=geom,
        dtype=dtype,
        warnings=warnings,
        fingerprint=fp,
        info={"modality": "", "nFiles": 1, "window": None},
        file_path=path,
    )


def _seg_candidate(cid: int, path: str) -> Candidate:
    from ..volumes.files import read_seg

    _, geom, labels = read_seg(path)
    ds = pydicom.dcmread(path, stop_before_pixels=True)
    desc = _str(ds, "SeriesDescription") or "Segmentacja DICOM"
    fp = hashlib.sha1(f"seg|{_str(ds, 'SOPInstanceUID') or path}".encode()).hexdigest()
    return Candidate(
        id=cid,
        kind="seg",
        name=desc,
        geometry=geom,
        dtype=np.dtype(np.uint8),
        warnings=[],
        fingerprint=fp,
        info={"modality": "SEG", "nFiles": 1, "window": None, "segments": len(labels)},
        file_path=path,
    )
