"""Shared fixtures for the calculation-half tests.

The phantom every test measures against is `fmriqa.testing.synthetic_series`.
Core reads no files, so every scan here is built in memory. `artifact` runs the
whole pipeline over the phantom once per session.
"""

import dataclasses
from collections.abc import Callable, Iterator

import numpy as np
import pytest

import fmriqa as q
from fmriqa.testing import phantom_scan, synthetic_series

MakeScan = Callable[..., "q.QAScan"]


@pytest.fixture
def make_scan() -> MakeScan:
    """Return a factory building an in-memory `QAScan` over `synthetic_series`.

    `pe_axis=1` is passed explicitly to skip the ghost-estimate fallback and its
    warning.
    """

    def factory(seed: int = 0, n: int = 32, z: int = 3, t: int = 40) -> q.QAScan:
        data = synthetic_series(n=n, z=z, t=t, seed=seed)
        return q.QAScan(data=data, tr=2.0, pe_axis=1)

    return factory


def _arrays(obj: object) -> Iterator[np.ndarray]:
    """Every ndarray reachable through dataclass fields of `obj`."""
    if isinstance(obj, np.ndarray):
        yield obj
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _arrays(getattr(obj, f.name))


@pytest.fixture(scope="session")
def artifact() -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI.

    Built once per session and shared. The artifact is frozen with read-only
    arrays, so no test can change it for another. The assertion below checks
    that.
    """
    scan = phantom_scan()
    settings = q.AnalysisSettings(roi_size=9)
    result = q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")
    assert not any(a.flags.writeable for a in _arrays(result)), (
        "shared artifact has a writeable array"
    )
    return result
