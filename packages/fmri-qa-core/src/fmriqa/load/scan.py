"""The `QAScan` value object: a raw acquisition plus its header metadata.

`QAScan` is what the pure pipeline consumes: a plain array plus the metadata it
needs. Core reads no files. `fmriqa_io.scan_from_bytes` decodes a NIfTI and its
optional sidecar into one, and `fmriqa_io.load_scan` reads them from disk first.
The decoder reads the phase-encode axis from the sidecar first and the NIfTI
`dim_info` second. If neither has one, it warns and leaves the axis None,
because estimating it from the Nyquist ghost is the pipeline's job (see
`pipeline.run_qa`). The TR likewise prefers the sidecar over the unit-converted
header pixdim.
"""

from dataclasses import dataclass

from ..types import FloatArray
from .metadata import ScanMeta

__all__ = [
    "QAScan",
]


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
    millimeters. `fmriqa_io.scan_from_bytes` converts it and the header voxel
    sizes together, assuming millimeters with a warning when the spatial unit is
    unknown.

    `stored_integer` says whether the file held the scanner's integer samples,
    which the ADC-saturation check needs to find a `2**n - 1` hardware rail. A
    converter that wrote rescaled floats destroyed that evidence. The decoder
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
