"""Read the BIDS sidecar's acquisition metadata into `ScanMeta`.

dcm2niix writes a `.json` sidecar beside every NIfTI it converts; these helpers
read the acquisition metadata out of it, once `fmriqa_io` has parsed the JSON
into a mapping. The sidecar is optional, since a NIfTI exported straight off
the scanner never had one, so its absence leaves fields empty instead of
failing. Phase-encode axis resolution lives in `pe_axis` and TR
resolution in `repetition_time`. The row/col direction word the report header
shows is derived here (`_pe_direction`) from that resolved axis.
"""

import math
from dataclasses import dataclass

from ..exceptions import InvalidScanError
from ..types import Sidecar
from ..warn import warn
from .pe_axis import PE_ROWCOL, in_plane

__all__ = [
    "ScanMeta",
    "scan_meta",
]


@dataclass(frozen=True, slots=True)
class ScanMeta:
    """Human-readable acquisition metadata for the report header.

    Geometry (`voxel_mm`, `matrix`, `tr`) is always present: it comes from the
    NIfTI header, with `tr` the resolved repetition time in seconds, the same
    value the pipeline runs on (see `repetition_time`). The rest comes from the
    BIDS JSON sidecar written alongside the NIfTI (dcm2niix) and is `None` when
    no sidecar is found. `voxel_mm` is (row, col, slice-spacing) from the header
    zooms; `slice_thickness` is the excited slab from the sidecar (the zoom is
    spacing, which includes any gap). `pe_dir` is the row/col word for the
    phase-encode axis this scan resolved, and is `None` when it resolved none.
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


def _acq_datetime(sidecar: Sidecar) -> str | None:
    """Read the acquisition date/time from the sidecar, or None if absent.

    The time is truncated to whole seconds. Siemens often anonymizes the date
    away, leaving only `AcquisitionTime`.
    """
    if dt := sidecar.get("AcquisitionDateTime"):
        return str(dt).split(".")[0].replace("T", " ")
    date, time = sidecar.get("AcquisitionDate"), sidecar.get("AcquisitionTime")
    date = str(date) if date else None
    time = str(time).split(".")[0] if time else None
    return " ".join(x for x in (date, time) if x) or None


def _malformed(key: str, value: object, expected: str) -> None:
    """Warn that a sidecar field is unusable and is being recorded as unknown.

    The sidecar is optional and these fields only describe the acquisition, so
    a malformed one is treated like an absent one, with a warning naming it
    because the metadata exists and is being dropped. Coercing it instead (a
    string that happens to parse as a number) would guess at what the converter
    meant.
    """
    warn(
        f"sidecar {key} {value!r} is not {expected}; recording it as unknown",
    )


def _optional_number(sidecar: Sidecar, key: str) -> float | None:
    """Read a finite number from the sidecar, or None if absent or malformed."""
    value = sidecar.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        _malformed(key, value, "a number")
        return None
    if not math.isfinite(value):
        _malformed(key, value, "a finite number")
        return None
    return float(value)


def _optional_text(sidecar: Sidecar, key: str) -> str | None:
    """Read a text field from the sidecar, or None if absent or malformed.

    A number is kept as its text (a serial number written unquoted is still a
    serial number). Anything structured is not a value this field can hold.
    """
    value = sidecar.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    _malformed(key, value, "text")
    return None


def _pe_direction(pe_axis: int | None) -> str | None:
    """Name the row/col word for the resolved axis, or None if unresolved.

    Derived from `pe_axis` alone, not from the sidecar's
    `InPlanePhaseEncodingDirectionDICOM`. Reading that word gave a second answer
    to a question `pe_axis` had settled, and the two could disagree:
    `pe_axis_from_sidecar` prefers dcm2niix's BIDS fields, so a sidecar whose
    DICOM tag contradicted them gave an axis from one source and a direction
    from the other, and the report showed a direction that was not the axis the
    ghost masks used.

    Returns None when there is no in-plane axis, so a caller falls back to what
    the run used and not to a label for a different axis (see
    `analysis.build._pe_label`).
    """
    axis = in_plane(pe_axis)
    return None if axis is None else PE_ROWCOL[axis]


def scan_meta(
    sidecar: Sidecar,
    *,
    voxel_mm: tuple[float, float, float],
    matrix: tuple[int, int],
    pe_axis: int | None,
    tr: float,
) -> ScanMeta:
    """Assemble `ScanMeta` from the NIfTI geometry and (optional) BIDS sidecar.

    `voxel_mm` (header zooms, already in millimeters) and `matrix` come from the
    NIfTI header, which `fmriqa_io` decodes. `tr` is passed in already resolved,
    so the report shows the TR the pipeline ran on. The sidecar's optional
    fields are type-checked here at the boundary, so a malformed value is
    diagnosed against its file and doesn't surface as an unreadable artifact
    months later. A field that fails is recorded as unknown, with a warning.

    Raises
    ------
    InvalidScanError
        If a voxel size is not positive and finite.
    """
    if not all(math.isfinite(z) and z > 0 for z in voxel_mm):
        raise InvalidScanError("voxel size", voxel_mm, "expected positive finite sizes")
    return ScanMeta(
        voxel_mm=voxel_mm,
        matrix=matrix,
        tr=tr,
        te=_optional_number(sidecar, "EchoTime"),
        flip_angle=_optional_number(sidecar, "FlipAngle"),
        slice_thickness=_optional_number(sidecar, "SliceThickness"),
        pe_dir=_pe_direction(pe_axis),
        coil=_optional_text(sidecar, "ReceiveCoilName"),
        manufacturer=_optional_text(sidecar, "Manufacturer"),
        model=_optional_text(sidecar, "ManufacturersModelName"),
        serial=_optional_text(sidecar, "DeviceSerialNumber"),
        field_strength=_optional_number(sidecar, "MagneticFieldStrength"),
        software=_optional_text(sidecar, "SoftwareVersions"),
        datetime=_acq_datetime(sidecar),
        series=_optional_text(sidecar, "SeriesDescription"),
    )
