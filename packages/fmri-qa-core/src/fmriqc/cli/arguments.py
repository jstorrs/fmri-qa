"""Argument types and diagnostics all three commands share.

The `argparse` `type=` callables that reject an out-of-range value at parse
time — so a bad flag is a usage error with a clear message rather than a
traceback deep in the pipeline — the warning reprinter all three commands route
their captured warnings through, the wildcard expansion that makes one
documented command line work in a shell that does not expand its own, and the
shared `--version` action.
"""

import argparse
import glob
import math
import re
import sys
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path

import fmriqc as q

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


class PrintVersion(argparse.Action):
    """`--version`, resolved on use rather than when the parser is built."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        # stdout, and only then exit: `parser.exit(message=...)` would send it
        # to stderr, where argparse's own `action="version"` never put it.
        print(f"{parser.prog} {q.core_version()}")
        parser.exit()


def expand_globs(paths: Sequence[str]) -> list[str]:
    """Every path, with any wildcard pattern that named nothing expanded here.

    A POSIX shell expands a wildcard before the command is started, so `fmri-qa
    data/*.nii.gz` arrives as one argument per scan. PowerShell and cmd do not:
    the same line -- the line `fmri-qa-import` prints for the user to paste --
    arrives as a single literal argument with a `*` still in it, and fails as a
    missing file naming a path no one typed. Expanding here makes one command
    line mean the same thing on every platform.

    An argument naming something that exists is never expanded, so a file whose
    name really does contain a wildcard character is still usable, and on POSIX
    (where the shell already did this) every argument takes that path. A pattern
    matching nothing is passed through as itself, to be reported as the missing
    input it is rather than silently dropped -- which would turn a mistyped
    pattern into a run that quietly analyzed fewer scans than were asked for.
    """
    expanded: list[str] = []
    for path in paths:
        if Path(path).exists() or not _WILDCARD.search(path):
            expanded.append(path)
            continue
        # glob.glob, not Path.glob: the pattern is one string that may carry
        # wildcards in its directory components too, and be absolute or
        # relative. Path.glob cannot take that without being taken apart first.
        matched = sorted(glob.glob(path, recursive=True))  # noqa: PTH207
        expanded.extend(matched or [path])
    return expanded


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected a finite number greater than or equal to 0"
        )
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def nonempty(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("expected a non-empty path")
    return value


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected an integer greater than or equal to 0"
        )
    return parsed


def print_warnings(caught: Iterable[warnings.WarningMessage], subject: str) -> None:
    """Reprint captured warnings on stderr, named for what was being analyzed.

    Python's default formatter names the source line the warning is attributed
    to — for the package's own warnings, the console-script frame that called
    into it — and the category, and says nothing about the data. In a batch
    that is exactly backwards: which scan provoked the warning is the only thing
    an operator can act on, and the source line is noise the pipeline's own
    authors read. So the warnings are captured around each scan's analysis and
    reprinted attributed, on stderr, where the table's diagnostics belong.
    """
    for entry in caught:
        print(f"{subject}: warning: {entry.message}", file=sys.stderr)
