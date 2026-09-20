"""`fmri-qa-run`: one DICOM directory in, one report directory per series out.

The command-line front end over `session.run_session`. With both directories
given it runs the pipeline once and reports every outcome; with neither, it
opens the desktop panel (`.panel`, not built yet -- see `_launch_panel`).
Giving exactly one directory, or any flag without both directories, is a
usage error: the panel takes no flags in this commit, so there is no
"partially configured panel" state to support.

The heavy stack (`fmriqc`'s pipeline, `fmriqc_report`'s renderer) is reached
only through `.session`, imported inside `main` after argument parsing --
never at module or parser-build time -- so `-h`, a bad flag, and the
zero-argument panel path all stay as cheap as parsing itself.
"""

import argparse
import math
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

from fmriqc.settings import AnalysisSettings

from .exceptions import LauncherError, RequestError
from .progress import Progress, describe
from .request import (
    ANONYMIZE_CHOICES,
    ANONYMIZE_HELP,
    CENTER_CHOICES,
    CENTER_HELP,
    DEFAULT_ANONYMIZE,
    DEFAULT_SETTINGS,
    DETREND_CHOICES,
    DETREND_HELP,
    DICOM_DIR_HELP,
    DICOM_DIR_LABEL,
    OPEN_REPORT_HELP,
    OUTPUT_DIR_HELP,
    OUTPUT_DIR_LABEL,
    ROI_SIZE_HELP,
    TRIM_SEC_HELP,
    RunRequest,
)
from .results import open_results
from .version import launcher_version

__all__ = ["main"]


class _PrintVersion(argparse.Action):
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
        print(f"{parser.prog} {launcher_version()}")
        parser.exit()


def _nonnegative_float(value: str) -> float:
    """Mirrors `fmriqc.cli.arguments.nonnegative_float` -- see the module docstring."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected a finite number greater than or equal to 0"
        )
    return parsed


def _positive_int(value: str) -> int:
    """Mirrors `fmriqc.cli.arguments.positive_int` -- see this module's docstring."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-run",
        description="Run fmri-qa end to end: one DICOM directory in, one report "
        "directory per series out. With neither directory given, opens the "
        "desktop panel.",
    )
    parser.add_argument("--version", action=_PrintVersion, nargs=0)
    parser.add_argument("dicom_dir", nargs="?", default=None, help=DICOM_DIR_HELP)
    parser.add_argument("output_dir", nargs="?", default=None, help=OUTPUT_DIR_HELP)
    parser.add_argument(
        "--trim-sec",
        type=_nonnegative_float,
        default=DEFAULT_SETTINGS.trim_sec,
        help=TRIM_SEC_HELP,
    )
    parser.add_argument(
        "--detrend",
        choices=DETREND_CHOICES,
        default=DEFAULT_SETTINGS.detrend,
        help=DETREND_HELP,
    )
    parser.add_argument(
        "--center",
        choices=CENTER_CHOICES,
        default=DEFAULT_SETTINGS.center,
        help=CENTER_HELP,
    )
    parser.add_argument(
        "--roi-size",
        type=_positive_int,
        default=DEFAULT_SETTINGS.roi_size,
        help=ROI_SIZE_HELP,
    )
    parser.add_argument(
        "--anonymize",
        choices=ANONYMIZE_CHOICES,
        default=DEFAULT_ANONYMIZE,
        help=ANONYMIZE_HELP,
    )
    parser.add_argument(
        "--dcm2niix",
        metavar="PATH",
        default=None,
        help="Use this dcm2niix executable instead of the bundled one.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help=OPEN_REPORT_HELP,
    )
    return parser


def _launch_panel() -> int:
    """Open the desktop panel, or explain on stderr why it could not start.

    `.panel` does not exist yet -- a later commit adds it -- so today the
    `ImportError` branch below is the only one reached. `import_module` (not
    a plain `from . import panel`) is what lets a type checker resolve this
    module cleanly before `.panel` exists at all: there is no import target
    for it to fail to find.
    """
    try:
        panel = import_module(f"{__package__}.panel")
    except ImportError:
        print(
            "ERROR: the desktop panel needs tkinter, which this Python does "
            "not have (or the panel is not available); pass the DICOM "
            "directory and the output directory on the command line instead.\n"
            "usage: fmri-qa-run DICOM_DIR OUTPUT_DIR [options]",
            file=sys.stderr,
        )
        return 2
    return int(panel.main())


def main(argv: Sequence[str] | None = None) -> int:
    """Run one session from the command line, or open the panel with no arguments.

    Report paths go to stdout, one per line, so the command composes; progress,
    refusals, failures and warnings go to stderr. Returns 0 when every series
    was published, 1 when any was refused or failed or the run could not
    happen, and 2 for a usage error.
    """
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    given = sum(d is not None for d in (args.dicom_dir, args.output_dir))
    if given == 1:
        parser.error(
            f"give both the {DICOM_DIR_LABEL} and the {OUTPUT_DIR_LABEL}, or neither"
        )
    if given == 0:
        if argv:
            parser.error(
                "the desktop panel takes no options; pass the DICOM directory "
                "and the output directory on the command line, or neither"
            )
        return _launch_panel()

    try:
        settings = AnalysisSettings(
            trim_sec=args.trim_sec,
            detrend=args.detrend,
            center=args.center,
            roi_size=args.roi_size,
        )
        request = RunRequest(
            dicom_dir=Path(args.dicom_dir),
            output_dir=Path(args.output_dir),
            settings=settings,
            anonymize=args.anonymize,
            dcm2niix=Path(args.dcm2niix) if args.dcm2niix else None,
            open_report=args.open,
        )
    except RequestError as exc:
        for problem in exc.problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1

    # Deferred past every usage error and every bad request: this is the
    # import that pulls in scipy, scikit-image, and matplotlib behind
    # `fmriqc`'s pipeline and `fmriqc_report`'s renderer -- see the module
    # docstring.
    from .session import Published, Refused, run_session

    def _report_progress(event: Progress) -> None:
        print(describe(event), file=sys.stderr)

    try:
        result = run_session(request, progress=_report_progress)
    except LauncherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for outcome in result.outcomes:
        if isinstance(outcome, Published):
            print(outcome.report)
            for warning in outcome.warnings:
                print(f"WARNING: {outcome.name}: {warning}", file=sys.stderr)
        elif isinstance(outcome, Refused):
            print(
                f"refusing to replace existing results: {outcome.existing}",
                file=sys.stderr,
            )
        else:
            # The union's last member: a fourth would fail to type-check here.
            print(f"ERROR: {outcome.name}: {outcome.reason}", file=sys.stderr)
            for warning in outcome.warnings:
                print(f"WARNING: {outcome.name}: {warning}", file=sys.stderr)

    published = len(result.published)
    total = len(result.outcomes)
    print(
        f"# {published} of {total} series published to {request.output_dir}",
        file=sys.stderr,
    )

    if args.open:
        open_results(result)

    return 0 if result.complete else 1
