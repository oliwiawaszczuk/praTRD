"""Synthetic DICOM / NIfTI writers with exactly known geometry and voxel values."""

from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    RLELossless,
    generate_uid,
)


def ramp_volume(nk: int, nj: int, ni: int) -> np.ndarray:
    """Stored values [k, j, i] = i + 10 j + 100 k (unique → any axis mix-up is detected)."""
    k, j, i = np.meshgrid(np.arange(nk), np.arange(nj), np.arange(ni), indexing="ij")
    return (i + 10 * j + 100 * k).astype(np.uint16)


def write_series(
    folder: Path,
    stored: np.ndarray,
    *,
    spacing=(0.5, 0.7),  # (row, col) mm
    slice_gap=1.25,
    origin=(-10.0, 20.0, 30.0),
    iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    intercept=-1024.0,
    slope=1.0,
    series_uid: str | None = None,
    temporal: int | None = None,
    gaps: list[float] | None = None,
    rle: bool = False,
    shuffle_seed: int | None = 0,
    patient=("Kowalska^Anna", "PESEL123"),
    bits_stored: int = 12,
) -> list[Path]:
    """One file per slice, in a shuffled file order (sorting must use positions)."""
    folder.mkdir(parents=True, exist_ok=True)
    nk, nj, ni = stored.shape
    row = np.asarray(iop[:3])
    col = np.asarray(iop[3:])
    normal = np.cross(row, col)
    series_uid = series_uid or generate_uid()
    offsets = np.concatenate([[0.0], np.cumsum(gaps)]) if gaps else np.arange(nk) * slice_gap
    order = np.arange(nk)
    if shuffle_seed is not None:
        np.random.default_rng(shuffle_seed).shuffle(order)
    paths = []
    for n, k in enumerate(order):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.SeriesInstanceUID = series_uid
        ds.StudyInstanceUID = "1.2.3.4"
        ds.Modality = "CT"
        ds.PatientName, ds.PatientID = patient
        ds.PatientSex = "F"
        ds.PatientAge = "042Y"
        ds.StudyDate = "20240115"
        ds.InstitutionName = "Szpital"
        ds.SeriesDescription = "Synth"
        ds.SeriesNumber = 7
        ds.InstanceNumber = int(n + 1)  # deliberately NOT the spatial order
        if temporal is not None:
            ds.TemporalPositionIdentifier = temporal
        ds.ImageOrientationPatient = [float(x) for x in iop]
        pos = np.asarray(origin) + normal * offsets[k]
        ds.ImagePositionPatient = [float(x) for x in pos]
        ds.PixelSpacing = [float(spacing[0]), float(spacing[1])]
        ds.SliceThickness = float(slice_gap)
        ds.Rows, ds.Columns = nj, ni
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = bits_stored
        ds.HighBit = bits_stored - 1
        ds.PixelRepresentation = 0
        ds.RescaleIntercept = intercept
        ds.RescaleSlope = slope
        ds.PixelData = np.ascontiguousarray(stored[k]).tobytes()
        if rle:
            ds.compress(RLELossless)
        p = folder / f"f{temporal or 0}_{n:04d}.dcm"
        ds.save_as(p, enforce_file_format=True)
        paths.append(p)
    return paths


def write_nifti(path: Path, data_ijk: np.ndarray, affine: np.ndarray) -> None:
    import nibabel as nib

    nib.save(nib.Nifti1Image(data_ijk, affine), str(path))
