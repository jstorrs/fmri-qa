"""`--help` and `--version` stay cheap: neither imports the heavy numeric stack.

The commands reach core through the lazy `fmriqa` root, so argparse has to run
before scipy and scikit-image load. `fmri-qa-hilo` is not covered: its parser
reads `HILO_ERODE` and `DETREND_METHODS` from core, which load them. Each probe
runs in a fresh interpreter, because this process has already imported scipy
and scikit-image in other tests.
"""

import subprocess
import sys

import pytest

_PROBE = """
import sys
import fmriqa_cli
try:
    fmriqa_cli.{entry}(["{flag}"])
except SystemExit:
    pass
print(sorted(m for m in ("scipy", "skimage") if m in sys.modules))
"""


@pytest.mark.parametrize("flag", ["--help", "--version"])
@pytest.mark.parametrize("entry", ["main", "import_main"])
def test_a_flag_that_only_prints_does_not_load_the_heavy_stack(
    entry: str, flag: str
) -> None:
    code = _PROBE.format(entry=entry, flag=flag)
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip().endswith("[]"), result.stdout + result.stderr
