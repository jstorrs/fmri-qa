"""Parse the BIDS JSON sidecar into `ScanMeta`.

dcm2niix writes a `.json` sidecar beside every NIfTI it converts; these helpers
read the acquisition metadata out of it. The sidecar is optional — a NIfTI
exported straight off the scanner never had one — so its absence leaves fields
empty rather than failing. Phase-encode *axis* resolution lives in `pe_axis`
and TR resolution in `repetition_time`; the DICOM row/col *direction* string
for the report header is derived here (`_pe_direction`) from the same sidecar.
"""

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..exceptions import InvalidScanError
from .paths import sidecar_path
from .pe_axis import PE_ROWCOL


@dataclass(frozen=True)
class ScanMeta:
    """Human-readable acquisition metadata for the report header.

    Geometry (`voxel_mm`, `matrix`, `tr`) is always present: it comes from the
    NIfTI header, with `tr` the resolved repetition time in seconds — the same
    value the pipeline runs on (see `repetition_time`). The rest comes from the
    BIDS JSON sidecar written alongside the NIfTI (dcm2niix) and is `None` when
    no sidecar is found. `voxel_mm` is (row, col, slice-spacing) from the header
    zooms; `slice_thickness` is the excited slab from the sidecar (the zoom is
    spacing, which includes any gap). `pe_dir` is the DICOM row/col direction.
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
    """Parse the BIDS JSON sidecar beside `path` (.nii/.nii.gz -> .json).

    dcm2niix writes one alongside every NIfTI it converts, but a scanner export
    never went through that conversion, so a missing sidecar warns and yields an
    empty mapping: the acquisition metadata is simply absent, which everything
    downstream already tolerates. A sidecar that *is* there and cannot be read
    is a different matter — the metadata exists and we would be misreading it —
    so it fails loudly.

    Raises:
        InvalidScanError: If the sidecar is not parseable as a JSON object.
    """
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        warnings.warn(
            f"{path}: no BIDS JSON sidecar found beside the NIfTI; the "
            f"acquisition metadata, including the sidecar phase-encode "
            f"direction and TR, will be absent",
            stacklevel=3,  # report at the caller of `QAScan.from_nifti`
        )
        return {}
    try:
        parsed: object = json.loads(sidecar.read_text())
    except json.JSONDecodeError as e:
        raise InvalidScanError(
            "BIDS JSON sidecar", str(sidecar), f"could not be parsed: {e}"
        ) from e
    if not isinstance(parsed, dict):
        raise InvalidScanError(
            "BIDS JSON sidecar",
            str(sidecar),
            "expected a JSON object of acquisition metadata",
        )
    # A JSON object's keys are always strings; rebuilding is how the type
    # checkers are told so, `json.loads` being typed as returning anything.
    return {str(key): value for key, value in parsed.items()}


def _acq_datetime(sidecar: dict[str, Any]) -> str | None:
    """Acquisition date/time from the sidecar, seconds-precision; None if absent.

    Siemens often anonymizes the date away, leaving only `AcquisitionTime`.
    """
    if dt := sidecar.get("AcquisitionDateTime"):
        return str(dt).split(".")[0].replace("T", " ")
    date, time = sidecar.get("AcquisitionDate"), sidecar.get("AcquisitionTime")
    time = str(time).split(".")[0] if time else None
    return " ".join(x for x in (date, time) if x) or None


def _malformed(key: str, value: object, expected: str) -> None:
    """Warn that a sidecar field is unusable and is being recorded as unknown.

    The sidecar is optional and these fields only describe the acquisition, so
    a malformed one is treated like an absent one — with a warning naming it,
    because the metadata exists and is being dropped. Coercing it instead (a
    string that happens to parse as a number) would be guessing at what the
    converter meant. Reported at the caller of `QAScan.from_nifti`.
    """
    warnings.warn(
        f"sidecar {key} {value!r} is not {expected}; recording it as unknown",
        stacklevel=4,
    )


def _optional_number(sidecar: dict[str, Any], key: str) -> float | None:
    """A finite number from the sidecar, or None if absent or malformed."""
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


def _optional_text(sidecar: dict[str, Any], key: str) -> str | None:
    """A text field from the sidecar, or None if absent or malformed.

    A number is kept as its text (a serial number written unquoted is still a
    serial number); anything structured is not a value this field can hold.
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


def _pe_direction(pe_axis: int | None, sidecar: dict[str, Any]) -> str | None:
    """DICOM row/col phase-encode direction, preferring the sidecar's own wording.

    `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) is checked first because it
    already speaks in row/col terms. Otherwise `pe_axis` is used directly rather
    than re-deriving a row/col label from `PhaseEncodingDirection` here: by the
    time this runs, `QAScan.from_nifti` has already resolved `pe_axis` from that
    same sidecar field via `_pe_axis_from_sidecar` (`pe_axis.py`'s single source
    of truth for the BIDS i/j -> array-axis mapping), so re-consuming it would
    only recompute the answer `pe_axis` already carries.
    """
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return str(dicom).lower()
    return PE_ROWCOL.get(pe_axis) if pe_axis is not None else None


def _scan_meta(
    img: Any, sidecar: dict[str, Any], pe_axis: int | None, tr: float
) -> ScanMeta:
    """Assemble `ScanMeta` from the NIfTI header and (optional) BIDS sidecar.

    `tr` is handed in already resolved rather than re-read from pixdim[4], so
    the TR the report shows is the one the pipeline ran on. The sidecar's
    optional fields are held to the type each one promises here, at the
    boundary, so that a malformed value is diagnosed against the file it came
    from rather than surfacing as an unreadable artifact months later; one
    that fails is recorded as unknown, with a warning.
    """
    zooms = img.header.get_zooms()
    unit, _ = img.header.get_xyzt_units()
    if unit == "unknown":
        warnings.warn(
            "NIfTI spatial unit is unknown; assuming millimeters for voxel sizes",
            stacklevel=3,
        )
    factor = {"meter": 1000.0, "mm": 1.0, "micron": 0.001, "unknown": 1.0}[unit]
    voxel_mm = tuple(float(z) * factor for z in zooms[:3])
    if not all(math.isfinite(z) and z > 0 for z in voxel_mm):
        raise InvalidScanError("voxel size", voxel_mm, "expected positive finite sizes")
    return ScanMeta(
        voxel_mm=(voxel_mm[0], voxel_mm[1], voxel_mm[2]),
        matrix=(int(img.shape[0]), int(img.shape[1])),
        tr=tr,
        te=_optional_number(sidecar, "EchoTime"),
        flip_angle=_optional_number(sidecar, "FlipAngle"),
        slice_thickness=_optional_number(sidecar, "SliceThickness"),
        pe_dir=_pe_direction(pe_axis, sidecar),
        coil=_optional_text(sidecar, "ReceiveCoilName"),
        manufacturer=_optional_text(sidecar, "Manufacturer"),
        model=_optional_text(sidecar, "ManufacturersModelName"),
        serial=_optional_text(sidecar, "DeviceSerialNumber"),
        field_strength=_optional_number(sidecar, "MagneticFieldStrength"),
        software=_optional_text(sidecar, "SoftwareVersions"),
        datetime=_acq_datetime(sidecar),
        series=_optional_text(sidecar, "SeriesDescription"),
    )
