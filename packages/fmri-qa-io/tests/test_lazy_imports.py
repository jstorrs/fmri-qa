"""The lazy `fmriqa_io/__init__.py` re-export: names resolve, nothing loads early.

The root is lazy so that importing one Pyodide-safe submodule never imports the
filesystem-bound ones. That holds only if `_EXPORTS` never drifts from
`__all__` and a bare `import fmriqa_io` loads no submodule. Both are asserted
here.
"""

import subprocess
import sys

import pytest

import fmriqa_io

# Run in a fresh interpreter: this process has imported submodules in other tests.
_PROBE = """
import sys
import fmriqa_io
print(sorted(m for m in sys.modules if m.startswith("fmriqa_io.")))
"""


def test_every_exported_name_is_reachable() -> None:
    for name in fmriqa_io.__all__:
        assert getattr(fmriqa_io, name) is not None, f"fmriqa_io.{name} is None"


def test_exports_map_covers_all_and_nothing_else() -> None:
    flattened = {name for names in fmriqa_io._EXPORTS.values() for name in names}
    assert flattened == set(fmriqa_io.__all__)
    # No name claimed by two modules; a duplicate would silently shadow.
    assert sum(len(names) for names in fmriqa_io._EXPORTS.values()) == len(flattened)


def test_dir_lists_the_public_names() -> None:
    assert dir(fmriqa_io) == sorted(fmriqa_io.__all__)


def test_unknown_attribute_raises_standard_attribute_error() -> None:
    with pytest.raises(
        AttributeError, match="module 'fmriqa_io' has no attribute 'bogus'"
    ):
        fmriqa_io.bogus  # noqa: B018 - the attribute access is the test


def test_bare_import_loads_no_submodule() -> None:
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout + result.stderr


def test_importing_the_artifact_module_does_not_load_netcdf4() -> None:
    """`netCDF4` loads libhdf5 and libnetcdf, so it waits for a file.

    The report CLI imports `fmriqa_io.artifact` to read one artifact, and
    `--help` must not pay for the native libraries first.
    """
    probe = "import sys, fmriqa_io.artifact; print('netCDF4' in sys.modules)"
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False", result.stdout + result.stderr
