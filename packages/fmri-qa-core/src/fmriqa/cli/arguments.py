"""Argument types and diagnostics all three commands share.

The `argparse` `type=` callables that reject an out-of-range value at parse
time, so a bad flag is a usage error with a clear message and not a traceback
deep in the pipeline. Also the warning reprinter that all three commands route
their captured warnings through, and the shared `--version` action.
"""

import argparse
import math
import sys
import warnings
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import fmriqa as q


class PrintVersion(argparse.Action):
    """`--version`, resolved on use rather than when the parser is built."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """Print the program name and core version, then exit."""
        # Print to stdout, then exit. `parser.exit(message=...)` would send it
        # to stderr, where argparse's own `action="version"` never puts it.
        print(f"{parser.prog} {q.core_version()}")
        parser.exit()


def nonnegative_float(value: str) -> float:
    """Parse a finite number of at least zero."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected a finite number greater than or equal to 0"
        )
    return parsed


def positive_int(value: str) -> int:
    """Parse a positive integer."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def nonempty(value: str) -> str:
    """Accept a non-empty path argument."""
    if not value:
        raise argparse.ArgumentTypeError("expected a non-empty path")
    return value


def nonnegative_int(value: str) -> int:
    """Parse an integer of at least zero."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected an integer greater than or equal to 0"
        )
    return parsed


def print_warnings(caught: Iterable[warnings.WarningMessage], subject: str) -> None:
    """Reprint captured warnings on stderr, named for what was being analyzed.

    Python's default formatter names the source line and category, which for
    this package's warnings is the console-script frame, and says nothing about
    the data. In a batch, an operator needs the scan that provoked the warning.
    So warnings are captured around each scan's analysis and reprinted with the
    scan's name on stderr, where the table's diagnostics go.
    """
    for entry in caught:
        print(f"{subject}: warning: {entry.message}", file=sys.stderr)


@contextmanager
def attributed_warnings(subject: str) -> Iterator[None]:
    """Capture warnings raised in the block and reprint them naming `subject`.

    The reprint happens on every exit, so a block that fails still reports the
    warnings it raised. A handler inside the block prints its own error first.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            print_warnings(caught, subject)
