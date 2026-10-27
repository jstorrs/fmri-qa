"""The lazy `fmriqa/__init__.py` re-export: every name resolves, nothing heavy loads.

`fmriqa/__init__.py` replaced ~90 eager `from .x import Y` statements with a
PEP 562 `__getattr__` keyed off `_EXPORTS`, so `argparse` (`--version`,
`--help`) does not pay for scipy and scikit-image. That holds only if
`_EXPORTS` never drifts from `__all__` and a bare `import fmriqa` never imports
the heavy stack. Both are asserted here.
"""

import subprocess
import sys

import pytest

import fmriqa

# Modules a bare `import fmriqa` must never pull in. Each is expensive with one
# call site in the package (see `analysis/build.py`, `metrics/artifacts.py`), or
# is a real dependency (`skimage`) that a name access should trigger.
_HEAVY_MODULES = ("skimage", "scipy.special", "scipy.spatial")

# Probe run in a fresh interpreter (see
# test_bare_import_does_not_load_the_heavy_stack). This process already has half
# of scipy loaded from other tests.
_PROBE = f"""
import sys
import fmriqa
heavy = {_HEAVY_MODULES!r}
loaded = sorted(
    m for m in sys.modules if any(m == h or m.startswith(h + ".") for h in heavy)
)
print(loaded)
"""


def _run_probe(code: str) -> subprocess.CompletedProcess[str]:
    """Run `code` in a fresh interpreter (fixed literal source, not user input)."""
    return subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )


def test_every_exported_name_is_reachable() -> None:
    for name in fmriqa.__all__:
        value = getattr(fmriqa, name)
        assert value is not None, f"fmriqa.{name} resolved to None"


def test_exports_map_covers_all_and_nothing_else() -> None:
    flattened = {name for names in fmriqa._EXPORTS.values() for name in names}
    assert flattened == set(fmriqa.__all__)
    # No name claimed by two modules; a duplicate would silently shadow.
    assert sum(len(names) for names in fmriqa._EXPORTS.values()) == len(flattened)


def test_dir_lists_the_public_names() -> None:
    assert dir(fmriqa) == sorted(fmriqa.__all__)


def test_unknown_attribute_raises_standard_attribute_error() -> None:
    with pytest.raises(
        AttributeError, match="module 'fmriqa' has no attribute 'bogus'"
    ):
        fmriqa.bogus  # noqa: B018 - the attribute access is the test


def test_bare_import_does_not_load_the_heavy_stack() -> None:
    result = _run_probe(_PROBE)
    message = f"bare import pulled in heavy modules: {result.stdout}\n{result.stderr}"
    assert result.stdout.strip() == "[]", message


def test_accessing_a_real_name_then_works() -> None:
    result = _run_probe("import fmriqa\nassert fmriqa.QAScan is not None\n")
    assert result.returncode == 0, result.stderr
