"""The synthetic phantom every figure on these pages is drawn from.

Each `plot` block in `user-guide/analyses/` runs against this module while
Sphinx builds. Figures are live output of the installed package. Change a
metric and the curve on its page changes, or the build fails (`make docs`
passes `-W`).

The series matches the one the test suite uses: a bright disk over a
Rician-like background floor, seeded, 3 mm isotropic voxels, TR 2 s, stored as
`uint16`. It is rebuilt here because core's `tests/` is a pytest directory, not
an importable package, and because the docs should not break when a fixture is
rearranged. `synthetic_series` below is the same construction as
`packages/fmri-qa-core/tests/conftest.py::synthetic_series`, plus the blur
that `SMOOTHING_VOXELS` documents. Keep the two alike.

`scan()` writes that series to a NIfTI + BIDS sidecar in a temporary directory
and loads it back, so the figures take the same path a real run takes. The
phase-encode axis comes from the sidecar, the voxel size from the header (so
lengths are in mm), and the integer storage lets the saturation check run.
`artifact()` analyzes the scan once and caches it, so one analysis serves every
figure in the build.
"""

import atexit
import json
import shutil
import tempfile
from functools import cache
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import gaussian_filter

import fmriqa as q

# Background noise floor, as a fraction of phantom signal. A real magnitude
# image has a Rician air background, so the figures include a realistic floor.
BACKGROUND_SCALE = 8.0
PHANTOM_SIGNAL = 1000.0

# The size the figures are drawn at. Larger than the unit tests' default, so a
# curve has enough samples to read as a curve. The construction, seed and
# acquisition parameters are the fixture's.
FRAME_SIZE = 64
N_SLICES = 3
N_FRAMES = 120
ROI_SIZE = 21

# In-plane Gaussian blur (voxels) per frame, standing in for an acquisition's
# point spread. The unit fixture has none. Without it the hard-edged disk gives
# the registration (`analyses/motion.md`) no gradients to lock onto, every fit
# comes back unidentifiable, and the motion figure shows only NaN. The blur also
# gives the noise a correlation length for `analyses/smoothness.md` to measure.
# `synthetic_series(smoothing=0.0)` is the tests' series exactly.
SMOOTHING_VOXELS = 0.8


def synthetic_series(
    n: int = FRAME_SIZE,
    z: int = N_SLICES,
    t: int = N_FRAMES,
    seed: int = 0,
    smoothing: float = SMOOTHING_VOXELS,
) -> np.ndarray:
    """Build a bright central disk over a noisy background, (n, n, z, t) float64.

    The disk carries seeded temporal noise, which the stability metrics
    measure. The background carries a static magnitude floor. Each frame is
    then blurred in-plane by `smoothing` voxels, the point spread a real
    acquisition has (see `SMOOTHING_VOXELS`).
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


@cache
def _written() -> Path:
    """Write the phantom to a NIfTI + sidecar once, and return its path.

    The directory is temporary and removed when the build process exits. The
    file exists because `QAScan.from_nifti` is the path a real run takes, and
    the pages describe reading voxel size and phase-encode direction from a
    header.
    """
    directory = Path(tempfile.mkdtemp(prefix="fmriqa-docs-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)

    data = synthetic_series()
    image = nib.Nifti1Image(data.astype(np.uint16), affine=np.eye(4))
    image.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    image.header.set_xyzt_units("mm", "sec")
    nifti = directory / "phantom.nii.gz"
    nib.save(image, str(nifti))
    (directory / "phantom.json").write_text(
        json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": 77})
    )
    return nifti


def scan() -> q.QAScan:
    """Return the phantom as the loader hands it to the pipeline."""
    return q.QAScan.from_nifti(_written())


@cache
def artifact() -> q.QAArtifact:
    """Return the analyzed phantom, computed once per documentation build.

    Cached so every figure reads the same analysis. The curves on a page and
    the numbers in its table then come from one run.
    """
    settings = q.AnalysisSettings(roi_size=ROI_SIZE)
    return q.analyze(scan(), settings, name="phantom.nii.gz", source="phantom.nii.gz")
