"""The synthetic phantom, shared by every package, the docs and the spikes.

This is the deterministic test and doc phantom, shipped so they all measure
against one definition. It is a bright central disk over a Rician-like noise
floor, seeded. `synthetic_series` is the raw array. `phantom_scan` is the
`QAScan` that loading the file `fmriqa_io.testing.write_phantom` writes gives
back, built without touching a file. A parity test in `fmri-qa-io` pins the two
together.

Pure: no file IO. Import it as `fmriqa.testing`. It is not part of the
`fmriqa` public surface.
"""

import numpy as np
from scipy.ndimage import gaussian_filter

from .load.metadata import ScanMeta
from .load.scan import QAScan
from .types import FloatArray

# Background noise floor, as a fraction of phantom signal. Real magnitude images
# have a Rician air background. A constant one makes the intensity quantiles
# that seed `segment_phantom` degenerate.
BACKGROUND_SCALE = 8.0
PHANTOM_SIGNAL = 1000.0

# The phantom's acquisition, as `write_phantom` records it in the header and the
# sidecar and `phantom_scan` repeats in memory.
TR_SEC = 2.0
VOXEL_MM = 3.0
PE_AXIS = 1


def synthetic_series(
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    smoothing: float = 0.0,
) -> FloatArray:
    """Build a bright central disk over a noisy background: (n, n, z, t), float64.

    The disk carries seeded temporal noise. The background has a static floor
    (see `BACKGROUND_SCALE`) so the phantom is separable from it. `smoothing`
    blurs each frame in-plane by that many voxels, the point spread a real
    acquisition has. Zero leaves the hard-edged disk.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, PHANTOM_SIGNAL, 0.0)
    floor = np.abs(rng.normal(scale=BACKGROUND_SCALE, size=(n, n, z, t)))
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    series = base[:, :, None, None] + noise + floor
    if smoothing > 0.0:
        series = gaussian_filter(series, (smoothing, smoothing, 0, 0), mode="nearest")
    return np.asarray(series, dtype=np.float64)


def phantom_scan(
    *, n: int = 32, z: int = 3, t: int = 40, seed: int = 0, flip: float = 77.0
) -> QAScan:
    """Build the scan `fmriqa_io.load_scan(write_phantom(...))` gives back.

    The samples go through `uint16` and back, as they do on disk, so they are
    truncated to whole numbers. `meta` holds what the header and sidecar give:
    geometry, TR, flip angle and the phase-encode direction.
    """
    data = synthetic_series(n=n, z=z, t=t, seed=seed).astype(np.uint16)
    meta = ScanMeta(
        voxel_mm=(VOXEL_MM, VOXEL_MM, VOXEL_MM),
        matrix=(n, n),
        tr=TR_SEC,
        flip_angle=flip,
        pe_dir="col",
    )
    return QAScan(
        data=data.astype(np.float64),
        tr=TR_SEC,
        affine=np.eye(4),
        pe_axis=PE_AXIS,
        meta=meta,
        slope=1.0,
        inter=0.0,
        stored_integer=True,
    )
