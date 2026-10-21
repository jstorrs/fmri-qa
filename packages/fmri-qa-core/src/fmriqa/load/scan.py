"""The `QAScan` value object and its NIfTI loader (the I/O boundary).

`QAScan` is the imperative shell's entry point. `from_nifti` does the file I/O
and header/sidecar parsing, then hands the pure pipeline a plain array plus the
metadata it needs. It reads the phase-encode axis from the sidecar first and the
NIfTI `dim_info` second. If neither has one, it warns and leaves the axis None,
because estimating it from the Nyquist ghost is the pipeline's job (see
`pipeline.run_qa`) and would make this layer depend on the metrics above it. The
TR likewise prefers the sidecar over the unit-converted header pixdim.
"""

from dataclasses import dataclass
from pathlib import Path

import nibabel as nib

from ..exceptions import InvalidScanError
from ..types import FloatArray
from ..warn import warn
from .metadata import ScanMeta, _load_sidecar, _scan_meta
from .pe_axis import _pe_axis_from_header, _pe_axis_from_sidecar
from .repetition_time import _repetition_time

__all__ = [
    "QAScan",
]


def _spatial_scale_mm(unit: str) -> float:
    """Resolve the header's spatial unit once for voxel sizes and the affine."""
    if unit == "unknown":
        warn(
            "NIfTI spatial unit is unknown; assuming millimeters for voxel sizes "
            "and affine",
        )
    return {"meter": 1000.0, "mm": 1.0, "micron": 0.001, "unknown": 1.0}[unit]


@dataclass(frozen=True, eq=False, slots=True)
class QAScan:
    """A raw QA acquisition plus the header metadata the pipeline needs.

    `pe_axis` is the phase-encode axis as a NIfTI voxel-array index (0/1/2). The
    single-slice pipeline supports the in-plane axes 0/1 and rejects axis 2. It
    comes from the sidecar (see `pe_axis` for the three fields it reads), falling
    back to the header `dim_info` phase field, and is `None` when neither names
    an axis; `run_qa` then estimates one from the Nyquist ghost. Polarity is
    dropped. `tr` is in seconds, from the sidecar `RepetitionTime` or the header
    pixdim converted by its declared time unit. `meta` is the human-readable
    acquisition metadata for the report. Its fields are `None` when no BIDS
    sidecar sits beside the NIfTI.

    `affine`, when present, maps voxel indices to world coordinates in
    millimeters, including its translation. Direct callers must supply it in
    millimeters. `from_nifti` converts it and the header voxel sizes together,
    assuming millimeters with a warning when the spatial unit is unknown.

    `stored_integer` says whether the file held the scanner's integer samples,
    which the ADC-saturation check needs to find a `2**n - 1` hardware rail. A
    converter that wrote rescaled floats destroyed that evidence. `from_nifti`
    reads it from the NIfTI datatype. It defaults to True for a `QAScan` built
    from an array, since that caller hands over the samples themselves.
    """

    data: FloatArray  # (X, Y, Z, T)
    tr: float
    affine: FloatArray | None = None
    pe_axis: int | None = None
    meta: ScanMeta | None = None
    # NIfTI scl_slope/scl_inter, so saturation can recover stored integers from
    # `data` (in scaled image units). Default identity: `data` is already stored.
    slope: float = 1.0
    inter: float = 0.0
    stored_integer: bool = True  # the file kept the scanner's integer samples

    @classmethod
    def from_nifti(cls, path: str | Path) -> "QAScan":
        """Load a 4-D NIfTI series, with its BIDS sidecar when one exists."""
        img = nib.load(str(path))
        if len(img.shape) != 4:
            raise InvalidScanError(
                "data shape", img.shape, "expected a 4-D (X, Y, Z, T) NIfTI series"
            )
        # Optional: a scanner export never went through dcm2niix. Read after the
        # image so a missing NIfTI fails on the NIfTI, not its sidecar.
        sidecar = _load_sidecar(path)
        data = img.get_fdata()
        # Loading consumes header scaling. The proxy keeps the transform that
        # get_fdata applied (identity for unscaled files).
        slope, inter = img.dataobj.slope, img.dataobj.inter
        # The on-disk datatype, before `get_fdata` widened everything to float64.
        stored_integer = img.header.get_data_dtype().kind in "iu"
        if not stored_integer:
            warn(
                f"{path}: stored as {img.header.get_data_dtype()}, not an integer "
                "type, so the scanner's ADC samples are gone and clipping cannot "
                "be detected -- the saturation check will report 'not "
                "determinable' rather than clean. Convert with a tool that "
                "preserves the stored integer datatype (dcm2niix does by "
                "default) if you need the receiver-gain check.",
            )

        pe_axis = _pe_axis_from_sidecar(sidecar)
        if pe_axis is None:
            pe_axis = _pe_axis_from_header(img.header)
        if pe_axis is None:
            warn(
                f"{path}: no phase-encode axis in sidecar or NIfTI dim_info; "
                "the pipeline will estimate it from the Nyquist ghost. Pass "
                "--pe-axis to name the acquisition's direction instead.",
            )

        tr = _repetition_time(img.header, sidecar, path)
        unit, _ = img.header.get_xyzt_units()
        spatial_scale_mm = _spatial_scale_mm(unit)
        affine = img.affine.copy()
        affine[:3, :] *= spatial_scale_mm
        return cls(
            data=data,
            tr=tr,
            affine=affine,
            pe_axis=pe_axis,
            meta=_scan_meta(
                img, sidecar, pe_axis, tr, spatial_scale_mm=spatial_scale_mm
            ),
            slope=float(slope),
            inter=float(inter),
            stored_integer=stored_integer,
        )
