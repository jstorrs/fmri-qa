"""Shared fixtures for the presentation-half tests.

Every fixture stops at a `QAAnalysis`, the report package's only input. It is
built in memory from a synthetic phantom, so no NIfTI on disk or file-I/O layer
is needed. `QAScan` is constructed directly, which also shows the seam holds.
"""

from dataclasses import replace

import pytest

import fmriqa as q
from fmriqa.testing import phantom_scan


def _phantom(n: int = 32, z: int = 3, t: int = 40, seed: int = 0) -> q.QAScan:
    """Build the shared synthetic phantom with report-page metadata.

    The scan is `fmriqa.testing.phantom_scan`, the calculation half's fixture,
    which the docs draw a variant of. Only the sidecar fields a report page
    shows are added, so the geometry, TR and phase-encode axis cannot drift from
    the data. Its Rayleigh background keeps the intensity quantiles that seed
    the phantom segmentation from collapsing, which would fill the report with
    NaNs.
    """
    scan = phantom_scan(n=n, z=z, t=t, seed=seed)
    meta = replace(
        scan.meta,
        manufacturer="Acme",
        model="Scanner 3T",
        field_strength=3.0,
        serial="12345",
        datetime="2026-01-02 03:04:05",
    )
    return replace(scan, meta=meta)


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
