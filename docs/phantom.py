"""The synthetic phantom every figure on these pages is drawn from.

Each `plot` block in `user-guide/analyses/` runs against this module while
Sphinx builds. Figures are live output of the installed package. Change a
metric and the curve on its page changes, or the build fails (`make docs`
passes `-W`).

The series is the one the test suite uses, `fmriqa.testing.synthetic_series`:
a uniform disk rendered from exact k-space, so its edges are band-limited and
its background is Rayleigh noise. Seeded, 3 mm isotropic voxels, TR 2 s, stored
as `uint16`. The docs draw a variant of it. On top of the tests' series they add
the small N/2 ghost and signal drift that `GHOST` and `DRIFT` document, and the
blur that `SMOOTHING_VOXELS` documents. The tests' unblurred series rings at the
edges (Gibbs); the docs' blur smooths the ringing away. The docs build it larger
than the tests do.

`scan()` writes that series to a temporary directory with
`fmriqa_io.testing.write_phantom` and loads it back, so the figures take the same
path a real run takes. The phase-encode axis comes from the sidecar, the voxel
size from the header (so lengths are in mm), and the integer storage lets the
saturation check run.
`analysis()` analyzes the scan once and caches it, so one analysis serves every
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

#: In-plane Gaussian blur (voxels), standing in for the smoothing a scanner's
#: reconstruction filter and interpolation apply to signal and noise alike. The
#: blur is for `analyses/smoothness.md`: unblurred, the noise is white, its FWHM
#: estimate sits at the edge of what the estimator resolves (about 0.6 voxel) and
#: the point-spread figure is a single spike. The registration
#: (`analyses/motion.md`) does not need it. A zero is the tests' series.
SMOOTHING_VOXELS = 0.8

#: N/2 ghost along the phase-encode axis, as a noise-free ghost-to-signal ratio.
#: A stable EPI scanner shows a ghost of a percent or two, so the ghosting page
#: has a real ghost to measure instead of the background.
GHOST = 0.02

#: Signal drift over the run, first frame to last, as a fraction of the mean.
#: One percent over the four minutes is a stable scanner's slow drift. The run
#: is long enough (`N_FRAMES` at TR 2 s is 240 s) for the detrend to fit a
#: line, so `drift_pct` reads about 1.
DRIFT = 0.01


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
        ghost=GHOST,
        drift=DRIFT,
    )


def scan() -> q.QAScan:
    """Return the phantom as the loader hands it to the pipeline."""
    return load_scan(_written())


@cache
def analysis() -> q.QAAnalysis:
    """Return the analyzed phantom, computed once per documentation build.

    Cached so every figure reads the same analysis. The curves on a page and
    the numbers in its table then come from one run.
    """
    settings = q.AnalysisSettings(roi_size=ROI_SIZE)
    return q.analyze(scan(), settings, name="phantom.nii.gz", source="phantom.nii.gz")
