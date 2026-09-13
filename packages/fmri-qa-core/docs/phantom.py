"""The synthetic phantom every figure on these pages is drawn from.

Each `plot` block in `analyses/` runs against this module while Sphinx builds,
so a figure is output of the installed package rather than a picture of what it
once produced: change a metric and the curve on its page changes with it, or the
build fails (`make docs` passes `-W`).

The series is the one the test suite measures against -- a bright disk over a
Rician-like background floor, seeded, 3 mm isotropic voxels, TR 2 s, stored as
`uint16`. It is rebuilt here rather than imported because `tests/` is a pytest
directory and not an importable package, and because the documentation should
not break when a fixture is rearranged; `synthetic_series` below is the same
construction as `tests/conftest.py::synthetic_series`, plus the one-parameter
blur `SMOOTHING_VOXELS` documents, and the two are expected to read alike.

`scan()` writes that series to a NIfTI + BIDS sidecar in a temporary directory
and loads it back, so the figures come off the same path a real run takes:
the phase-encode axis resolves from the sidecar, the voxel size from the header
(so lengths are in mm), and the integer storage lets the saturation check
actually run. `artifact()` analyzes it, cached, so one analysis serves every
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

import fmriqc as q

# Background noise floor, as a fraction of phantom signal. A real magnitude
# image has a Rician air background; an exactly-constant one makes the intensity
# quantiles that seed the segmentation degenerate, so the background gets a
# floor and the figures exercise the segmentation rather than a failure path.
BACKGROUND_SCALE = 8.0
PHANTOM_SIGNAL = 1000.0

# The size the figures are drawn at. Larger than the unit tests' default so a
# curve has enough samples to read as a curve -- the construction, the seed, and
# the acquisition parameters are the fixture's.
FRAME_SIZE = 64
N_SLICES = 3
N_FRAMES = 120
ROI_SIZE = 21

# In-plane Gaussian blur (voxels) applied to each frame, standing in for the
# point spread of an acquisition. The unit fixture has none, and a hard-edged
# disk is the one thing on these pages a real phantom is not: the registration
# (`analyses/motion.md`) locks onto image gradients, and a step edge with white
# noise everywhere else gives it none, so every frame's fit comes back
# unidentifiable and the motion figure would show nothing but NaN. It is also
# what gives the noise field a correlation length for `analyses/smoothness.md`
# to measure. `synthetic_series(smoothing=0.0)` is the tests' series exactly.
SMOOTHING_VOXELS = 0.8


def synthetic_series(
    n: int = FRAME_SIZE,
    z: int = N_SLICES,
    t: int = N_FRAMES,
    seed: int = 0,
    smoothing: float = SMOOTHING_VOXELS,
) -> np.ndarray:
    """A bright central disk over a noisy background: (n, n, z, t), float64.

    The disk carries seeded temporal noise (the fluctuation the stability
    metrics measure); the background carries a static magnitude floor. Each
    frame is then blurred in-plane by `smoothing` voxels, the point spread an
    acquisition has and a synthetic disk does not (see `SMOOTHING_VOXELS`).
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

    The directory is temporary and removed when the build process exits; the
    file exists at all because `QAScan.from_nifti` is the path a real run takes,
    and reading the voxel size and the phase-encode direction off a header is
    part of what the pages describe.
    """
    directory = Path(tempfile.mkdtemp(prefix="fmriqc-docs-"))
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
    """The phantom as the loader hands it to the pipeline."""
    return q.QAScan.from_nifti(_written())


@cache
def artifact() -> q.QAArtifact:
    """The analyzed phantom, computed once per documentation build.

    Cached because every figure reads from the same analysis: the curves a page
    plots and the numbers its table names are then one run's, not several.
    """
    settings = q.AnalysisSettings(roi_size=ROI_SIZE)
    return q.analyze(scan(), settings, name="phantom.nii.gz", source="phantom.nii.gz")
