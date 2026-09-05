"""Parse the BIDS JSON sidecar into `ScanMeta`.

dcm2niix writes a `.json` sidecar beside every NIfTI it converts; these helpers
read the acquisition metadata out of it. Phase-encode *axis* resolution lives in
`pe_axis`; the DICOM row/col *direction* string for the report header is derived
here (`_pe_direction`) from the same sidecar.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..exceptions import MissingSidecarError
from .pe_axis import PE_ROWCOL


@dataclass(frozen=True)
class ScanMeta:
    """Human-readable acquisition metadata for the report header.

    Geometry (`voxel_mm`, `matrix`, `tr`) comes from the NIfTI header and is
    always present. The rest comes from the BIDS JSON sidecar written alongside
    the NIfTI (dcm2niix) and is `None` when no sidecar is found. `voxel_mm` is
    (row, col, slice-spacing) from the header zooms; `slice_thickness` is the
    excited slab from the sidecar (the zoom is spacing, which includes any gap).
    `pe_dir` is the DICOM row/col direction.
    """

    voxel_mm: tuple[float, float, float]
    matrix: tuple[int, int]
    tr: float
    te: float | None = None  # s
    flip_angle: float | None = None  # degrees
    slice_thickness: float | None = None  # mm
    pe_dir: str | None = None  # "row" / "col"
    coil: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    field_strength: float | None = None  # tesla
    software: str | None = None
    datetime: str | None = None  # acquisition date and/or time
    series: str | None = None


def _load_sidecar(path: str | Path) -> dict[str, Any]:
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
        data: dict[str, Any] = json.load(f)
    return data


def _acq_datetime(sidecar: dict[str, Any]) -> str | None:
    """Acquisition date/time from the sidecar, seconds-precision; None if absent.

    Siemens often anonymizes the date away, leaving only `AcquisitionTime`.
    """
    if dt := sidecar.get("AcquisitionDateTime"):
        return str(dt).split(".")[0].replace("T", " ")
    date, time = sidecar.get("AcquisitionDate"), sidecar.get("AcquisitionTime")
    time = str(time).split(".")[0] if time else None
    return " ".join(x for x in (date, time) if x) or None


def _pe_direction(pe_axis: int | None, sidecar: dict[str, Any]) -> str | None:
    """DICOM row/col phase-encode direction, preferring the sidecar."""
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return str(dicom).lower()
    if ped := sidecar.get("PhaseEncodingDirection"):
        return PE_ROWCOL.get({"i": 0, "i-": 0, "j": 1, "j-": 1}.get(str(ped), -1))
    return PE_ROWCOL.get(pe_axis) if pe_axis is not None else None


def _scan_meta(img: Any, sidecar: dict[str, Any], pe_axis: int | None) -> ScanMeta:
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
