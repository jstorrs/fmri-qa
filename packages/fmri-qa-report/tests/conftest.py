"""Shared fixtures for the presentation-half tests.

Every fixture here stops at a `QAArtifact` — the report package's only input.
The artifact is built in memory from a synthetic phantom, so these tests need no
NIfTI on disk and no file-I/O layer: `QAScan` is constructed directly, which is
also a small proof that the seam holds.
"""

import numpy as np
import pytest

import fmriqc as q


def _phantom(n: int = 32, z: int = 3, t: int = 40, seed: int = 0) -> q.QAScan:
    """Build a synthetic bright-disk phantom series with seeded temporal noise.

    The background gets a magnitude noise floor, mirroring the calculation half's
    fixture: an exactly-constant background degenerates the intensity quantiles
    that seed the phantom segmentation, and a report rendered from a collapsed
    mask would be a report of NaNs rather than of panels.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    floor = np.abs(rng.normal(scale=8.0, size=(n, n, z, t)))
    data = np.where(disk, 1000.0, 0.0)[:, :, None, None] + noise + floor
    meta = q.ScanMeta(
        voxel_mm=(3.0, 3.0, 3.0),
        matrix=(n, n),
        tr=2.0,
        flip_angle=77.0,
        pe_dir="col",
        manufacturer="Acme",
        model="Scanner 3T",
        field_strength=3.0,
        serial="12345",
        datetime="2026-01-02 03:04:05",
    )
    return q.QAScan(data=data, tr=2.0, pe_axis=1, meta=meta)


@pytest.fixture(scope="session")
def artifact() -> q.QAArtifact:
    """One analyzed artifact, shared across the session (analysis is not cheap)."""
    return q.analyze(
        _phantom(), q.AnalysisSettings(roi_size=9), name="scan.nii.gz", source="scan"
    )


@pytest.fixture(scope="session")
def bare_artifact() -> q.QAArtifact:
    """An artifact with no sidecar metadata, to exercise the missing-field paths."""
    scan = q.QAScan(data=_phantom(seed=7).data, tr=2.0, pe_axis=1)
    return q.analyze(scan, q.AnalysisSettings(roi_size=9), name="bare.nii.gz")
