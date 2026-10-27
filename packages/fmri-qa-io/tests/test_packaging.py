"""The installed requirements leave netCDF4 and dcm2niix out of a browser install.

Pyodide reports `sys_platform` "emscripten", and micropip evaluates each
requirement's marker against it. netCDF4 and dcm2niix are native wheels with no
Pyodide build, so their markers must exclude them there and keep them everywhere
else. This reads the markers off the installed distribution's metadata, which is
what micropip and pip see.
"""

from importlib.metadata import requires

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_EMSCRIPTEN = {"sys_platform": "emscripten", "platform_system": "Emscripten"}
_LINUX = {"sys_platform": "linux", "platform_system": "Linux"}


def _installed(environment: dict[str, str]) -> set[str]:
    """The normalized names of io's requirements that apply in `environment`.

    Normalized because the metadata spells a name however the build wrote it
    (`netCDF4` arrives as `netcdf4`).
    """
    requirements = [Requirement(line) for line in requires("fmri-qa-io") or []]
    return {
        canonicalize_name(r.name)
        for r in requirements
        if r.marker is None or r.marker.evaluate(environment)
    }


@pytest.mark.parametrize(
    ("environment", "expected"),
    [(_EMSCRIPTEN, False), (_LINUX, True)],
    ids=["emscripten", "linux"],
)
def test_netcdf4_is_required_only_off_the_browser(
    environment: dict[str, str], expected: bool
) -> None:
    installed = _installed(environment)
    assert "fmri-qa-core" in installed
    assert ("netcdf4" in installed) is expected


@pytest.mark.parametrize(
    ("environment", "expected"),
    [(_EMSCRIPTEN, False), (_LINUX, True)],
    ids=["emscripten", "linux"],
)
def test_dcm2niix_is_required_only_off_the_browser(
    environment: dict[str, str], expected: bool
) -> None:
    assert ("dcm2niix" in _installed(environment)) is expected
