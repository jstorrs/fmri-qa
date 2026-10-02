"""Argument types and diagnostics all three commands share.

The `argparse` `type=` callables that reject an out-of-range value at parse
time — so a bad flag is a usage error with a clear message rather than a
traceback deep in the pipeline — the warning reprinter all three commands route
their captured warnings through, and the shared `--version` action.
"""

import argparse
import math
import sys
import warnings
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import fmriqc as q


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


@contextmanager
def attributed_warnings(subject: str) -> Iterator[None]:
    """Capture warnings raised in the block and reprint them naming `subject`.

    The reprint happens on every exit, so a block that fails still reports the
    warnings it raised on the way down; a handler inside the block prints its
    own error first.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            print_warnings(caught, subject)
