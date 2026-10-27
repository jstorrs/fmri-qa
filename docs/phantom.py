"""The synthetic phantom every figure on these pages is drawn from.

Each `plot` block in `user-guide/analyses/` runs against this module while
Sphinx builds. Figures are live output of the installed package. Change a
metric and the curve on its page changes, or the build fails (`make docs`
passes `-W`).

The series is the one the test suite uses, `fmriqa.testing.synthetic_series`:
a bright disk over a Rician-like background floor, seeded, 3 mm isotropic
voxels, TR 2 s, stored as `uint16`, plus the blur that `SMOOTHING_VOXELS`
documents. The docs build it larger than the tests do.

`scan()` writes that series to a temporary directory with
`fmriqa_io.testing.write_phantom` and loads it back, so the figures take the same
path a real run takes. The phase-encode axis comes from the sidecar, the voxel
size from the header (so lengths are in mm), and the integer storage lets the
saturation check run.
`artifact()` analyzes the scan once and caches it, so one analysis serves every
figure in the build.
"""

import atexit
import shutil
import tempfile
from functools import cache
from pathlib import Path

import fmriqa as q
from fmriqa_io import load_scan
from fmriqa_io.testing import write_phantom

# The size the figures are drawn at. Larger than the unit tests' default, so a
# curve has enough samples to read as a curve. The construction, seed and
# acquisition parameters are the shared phantom's.
FRAME_SIZE = 64
N_SLICES = 3
N_FRAMES = 120
ROI_SIZE = 21

# In-plane Gaussian blur (voxels) per frame, standing in for an acquisition's
# point spread. The unit fixture has none. Without it the hard-edged disk gives
# the registration (`analyses/motion.md`) no gradients to lock onto, every fit
# comes back unidentifiable, and the motion figure shows only NaN. The blur also
# gives the noise a correlation length for `analyses/smoothness.md` to measure.
# A smoothing of zero is the tests' series exactly.
SMOOTHING_VOXELS = 0.8


@cache
def _written() -> Path:
    """Write the phantom to a NIfTI + sidecar once, and return its path.

    The directory is temporary and removed when the build process exits. The
    file exists because `fmriqa_io.load_scan` is the path a real run takes, and
    the pages describe reading voxel size and phase-encode direction from a
    header.
    """
    directory = Path(tempfile.mkdtemp(prefix="fmriqa-docs-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)

    return write_phantom(
        directory,
        "phantom",
        n=FRAME_SIZE,
        z=N_SLICES,
        t=N_FRAMES,
        smoothing=SMOOTHING_VOXELS,
    )


def scan() -> q.QAScan:
    """Return the phantom as the loader hands it to the pipeline."""
    return load_scan(_written())


@cache
def artifact() -> q.QAArtifact:
    """Return the analyzed phantom, computed once per documentation build.

    Cached so every figure reads the same analysis. The curves on a page and
    the numbers in its table then come from one run.
    """
    settings = q.AnalysisSettings(roi_size=ROI_SIZE)
    return q.analyze(scan(), settings, name="phantom.nii.gz", source="phantom.nii.gz")
