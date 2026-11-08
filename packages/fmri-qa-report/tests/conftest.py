"""Shared fixtures for the presentation-half tests.

Every fixture stops at a `QAAnalysis`, the report package's only input. It is
built in memory from a synthetic phantom, so no NIfTI on disk or file-I/O layer
is needed. `QAScan` is constructed directly, which also shows the seam holds.
"""

import numpy as np
import pytest

import fmriqa as q


def _phantom(n: int = 32, z: int = 3, t: int = 40, seed: int = 0) -> q.QAScan:
    """Build a synthetic bright-disk phantom series with seeded temporal noise.

    The background gets a magnitude noise floor, as in the calculation half's
    fixture. A constant background collapses the intensity quantiles that seed
    the phantom segmentation, and the report would be full of NaNs.
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
def analysis() -> q.QAAnalysis:
    """One analyzed analysis, shared across the session (analysis is not cheap)."""
    return q.analyze(
        _phantom(), q.AnalysisSettings(roi_size=9), name="scan.nii.gz", source="scan"
    )


@pytest.fixture(scope="session")
def bare_analysis() -> q.QAAnalysis:
    """An analysis with no sidecar metadata, to exercise the missing-field paths."""
    scan = q.QAScan(data=_phantom(seed=7).data, tr=2.0, pe_axis=1)
    return q.analyze(scan, q.AnalysisSettings(roi_size=9), name="bare.nii.gz")
