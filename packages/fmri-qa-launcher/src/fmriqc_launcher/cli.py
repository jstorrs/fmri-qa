"""`fmri-qa-run`: one DICOM directory in, one report directory per series out.

The command-line front end over `session.run_session`. With both directories
it runs the pipeline once and reports every outcome. With neither it opens the
desktop panel (see `_launch_panel`). One directory, or any flag without both
directories, is a usage error, because the panel takes no flags.

The heavy stack (`fmriqc`'s pipeline, `fmriqc_report`'s renderer) is imported
through `.session` inside `main`, after argument parsing, so `-h`, a bad flag
and the panel path stay as cheap as parsing.
"""

import argparse
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import assert_never

from fmriqc.cli.arguments import nonnegative_float, positive_int
from fmriqc.settings import AnalysisSettings

from .exceptions import LauncherError, PanelUnavailableError, RequestError
from .outcome import Failed, Published, Refused, RunResult
from .progress import CleanupNotice, Progress, describe
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
        # Print to stdout, then exit. `parser.exit(message=...)` would use
        # stderr, which argparse's own `action="version"` never does.
        print(f"{parser.prog} {launcher_version()}")
        parser.exit()


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser for the command line this command accepts."""
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
        type=nonnegative_float,
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
        type=positive_int,
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


def _is_missing_tkinter(exc: ImportError) -> bool:
    """Check whether `exc` means `tkinter` (or `_tkinter`) is missing outright.

    `exc.name` is the module the failed import wanted: `tkinter`, a submodule
    (`tkinter.ttk`, ...), or `_tkinter`, the C extension absent from a Python
    built without Tcl/Tk. Any other name (a typo in `panel.py`, an unrelated
    missing dependency) is a real bug and must not be reported as "no tkinter".
    """
    name = exc.name or ""
    return name == "tkinter" or name.startswith(("tkinter.", "_tkinter"))


def _launch_panel() -> int:
    """Open the desktop panel, or explain on stderr why it could not start.

    `import_module` rather than `from . import panel` lets a type checker
    resolve this module on a Python built without `tkinter`. A plain import would
    have no target to find there, whereas `import_module` fails at run time the
    same way either way. Two failures get
    the same report, since the fix is the same: an `ImportError` naming
    `tkinter`/`_tkinter` (see `_is_missing_tkinter`), and `PanelUnavailableError`
    from `panel.run_panel` when `tkinter` imports but no display exists, so
    `tkinter.TclError` never reaches `cli.py`. Any other `ImportError` is a bug
    or packaging fault and propagates.
    """
    message = (
        "ERROR: the desktop panel needs tkinter with a graphical display "
        "attached, which this Python or this session does not have; pass "
        "the DICOM directory and the output directory on the command line "
        "instead.\n"
        "usage: fmri-qa-run DICOM_DIR OUTPUT_DIR [options]"
    )
    try:
        panel = import_module(f"{__package__}.panel")
    except ImportError as exc:
        if not _is_missing_tkinter(exc):
            raise
        print(message, file=sys.stderr)
        return 2
    try:
        return int(panel.run_panel())
    except PanelUnavailableError:
        print(message, file=sys.stderr)
        return 2


def _request_from(args: argparse.Namespace) -> RunRequest:
    """Build the run `args` ask for; raises `RequestError` naming every problem."""
    settings = AnalysisSettings(
        trim_sec=args.trim_sec,
        detrend=args.detrend,
        center=args.center,
        roi_size=args.roi_size,
    )
    return RunRequest(
        dicom_dir=Path(args.dicom_dir),
        output_dir=Path(args.output_dir),
        settings=settings,
        anonymize=args.anonymize,
        dcm2niix=args.dcm2niix,
        open_report=args.open,
    )


def _print_outcomes(result: RunResult, output_dir: Path) -> None:
    """Report each series: published report paths on stdout, the rest on stderr.

    Stdout carries only report paths, one per line, so the command composes;
    refusals, failures, warnings and the closing tally go to stderr.
    """
    for outcome in result.outcomes:
        match outcome:
            case Published():
                print(outcome.report)
                for warning in outcome.warnings:
                    print(f"WARNING: {outcome.name}: {warning}", file=sys.stderr)
            case Refused():
                print(
                    f"refusing to replace existing results: {outcome.existing}",
                    file=sys.stderr,
                )
            case Failed():
                print(f"ERROR: {outcome.name}: {outcome.reason}", file=sys.stderr)
                for warning in outcome.warnings:
                    print(f"WARNING: {outcome.name}: {warning}", file=sys.stderr)
            case _ as unreachable:
                assert_never(unreachable)

    published = len(result.published)
    total = len(result.outcomes)
    print(f"# {published} of {total} series published to {output_dir}", file=sys.stderr)


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
        request = _request_from(args)
    except RequestError as exc:
        for problem in exc.problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1

    # Deferred past every usage error and bad request: this import pulls in
    # scipy, scikit-image and matplotlib (see the module docstring).
    from .session import run_session

    def _report_progress(event: Progress) -> None:
        print(describe(event), file=sys.stderr)

    def _report_notice(event: CleanupNotice) -> None:
        print(f"WARNING: {event.path}: {event.message}", file=sys.stderr)

    try:
        result = run_session(request, progress=_report_progress, notice=_report_notice)
    except LauncherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _print_outcomes(result, request.output_dir)

    if args.open:
        open_results(result)

    return 0 if result.complete else 1
