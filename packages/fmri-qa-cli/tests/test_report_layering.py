"""Importing the commands must not load the calculation stack or matplotlib.

`fmri-qa-report` reads an artifact and renders it only when a page is written,
and the other commands reach core through its lazy root. A static scan of import
text cannot see what an import *executes*; only a fresh interpreter's
`sys.modules` can. The probe imports the `fmriqa_cli` package, whose root
imports every command, so it covers the report command along with the rest.
"""

import subprocess
import sys

# The calculation stack, the third-party libraries only it needs, and the
# drawing stack. Importing the commands reaches none of these.
_FORBIDDEN = (
    "fmriqa.pipeline",
    "fmriqa.metrics",
    "fmriqa.prep",
    "fmriqa.load",
    "skimage",
    "scipy",
    "nibabel",
    "netCDF4",
    "matplotlib",
)

# Run in a fresh interpreter. Only a process that has imported nothing else can
# say what the import costs; this one already has the whole stack loaded by
# other tests.
_PROBE = f"""
import sys
import fmriqa_cli
{{extra}}
forbidden = {_FORBIDDEN!r}
loaded = sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
)
print(loaded)
"""


def _probe(extra: str = "") -> str:
    """Run `_PROBE`, with `extra` imported after the package; return its list."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _PROBE.format(extra=extra)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_importing_fmriqa_cli_does_not_load_the_calculation_stack() -> None:
    output = _probe()
    assert output == "[]", (
        f"importing fmriqa_cli loaded the calculation stack or matplotlib: {output}"
    )


def test_the_probe_would_catch_a_forbidden_module() -> None:
    """A negative control, so the probe cannot pass by failing to see anything."""
    assert "fmriqa.pipeline" in _probe("import fmriqa.pipeline")
