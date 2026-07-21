"""Parse the BIDS JSON sidecar into `ScanMeta`.

dcm2niix writes a `.json` sidecar beside every NIfTI it converts; these helpers
read the acquisition metadata and phase-encode direction out of it. The sidecar
is authoritative for the PE axis (see the project notes); the header fields are
fallbacks handled in `scan`.
"""

import json
from pathlib import Path

from .constants import _PE_ROWCOL
from .exceptions import MissingSidecarError
from .types import ScanMeta


def _load_sidecar(path: str | Path) -> dict:
    """Parse the required BIDS JSON sidecar beside `path` (.nii/.nii.gz -> .json).

    dcm2niix writes this alongside every NIfTI it converts, so a missing sidecar
    means the input did not go through the expected conversion; we refuse it
    rather than silently dropping metadata.

    Raises:
        MissingSidecarError: If no `.json` sidecar is found beside `path`.
    """
    p = Path(path)
    name = p.name
    for ext in (".nii.gz", ".nii"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    sidecar = p.with_name(name + ".json")
    if not sidecar.is_file():
        raise MissingSidecarError(sidecar)
    with sidecar.open() as f:
        return json.load(f)


def _acq_datetime(sidecar: dict) -> str | None:
    """Acquisition date/time from the sidecar, seconds-precision; None if absent.

    Siemens often anonymizes the date away, leaving only `AcquisitionTime`.
    """
    if dt := sidecar.get("AcquisitionDateTime"):
        return str(dt).split(".")[0].replace("T", " ")
    date, time = sidecar.get("AcquisitionDate"), sidecar.get("AcquisitionTime")
    time = str(time).split(".")[0] if time else None
    return " ".join(x for x in (date, time) if x) or None


def _pe_axis_from_sidecar(sidecar: dict) -> int | None:
    """PE axis (0/1/2) from the sidecar, or None if it carries no PE field.

    `PhaseEncodingDirection` (BIDS i/j/k, with an optional polarity we drop) maps
    straight to the array axis; `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) is
    the DICOM fallback (row = i = axis 0, col = j = axis 1).
    """
    if ped := sidecar.get("PhaseEncodingDirection"):
        return {"i": 0, "j": 1, "k": 2}.get(str(ped)[0])
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return {"ROW": 0, "COL": 1}.get(str(dicom).upper())
    return None


def _pe_direction(pe_axis: int | None, sidecar: dict) -> str | None:
    """DICOM row/col phase-encode direction, preferring the sidecar."""
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return str(dicom).lower()
    if ped := sidecar.get("PhaseEncodingDirection"):
        return _PE_ROWCOL.get({"i": 0, "j": 1}.get(str(ped)[0], -1))
    return _PE_ROWCOL.get(pe_axis) if pe_axis is not None else None


def _scan_meta(img, sidecar: dict, pe_axis: int | None) -> ScanMeta:
    """Assemble `ScanMeta` from the NIfTI header and (optional) BIDS sidecar."""
    zooms = img.header.get_zooms()
    return ScanMeta(
        voxel_mm=(float(zooms[0]), float(zooms[1]), float(zooms[2])),
        matrix=(int(img.shape[0]), int(img.shape[1])),
        tr=float(zooms[3]),
        te=sidecar.get("EchoTime"),
        flip_angle=sidecar.get("FlipAngle"),
        slice_thickness=sidecar.get("SliceThickness"),
        pe_dir=_pe_direction(pe_axis, sidecar),
        coil=sidecar.get("ReceiveCoilName"),
        manufacturer=sidecar.get("Manufacturer"),
        model=sidecar.get("ManufacturersModelName"),
        serial=sidecar.get("DeviceSerialNumber"),
        field_strength=sidecar.get("MagneticFieldStrength"),
        software=sidecar.get("SoftwareVersions"),
        datetime=_acq_datetime(sidecar),
        series=sidecar.get("SeriesDescription"),
    )
