"""The `QAScan` value object and its NIfTI loader (the I/O boundary).

`QAScan` is the imperative shell's entry point: `from_nifti` does the file I/O
and header/sidecar parsing, then hands the pure pipeline a plain array plus the
metadata it needs. The phase-encode axis is resolved from the sidecar first,
then the NIfTI `dim_info`, then — only if both are absent — the ghost estimate.
"""

import warnings
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib

from ..exceptions import InvalidScanError
from ..metrics.ghost import phase_encode_axis
from ..types import FloatArray
from .metadata import ScanMeta, _load_sidecar, _scan_meta
from .pe_axis import _pe_axis_from_header, _pe_axis_from_sidecar


@dataclass(frozen=True, eq=False)
class QAScan:
    """A raw QA acquisition plus the header metadata the pipeline needs.

    `pe_axis` is the phase-encode axis as a NIfTI voxel-array index (0/1/2). The
    single-slice QA pipeline supports the in-plane axes 0/1 and rejects axis 2.
    The value comes from the sidecar `PhaseEncodingDirection` (authoritative),
    falling back
    to the header `dim_info` phase field, then — only if both are absent — to the
    Nyquist-ghost estimate (with a warning; `None` if `estimate_pe=False`).
    Polarity is dropped (unneeded here). `meta` holds the human-readable
    acquisition metadata for the report; both are built from the BIDS JSON
    sidecar, which `from_nifti` requires.
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

    @classmethod
    def from_nifti(cls, path: str | Path, estimate_pe: bool = True) -> "QAScan":
        sidecar = _load_sidecar(path)  # required; raises before the data load
        img = nib.load(str(path))
        if len(img.shape) != 4:
            raise InvalidScanError(
                "data shape", img.shape, "expected a 4-D (X, Y, Z, T) NIfTI series"
            )
        zooms = img.header.get_zooms()
        data = img.get_fdata()
        slope, inter = img.header.get_slope_inter()  # (None, None) when unscaled

        pe_axis = _pe_axis_from_sidecar(sidecar)
        if pe_axis is None:
            pe_axis = _pe_axis_from_header(img.header)
        if pe_axis is None:
            msg = f"{path}: no phase-encode axis in sidecar or NIfTI dim_info"
            if estimate_pe:
                pe_axis = phase_encode_axis(data)
                msg += f"; falling back to ghost estimate (axis {pe_axis})"
            warnings.warn(msg, stacklevel=2)

        return cls(
            data=data,
            tr=float(zooms[3]),
            affine=img.affine,
            pe_axis=pe_axis,
            meta=_scan_meta(img, sidecar, pe_axis),
            slope=float(slope) if slope else 1.0,
            inter=float(inter) if inter else 0.0,
        )
