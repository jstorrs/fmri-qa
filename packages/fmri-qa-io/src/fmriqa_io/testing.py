"""Write the synthetic phantom to disk as a NIfTI + BIDS sidecar.

The file counterpart of `fmriqa.testing.phantom_scan`, for tests, docs and
spikes that need real file IO. Import it as `fmriqa_io.testing`. It is not part
of the `fmriqa_io` public surface.
"""

import json
from pathlib import Path

import nibabel as nib
import numpy as np

from fmriqa.testing import TR_SEC, VOXEL_MM, synthetic_series

__all__ = ["write_phantom"]


def write_phantom(
    directory: Path,
    name: str = "scan",
    *,
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    flip: float = 77.0,
    smoothing: float = 0.0,
) -> Path:
    """Write a synthetic phantom NIfTI + sidecar; return the NIfTI path.

    A bright central disk with seeded temporal noise, 3 mm isotropic voxels and
    TR 2 s. The sidecar sets `PhaseEncodingDirection`, so no ghost-estimate
    fallback warning fires.

    The background has a Rician-like noise floor, as a real magnitude image
    does. A constant background would make the quantiles that seed
    `segment_phantom` degenerate.

    Stored as `uint16`, like a properly converted acquisition. The saturation
    check needs integer data (see `metrics.saturation`), and floats would add a
    storage warning to every file-based test. `PHANTOM_SIGNAL` is 1000, so
    nibabel stores the values directly. Rescaling them onto the type's maximum
    would create a false `2**16 - 1` rail.

    `smoothing` blurs the series in-plane (see `synthetic_series`). The docs use
    it. `fmriqa.testing.phantom_scan` describes only the unblurred phantom.
    """
    data = synthetic_series(n=n, z=z, t=t, seed=seed, smoothing=smoothing)

    img = nib.Nifti1Image(data.astype(np.uint16), affine=np.eye(4))
    img.header.set_zooms((VOXEL_MM, VOXEL_MM, VOXEL_MM, TR_SEC))
    img.header.set_xyzt_units("mm", "sec")
    nifti = directory / f"{name}.nii.gz"
    nib.save(img, str(nifti))
    (directory / f"{name}.json").write_text(
        json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
    )
    return nifti
