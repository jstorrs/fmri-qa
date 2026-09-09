"""Running dcm2niix, and the flags a QA conversion must not leave to chance.

dcm2niix has some thirty options and most are matters of taste. Four are not,
because they decide whether the series that comes out can still answer the
questions `fmri-qa` asks of it — and they are *defaults*, which is the problem:
a default is not a decision, and dcm2niix reads `~/.dcm2nii.ini` before its own
defaults, so a file written months ago by another tool can change what a QA
import produces without appearing on anyone's command line. `PINNED` states
them explicitly instead.

`-l o` is the one that matters most, and the reason this module exists rather
than a line in the README telling people to run dcm2niix themselves. `-l y`
"losslessly" rescales 16-bit integers to fill the dynamic range: the file it
writes is *still an integer NIfTI*, so `QAScan.stored_integer` sees nothing
wrong and no warning fires, but every stored sample has been multiplied and the
ADC rail no longer sits at `2**n - 1`. Measured on a synthetic series clipped
flat at 4095: `-l o` finds a 12-bit rail and 7140 clipped samples, `-l y` finds
no rail and reports the run clean. That is the one saturation failure the
storage gate in `metrics.saturation` cannot catch, because the evidence it tests
for is present and merely wrong — which makes pinning the flag the only place
the mistake can be prevented.

The rest of the surface is deliberately thin. dcm2niix is a well-understood
program and this is not a wrapper trying to hide it: `build_args` produces an
argument list a reader can compare against `dcm2niix -h`, `extra` passes
anything through, and `--filename` keeps its own template language available.
"""

import re
import shutil
import subprocess
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from warnings import warn

from ..exceptions import ConversionError
from ..types import Anonymize

# dcm2niix's `-f` template for the staged conversion. Not the name a series is
# finally filed under (see `naming`) — it is what dcm2niix distinguishes its own
# outputs by, and the name a series falls back to when its sidecar cannot say
# who it is. `%t` is the study date+time, `%s` the series number, `%d` the
# series description.
DEFAULT_TEMPLATE = "%t_%s_%d"

# The flags an import fixes rather than inherits. Each one is load-bearing:
#
#   -g i   ignore ~/.dcm2nii.ini, so the three below are actually in force and
#          the same directory converts the same way on every machine
#   -l o   keep the stored integers exactly as the scanner sent them; see the
#          module docstring for what `-l y` costs the saturation check
#   -b y   write the BIDS sidecar — `load.metadata` reads TR, voxel size and
#          phase-encode direction from it, and `naming` reads the series' date
#   -w 2   add a suffix on a name conflict rather than overwrite; two series
#          that collide must both survive to be told apart later
PINNED: tuple[str, ...] = ("-g", "i", "-l", "o", "-b", "y", "-w", "2")

# `Anonymize` -> dcm2niix's `-ba`. Total over the Literal, so a new mode is a
# type error here rather than a silently missing flag.
_BA: dict[Anonymize, str] = {"pii": "o", "all": "y", "none": "n"}

_VERSION = re.compile(r"version\s+(v[\w.]+)")


def find_dcm2niix(explicit: str | Path | None = None) -> Path:
    """The dcm2niix to run: the one named, else the bundled one, else PATH.

    The `dcm2niix` PyPI package ships the compiled binary and exposes its path,
    and it is a dependency of `fmri-qa-core`, so the bundled branch is the one
    that answers on a working install and an import needs nothing from the
    system. A site that already has its own dcm2niix — a newer build, or one
    with vendor patches — names it with `--dcm2niix`; the bundled binary is
    preferred over PATH, so having one installed is not enough to select it.

    The PATH branch and the error below are what is left for an install that
    cannot import the bundled binary at all: a platform with no wheel that
    fell back to the sdist and failed to build it, or a pruned environment.

    Raises:
        ConversionError: If no dcm2niix can be found, or the named one is not
            an executable file. Naming one that cannot be run is a mistake worth
            reporting rather than quietly falling back past.
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
            "fmri-qa-core, so this environment is missing one it should have: "
            "reinstall fmri-qa-core, put dcm2niix on PATH, or name one "
            "with --dcm2niix",
        )
    return Path(found)


def build_args(
    source: Path,
    destination: Path,
    *,
    template: str = DEFAULT_TEMPLATE,
    compress: bool = True,
    anonymize: Anonymize = "pii",
    depth: int = 5,
    extra: Sequence[str] = (),
) -> list[str]:
    """The dcm2niix argument list for one import, pinned flags first.

    `extra` is appended *after* everything this function chooses, so a
    passthrough argument wins — that is what makes it an escape hatch rather
    than a suggestion. The one it should not win is `-l`, which is what
    `_warn_if_rescaling` says out loud.
    """
    _warn_if_rescaling(extra)
    return [
        *PINNED,
        "-f",
        template,
        "-z",
        "y" if compress else "n",
        "-ba",
        _BA[anonymize],
        "-d",
        str(depth),
        "-o",
        str(destination),
        *extra,
        str(source),
    ]


def _warn_if_rescaling(extra: Sequence[str]) -> None:
    """Warn if a passthrough `-l` would undo the pinned `-l o`.

    Overriding a pinned flag is allowed — `extra` exists for the case the author
    of this module did not foresee — but this particular override silently
    disarms the saturation check rather than breaking anything visibly, so it
    does not get to happen quietly. See the module docstring for the numbers.
    """
    for flag, value in pairwise(extra):
        if flag == "-l" and value != "o":
            warn(
                f"passing -l {value} to dcm2niix rescales the stored integers, "
                "so the saturation check will report a clipped acquisition as "
                "clean rather than as not determinable; -l o keeps them",
                stacklevel=3,
            )


def run(binary: Path, args: Sequence[str]) -> str:
    """Run dcm2niix and return everything it printed.

    dcm2niix reports per series on stdout and is quiet about nothing, so its
    output is the log of what happened; the caller decides how much of it to
    show. Which files were produced is *not* read back out of it — `session`
    converts into a directory it owns and lists that instead, so the answer
    comes from the filesystem rather than from parsing a human-readable line.

    Raises:
        ConversionError: If dcm2niix exits non-zero. Its own last words are
            carried through, since they name the DICOM problem far better than
            an exit status can.
    """
    try:
        # Not shell=True, and `binary` is an absolute path resolved by
        # `find_dcm2niix` rather than a name looked up at run time.
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


def version(output: str) -> str | None:
    """The dcm2niix version out of its own banner, or None if it did not say.

    Read from the run's output rather than asked for with a second `--version`
    call: the banner is the first line of every conversion, and the version that
    did the work is the one worth reporting.
    """
    match = _VERSION.search(output)
    return match.group(1) if match else None
