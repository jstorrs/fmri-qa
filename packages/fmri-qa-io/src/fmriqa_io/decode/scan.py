"""Decode a NIfTI series and its optional sidecar, as bytes, into a `QAScan`.

This is all of loading a scan except the file reads, so a browser can hand over
the bytes of a dropped file. It reads the phase-encode axis from the sidecar
first and the NIfTI `dim_info` second. If neither has one, it warns and leaves
the axis None, because estimating it from the Nyquist ghost is the pipeline's
job (see `fmriqa.pipeline.run_qa`). The TR likewise prefers the sidecar over
the unit-converted header pixdim.
"""

from fmriqa.exceptions import InvalidScanError
from fmriqa.load.metadata import scan_meta
from fmriqa.load.pe_axis import pe_axis_from_sidecar
from fmriqa.load.repetition_time import resolve_repetition_time
from fmriqa.load.scan import QAScan
from fmriqa.types import Sidecar
from fmriqa.warn import warn

from .nifti import (
    image_data,
    image_from_bytes,
    pe_axis_from_header,
    spatial_scale_mm,
    tr_from_header,
)
from .sidecar import parse_sidecar

__all__ = [
    "scan_from_bytes",
]


def scan_from_bytes(
    nifti: bytes,
    sidecar: bytes | None = None,
    *,
    name: str = "scan",
    sidecar_name: str = "sidecar",
) -> QAScan:
    """Decode a 4-D NIfTI series, with its BIDS sidecar when one is given.

    `nifti` is a single-file NIfTI-1 or NIfTI-2 image, gzipped or not. The
    whole file is held in memory while decoding, compressed and decompressed,
    unlike a memory-mapped `nibabel.load`, so peak memory is a few times the
    file size.
    `sidecar` is the JSON sidecar's bytes, or None when there is none. `name`
    and `sidecar_name` identify the two in warnings and errors, since there may
    be no files to name.

    Raises
    ------
    InvalidScanError
        If the image is damaged or not a 4-D NIfTI series, or the sidecar is
        not a JSON object or holds an invalid phase-encode field or voxel size.
    """
    img = image_from_bytes(nifti, name=name)
    if len(img.shape) != 4:
        raise InvalidScanError(
            "data shape", img.shape, "expected a 4-D (X, Y, Z, T) NIfTI series"
        )
    # Decoded after the image, so a bad NIfTI fails on the NIfTI, not its sidecar.
    fields = _sidecar_fields(sidecar, name=name, sidecar_name=sidecar_name)
    data = image_data(img, name=name)
    # Loading consumes header scaling. The proxy keeps the transform that
    # get_fdata applied (identity for unscaled files).
    slope, inter = img.dataobj.slope, img.dataobj.inter
    # The stored datatype, before `get_fdata` widened everything to float64.
    stored_integer = img.header.get_data_dtype().kind in "iu"
    if not stored_integer:
        warn(
            f"{name}: stored as {img.header.get_data_dtype()}, not an integer "
            "type, so the scanner's ADC samples are gone and clipping cannot "
            "be detected -- the saturation check will report 'not "
            "determinable' rather than clean. Convert with a tool that "
            "preserves the stored integer datatype (dcm2niix does by "
            "default) if you need the receiver-gain check.",
        )

    pe_axis = pe_axis_from_sidecar(fields)
    if pe_axis is None:
        pe_axis = pe_axis_from_header(img.header)
    if pe_axis is None:
        warn(
            f"{name}: no phase-encode axis in sidecar or NIfTI dim_info; "
            "the pipeline will estimate it from the Nyquist ghost. Pass "
            "--pe-axis to name the acquisition's direction instead.",
        )

    tr = resolve_repetition_time(tr_from_header(img.header), fields, source=name)
    unit, _ = img.header.get_xyzt_units()
    scale = spatial_scale_mm(unit)
    affine = img.affine.copy()
    affine[:3, :] *= scale
    zooms = img.header.get_zooms()
    return QAScan(
        data=data,
        tr=tr,
        affine=affine,
        pe_axis=pe_axis,
        meta=scan_meta(
            fields,
            voxel_mm=(
                float(zooms[0]) * scale,
                float(zooms[1]) * scale,
                float(zooms[2]) * scale,
            ),
            matrix=(int(img.shape[0]), int(img.shape[1])),
            pe_axis=pe_axis,
            tr=tr,
        ),
        slope=float(slope),
        inter=float(inter),
        stored_integer=stored_integer,
    )


def _sidecar_fields(sidecar: bytes | None, *, name: str, sidecar_name: str) -> Sidecar:
    """Parse the sidecar, or warn and return no fields when there is none.

    A scanner export never went through dcm2niix, so a missing sidecar yields
    an empty mapping, which everything downstream tolerates.
    """
    if sidecar is None:
        warn(
            f"{name}: no BIDS JSON sidecar found beside the NIfTI; the "
            f"acquisition metadata, including the sidecar phase-encode "
            f"direction and TR, will be absent",
        )
        return {}
    return parse_sidecar(sidecar, source=sidecar_name)
