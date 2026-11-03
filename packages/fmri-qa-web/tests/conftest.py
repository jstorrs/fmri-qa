"""Shared fixtures: an analyzable synthetic phantom as in-memory bytes."""

from pathlib import Path

import pytest

from fmriqa_io.testing import write_phantom

STEM = "20260909_143012_s002_QA_EPI_ISO"


@pytest.fixture(scope="session")
def phantom_bytes(tmp_path_factory: pytest.TempPathFactory) -> tuple[bytes, bytes]:
    """The phantom NIfTI's bytes and its sidecar's."""
    directory = tmp_path_factory.mktemp("phantom")
    nifti = write_phantom(directory)
    return nifti.read_bytes(), nifti.with_name("scan.json").read_bytes()


@pytest.fixture(scope="session")
def short_phantom_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """A 2-frame phantom: decodes, but is too short to analyze."""
    directory: Path = tmp_path_factory.mktemp("short")
    return write_phantom(directory, t=2).read_bytes()
