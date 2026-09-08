"""Argument types and diagnostics both commands share.

The `argparse` `type=` callables that reject an out-of-range value at parse
time — so a bad flag is a usage error with a clear message rather than a
traceback deep in the pipeline — plus the warning reprinter both commands route
their captured warnings through.
"""

import argparse
import math
import sys
import warnings
from collections.abc import Iterable


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


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected an integer greater than or equal to 0"
        )
    return parsed


def print_warnings(caught: Iterable[warnings.WarningMessage], subject: str) -> None:
    """Reprint captured warnings on stderr, named for what was being analyzed.

    Python's default formatter names the line that called `warn` — a path inside
    this package — and the category, and says nothing about the data. In a batch
    that is exactly backwards: which scan provoked the warning is the only thing
    an operator can act on, and the source line is noise the pipeline's own
    authors read. So the warnings are captured around each scan's analysis and
    reprinted attributed, on stderr, where the table's diagnostics belong.
    """
    for entry in caught:
        print(f"{subject}: warning: {entry.message}", file=sys.stderr)
