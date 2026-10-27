"""The dcm2niix flags a QA conversion must not leave to chance.

Four of dcm2niix's thirty-odd options decide whether the converted series can
still answer the questions `fmri-qa` asks of it. dcm2niix reads `~/.dcm2nii.ini`
before its own defaults, so a file written months ago by another tool could
change what a QA import produces without appearing on any command line.
`PINNED` sets them explicitly.

`-l o` matters most. `-l y` "losslessly" rescales 16-bit integers to fill the
dynamic range. The file is still an integer NIfTI, so `QAScan.stored_integer`
sees nothing wrong and no warning fires, but every sample has been multiplied
and the ADC rail no longer sits at `2**n - 1`. On a synthetic series clipped
flat at 4095, `-l o` finds a 12-bit rail and 7140 clipped samples, and `-l y`
finds no rail and reports the run clean. The storage gate in
`metrics.saturation` can't catch this, because the evidence it tests for is
present but wrong, so pinning the flag is the only prevention.

These are rules, not a runner. `flags` is the option list without paths, and it
is the one rule every converter shares: `fmriqa_io.convert.dcm2niix` runs the
native binary with it, and a converter that runs dcm2niix elsewhere (a wasm
build in a browser) mirrors it. `build_args` adds the paths and the
passthrough, producing an argument list a reader can compare against
`dcm2niix -h`. `extra` passes anything through, and `--filename` keeps its own
template language.
"""

import re
from collections.abc import Sequence
from itertools import pairwise
from pathlib import PurePath

from ..types import Anonymize
from ..warn import warn

# dcm2niix's `-f` template for the staged conversion. This is not the final
# name (see `naming`). It is what dcm2niix tells its own outputs apart by, and
# the fallback name when the sidecar can't identify the series. `%t` is the
# study date+time, `%s` the series number, `%d` the series description.
DEFAULT_TEMPLATE = "%t_%s_%d"
# `import_dicom`, `flags`, `build_args` and `fmri-qa-import` all default to these.
#: Default sidecar anonymization: ``"pii"``, strip the patient and keep the dates.
DEFAULT_ANONYMIZE: Anonymize = "pii"
DEFAULT_DEPTH = 5

# The flags an import fixes instead of inheriting. Each is needed:
#
#   -g i   ignore ~/.dcm2nii.ini, so the three below are in force and the same
#          directory converts the same way on every machine
#   -l o   keep the stored integers as the scanner sent them; see the module
#          docstring for what `-l y` costs the saturation check
#   -b y   write the BIDS sidecar; `load.metadata` reads TR, voxel size and
#          phase-encode direction from it, and `naming` reads the series' date
#   -w 2   add a suffix on a name conflict instead of overwriting, so two
#          colliding series both survive to be told apart later
PINNED: tuple[str, ...] = ("-g", "i", "-l", "o", "-b", "y", "-w", "2")

# `Anonymize` -> dcm2niix's `-ba`. Covers the whole Literal, so a new mode is a
# type error here, not a silently missing flag.
_BA: dict[Anonymize, str] = {"pii": "o", "all": "y", "none": "n"}

_VERSION = re.compile(r"version\s+(v[\w.]+)")


def flags(
    *,
    template: str = DEFAULT_TEMPLATE,
    compress: bool = True,
    anonymize: Anonymize = DEFAULT_ANONYMIZE,
    depth: int = DEFAULT_DEPTH,
) -> list[str]:
    """Return the dcm2niix options for one import, pinned flags first, no paths.

    This is what any converter running dcm2niix mirrors, so a series converted
    elsewhere is converted the same way. `build_args` adds the paths.
    """
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
    ]


def build_args(
    source: str | PurePath,
    destination: str | PurePath,
    *,
    template: str = DEFAULT_TEMPLATE,
    compress: bool = True,
    anonymize: Anonymize = DEFAULT_ANONYMIZE,
    depth: int = DEFAULT_DEPTH,
    extra: Sequence[str] = (),
) -> list[str]:
    """Build the dcm2niix argument list for one import: `flags`, then the paths.

    `extra` is appended after everything this function chooses, so a
    passthrough argument wins. The one that should not win is `-l`, which
    `_warn_if_rescaling` warns about.
    """
    _warn_if_rescaling(extra)
    chosen = flags(
        template=template, compress=compress, anonymize=anonymize, depth=depth
    )
    return [*chosen, "-o", str(destination), *extra, str(source)]


def _warn_if_rescaling(extra: Sequence[str]) -> None:
    """Warn if a passthrough `-l` would undo the pinned `-l o`.

    Overriding a pinned flag is allowed, since `extra` exists for cases not
    foreseen here. But this override silently disarms the saturation check
    without visibly breaking anything, so it warns. See the module docstring for
    the numbers.
    """
    for flag, value in pairwise(extra):
        if flag == "-l" and value != "o":
            warn(
                f"passing -l {value} to dcm2niix rescales the stored integers, "
                "so the saturation check will report a clipped acquisition as "
                "clean rather than as not determinable; -l o keeps them",
            )


def version(output: str) -> str | None:
    """Parse the dcm2niix version from its banner, or None if it did not say.

    Read from the run's own banner, not a second `--version` call, so it is the
    version that did the work.
    """
    match = _VERSION.search(output)
    return match.group(1) if match else None
