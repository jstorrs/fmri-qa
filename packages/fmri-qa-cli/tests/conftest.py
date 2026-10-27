"""Shared fixtures for the command-line tests.

`write_scan` writes the synthetic phantom to disk, `artifact` runs the pipeline
over it once per session, and `fake_dcm2niix` builds the stub converter the
import tests drive.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

import fmriqa as q
from fmriqa.testing import phantom_scan
from fmriqa_io.testing import fake_dcm2niix_script, write_phantom

WriteScan = Callable[..., str]
FakeDcm2niix = Callable[..., Path]


@pytest.fixture
def write_scan() -> WriteScan:
    """Return a writer of a synthetic phantom NIfTI + sidecar; it returns the path.

    The path is a `str`, as the commands take it on a command line.
    """

    def write(directory: Path, name: str = "scan", **kwargs: float) -> str:
        return str(write_phantom(directory, name, **kwargs))

    return write


@pytest.fixture(scope="session")
def artifact() -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI."""
    return q.analyze(
        phantom_scan(),
        q.AnalysisSettings(roi_size=9),
        name="scan.nii.gz",
        source="scan.nii.gz",
    )


@pytest.fixture
def fake_dcm2niix(tmp_path: Path) -> FakeDcm2niix:
    """Return a builder of a stub dcm2niix in `tmp_path`; see `fake_dcm2niix_script`."""

    def build(outputs, returncode=0, name="dcm2niix", **kwargs) -> Path:
        return fake_dcm2niix_script(tmp_path, outputs, returncode, name, **kwargs)

    return build
