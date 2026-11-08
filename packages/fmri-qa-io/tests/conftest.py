"""Shared fixtures for the analysis-file and import tests.

`analysis` runs the whole pipeline over `fmriqa.testing.phantom_scan` once per
session. `read_netcdf` and `encode` reach a stored analysis below
`load_analysis` and `save_analysis`. `fake_dcm2niix` builds the stub converter
the import tests drive.
"""

import dataclasses
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import netCDF4
import numpy as np
import pytest

import fmriqa as q
from fmriqa.testing import phantom_scan
from fmriqa_io.analysis_file import netcdf
from fmriqa_io.testing import fake_dcm2niix_script

FakeDcm2niix = Callable[..., Path]


def _arrays(obj: object) -> Iterator[np.ndarray]:
    """Every ndarray reachable through dataclass fields of `obj`."""
    if isinstance(obj, np.ndarray):
        yield obj
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _arrays(getattr(obj, f.name))


@pytest.fixture(scope="session")
def analysis() -> q.QAAnalysis:
    """An analysis from the synthetic phantom, at a small ROI.

    Built once per session and shared. The analysis is frozen with read-only
    arrays, so no test can change it for another. The assertion below checks
    that.
    """
    scan = phantom_scan()
    settings = q.AnalysisSettings(roi_size=9)
    result = q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")
    assert not any(a.flags.writeable for a in _arrays(result)), (
        "shared analysis has a writeable array"
    )
    return result


@pytest.fixture
def read_netcdf() -> Callable[[Path], tuple[dict, dict[str, np.ndarray]]]:
    """Return a reader of a stored analysis that drives `netCDF4` directly.

    Tests that corrupt or inspect a stored analysis use plain netCDF instead of
    the package's `netcdf` module, since readability that way is why this
    container was chosen.
    """

    def read(path: Path) -> tuple[dict, dict[str, np.ndarray]]:
        """The document and every array of a stored analysis, read with netCDF4 alone.

        Coordinate variables are skipped. They are derived on the way out, so the
        result is what `decompose` produced.
        """
        with netCDF4.Dataset(str(path)) as dataset:
            dataset.set_auto_mask(False)
            document = json.loads(dataset.getncattr("document"))
            arrays = {
                name: (
                    np.asarray(variable[...] != 0)
                    if "flag_values" in variable.ncattrs()
                    else np.asarray(variable[...])
                )
                for name, variable in dataset.variables.items()
                if name not in dataset.dimensions
            }
        return document, arrays

    return read


@pytest.fixture
def encode() -> Callable[[dict, dict[str, np.ndarray]], bytes]:
    """Return `netcdf.encode` as `save_analysis` calls it: text and its parse."""

    def run(document: dict, arrays: dict[str, np.ndarray]) -> bytes:
        text = json.dumps(document)
        return netcdf.encode(text, json.loads(text), arrays)

    return run


@pytest.fixture
def fake_dcm2niix(tmp_path: Path) -> FakeDcm2niix:
    """Return a builder of a stub dcm2niix in `tmp_path`; see `fake_dcm2niix_script`."""

    def build(outputs, returncode=0, name="dcm2niix", **kwargs) -> Path:
        return fake_dcm2niix_script(tmp_path, outputs, returncode, name, **kwargs)

    return build
