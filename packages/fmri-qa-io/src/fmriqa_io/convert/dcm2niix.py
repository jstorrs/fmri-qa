"""Running dcm2niix: finding the binary and running it with core's flags.

The flags themselves are `fmriqa.convert.dcm2niix`'s, pure code a browser
converter can mirror. This module is the native side: which binary to run, and
running it as a subprocess.
"""

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ..exceptions import ConversionError


def find_dcm2niix(explicit: str | Path | None = None) -> Path:
    """Find the dcm2niix to run: the one named, else bundled, else on PATH.

    The `dcm2niix` PyPI package ships the compiled binary and exposes its path.
    It is a dependency of `fmri-qa-io`, so a working install uses the bundled
    binary and needs nothing from the system. A site with its own dcm2niix (a
    newer build, or one with vendor patches) names it with `--dcm2niix`. The
    bundled binary is preferred over PATH, so installing another is not enough
    to select it.

    The PATH branch and the error below cover an install that can't import the
    bundled binary: a platform with no wheel whose sdist failed to build, or a
    pruned environment.

    Raises
    ------
    ConversionError
        If no dcm2niix can be found, or the named one is not an executable file.
        A named binary that can't be run is reported, not quietly skipped.
    """
    if explicit is not None:
        found = shutil.which(str(explicit))
        if found is None:
            raise ConversionError("dcm2niix", f"{explicit} is not an executable file")
        return Path(found)
    try:
        import dcm2niix  # the PyPI wrapper: a bundled binary and its path
    except ImportError:
        pass
    else:
        return Path(dcm2niix.bin)
    found = shutil.which("dcm2niix")
    if found is None:
        raise ConversionError(
            "dcm2niix",
            "not found — the bundled dcm2niix ships as a dependency of "
            "fmri-qa-io, so this environment is missing one it should have: "
            "reinstall fmri-qa-io, put dcm2niix on PATH, or name one "
            "with --dcm2niix",
        )
    return Path(found)


def run(binary: Path, args: Sequence[str]) -> str:
    """Run dcm2niix and return everything it printed.

    dcm2niix reports per series on stdout, so its output is the log of what
    happened, and the caller decides how much to show. Which files were produced
    is not read from it. `session` converts into a directory it owns and lists
    that instead.

    Raises
    ------
    ConversionError
        If dcm2niix exits non-zero. Its own last words are carried through,
        since they name the DICOM problem far better than an exit status can.
    """
    try:
        # Not shell=True, and `binary` is an absolute path resolved by
        # `find_dcm2niix`, not a name looked up at run time.
        result = subprocess.run(  # noqa: S603
            [str(binary), *args], capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise ConversionError("dcm2niix", f"could not run {binary}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        last = detail[-1] if detail else "no output"
        raise ConversionError("dcm2niix", f"exited {result.returncode}: {last}")
    return result.stdout
