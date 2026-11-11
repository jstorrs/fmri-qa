"""The synthetic phantom, shared by every package, the docs and the spikes.

This is the deterministic test and doc phantom, shipped so they all measure
against one definition. It is a bright central disk over a Rician-like noise
floor, seeded. `synthetic_series` is the raw array. `phantom_scan` is the
`QAScan` that loading the file `fmriqa_io.testing.write_phantom` writes gives
back, built without touching a file. A parity test in `fmri-qa-io` pins the two
together.

The phantom lives in `series.py` and the analytic k-space kernel in `kspace.py`.

Pure: no file IO. Import it as `fmriqa.testing`. It is not part of the
`fmriqa` public surface.
"""

from .series import (
    BACKGROUND_SCALE,
    PE_AXIS,
    PHANTOM_SIGNAL,
    TR_SEC,
    VOXEL_MM,
    phantom_scan,
    synthetic_series,
)

__all__ = [
    "BACKGROUND_SCALE",
    "PE_AXIS",
    "PHANTOM_SIGNAL",
    "TR_SEC",
    "VOXEL_MM",
    "phantom_scan",
    "synthetic_series",
]
