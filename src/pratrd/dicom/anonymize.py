"""De-identification of what praTRD keeps from DICOM headers.

Pixel data is converted into the store, and the original files are never copied — the
only identifying information praTRD could retain lives in the tag dump, the volume
metadata and the source path. All three are cleaned here, following the DICOM PS3.15
Basic Application Confidentiality Profile (subset relevant to images), with the
"Retain Patient Characteristics" option on by default (sex, age, size, weight are often
study variables — cf. Metadata.csv of the sample data).
"""

import hashlib
import secrets
from pathlib import Path

from pydicom.dataset import Dataset

# Removed regardless of options.
_REMOVE = (
    "PatientName",
    "PatientID",
    "OtherPatientIDs",
    "OtherPatientIDsSequence",
    "OtherPatientNames",
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientBirthName",
    "PatientMotherBirthName",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientInsurancePlanCodeSequence",
    "MilitaryRank",
    "BranchOfService",
    "MedicalRecordLocator",
    "EthnicGroup",
    "Occupation",
    "AdditionalPatientHistory",
    "PatientComments",
    "ResponsiblePerson",
    "ResponsibleOrganization",
    "CountryOfResidence",
    "RegionOfResidence",
    "PatientReligiousPreference",
    "ReferringPhysicianName",
    "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy",
    "OperatorsName",
    "PhysiciansOfRecord",
    "RequestingPhysician",
    "ScheduledPerformingPhysicianName",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
    "AccessionNumber",
    "StudyID",
    "RequestAttributesSequence",
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "ContentDate",
    "AcquisitionDateTime",
    "StudyTime",
    "SeriesTime",
    "AcquisitionTime",
    "ContentTime",
    "InstanceCreationDate",
    "InstanceCreationTime",
    "PerformedProcedureStepStartDate",
    "PerformedProcedureStepStartTime",
    "PerformedProcedureStepID",
    "ImageComments",
    "FrameOfReferenceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "MediaStorageSOPInstanceUID",
    "ReferencedImageSequence",
    "SourceImageSequence",
    "ReferencedStudySequence",
    "ReferencedPatientSequence",
    "ReferencedPerformedProcedureStepSequence",
)
_KEEP_UID_SUFFIXES = ("ClassUID", "TransferSyntaxUID", "CodingSchemeUID", "ContextUID")
_PATIENT_CHARACTERISTICS = ("PatientSex", "PatientAge", "PatientSize", "PatientWeight")


def _salt(root: Path) -> bytes:
    """Per-installation secret: pseudonyms are stable inside one installation (series of the
    same patient group together) but cannot be reversed or matched across installations."""
    f = root / ".anon_salt"
    try:
        return bytes.fromhex(f.read_text().strip())
    except (FileNotFoundError, ValueError):
        s = secrets.token_bytes(16)
        f.write_text(s.hex())
        return s


def pseudonym(root: Path, patient_id: str, patient_name: str) -> str:
    key = (patient_id or patient_name or "").encode()
    if not key:
        return "ANON"
    return "ANON-" + hashlib.sha256(_salt(root) + key).hexdigest()[:8].upper()


def anonymize_dataset(ds: Dataset, keep_characteristics: bool = True) -> None:
    """In place, recursively; private tags are dropped (they routinely carry PHI)."""
    ds.remove_private_tags()
    names = _REMOVE if keep_characteristics else _REMOVE + _PATIENT_CHARACTERISTICS
    for name in names:
        if name in ds:
            delattr(ds, name)
    if hasattr(ds, "file_meta"):
        for name in ("MediaStorageSOPInstanceUID",):
            if name in ds.file_meta:
                delattr(ds.file_meta, name)
    # Every UID that identifies an instance (study/series/SOP/irradiation event/frame of
    # reference/…) goes; UIDs naming a class, syntax or coding scheme identify nothing.
    for elem in list(ds):
        if elem.VR == "UI" and not elem.keyword.endswith(_KEEP_UID_SUFFIXES):
            del ds[elem.tag]
    for elem in ds:
        if elem.VR == "SQ":
            for item in elem.value:
                anonymize_dataset(item, keep_characteristics)
