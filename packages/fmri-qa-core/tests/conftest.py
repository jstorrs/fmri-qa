"""Shared fixtures for the calculation-half tests.

`synthetic_series` builds the tiny phantom every test measures against, and
`write_scan` writes one to disk as a NIfTI + BIDS sidecar, so the tests that need
the real file-I/O path (`QAScan.from_nifti`, the CLI) get one without each of
them rebuilding the phantom. `artifact` runs the whole pipeline over that
phantom once per test, for the artifact and CLI tests that need a finished
analysis rather than a scan.
"""

import json
from collections.abc import Callable
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

import fmriqc as q

WriteScan = Callable[..., str]
MakeScan = Callable[..., "q.QAScan"]

# Background noise floor, as a fraction of phantom signal. Real magnitude images
# have a Rician air background; an exactly-constant one is what makes the
# intensity quantiles seeding `segment_phantom` degenerate, so the fixtures give
# the background a floor and exercise the segmentation rather than a failure path.
BACKGROUND_SCALE = 8.0
PHANTOM_SIGNAL = 1000.0


def synthetic_series(n: int = 32, z: int = 3, t: int = 40, seed: int = 0) -> np.ndarray:
    """A bright central disk over a noisy background: (n, n, z, t), float64.

    The disk carries seeded temporal noise (the fluctuation the stability metrics
    measure); the background carries a static magnitude floor (see
    `BACKGROUND_SCALE`) so the phantom is separable from it.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, PHANTOM_SIGNAL, 0.0)
    floor = np.abs(rng.normal(scale=BACKGROUND_SCALE, size=(n, n, z, t)))
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    return np.asarray(base[:, :, None, None] + noise + floor, dtype=np.float64)


@pytest.fixture
def make_scan() -> MakeScan:
    """Return a factory building an in-memory `QAScan` over `synthetic_series`.

    The in-code counterpart of `write_scan`, for the tests that exercise the pure
    pipeline and need no file on disk. `pe_axis=1` is passed explicitly so the
    ghost-estimate fallback (and its warning) stays out of the way.
    """

    def factory(seed: int = 0, n: int = 32, z: int = 3, t: int = 40) -> q.QAScan:
        data = synthetic_series(n=n, z=z, t=t, seed=seed)
        return q.QAScan(data=data, tr=2.0, pe_axis=1)

    return factory


@pytest.fixture
def write_scan() -> WriteScan:
    """Return a factory writing a synthetic phantom NIfTI + sidecar.

    A bright central disk with seeded temporal noise, 3 mm isotropic voxels and
    TR 2 s. The sidecar sets `PhaseEncodingDirection` so the PE axis resolves
    from metadata (no ghost-estimate fallback warning). Returns the NIfTI path.

    The background carries a Rician-like noise floor, as a real magnitude image
    does. That matters: on an *exactly* constant background the intensity
    quantiles that seed `segment_phantom` degenerate, so a zero-background
    fixture would exercise a failure path instead of the segmentation.
    """

    def factory(
        directory: Path,
        name: str = "scan",
        n: int = 32,
        z: int = 3,
        t: int = 40,
        seed: int = 0,
        flip: float = 77,
    ) -> str:
        data = synthetic_series(n=n, z=z, t=t, seed=seed)

        img = nib.Nifti1Image(data, affine=np.eye(4))
        img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
        img.header.set_xyzt_units("mm", "sec")
        nifti = directory / f"{name}.nii.gz"
        nib.save(img, str(nifti))
        (directory / f"{name}.json").write_text(
            json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
        )
        return str(nifti)

    return factory


@pytest.fixture
def artifact(tmp_path, write_scan) -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI."""
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    settings = q.AnalysisSettings(roi_size=9)
    return q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")
