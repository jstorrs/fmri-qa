"""`fmri-qa-report`: render a saved analysis file into a one-file HTML report.

The presentation half's command, installed with this distribution. It reads
`.qa.nc` analysis files written by `fmri-qa --analysis-file`, never a NIfTI
series, so it can run on another machine, long after the calculation, without
the acquisition data.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fmriqa.analysis import InvalidAnalysisFileError, QAAnalysis
from fmriqa_io.analysis_file import load_analysis
from fmriqa_io.path_arguments import expand_globs, same_file
from fmriqa_io.rename import write_text_atomically
from fmriqa_report.summary import package_version


def _title(analysis: QAAnalysis, path: str) -> str:
    """Choose the section title for one analysis file: its scan name, else the file."""
    return analysis.provenance.scan or Path(path).name


def _parser() -> argparse.ArgumentParser:
    """Build the parser for the command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-report",
        description="Render an fmri-qa analysis file (.qa.nc) into a "
        "single-file HTML report.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {package_version()}"
    )
    parser.add_argument(
        "analyses",
        nargs="+",
        metavar="ANALYSIS_FILE",
        help="One analysis file from `fmri-qa --analysis-file`, "
        "or a pattern naming one",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        required=True,
        help="Write the self-contained HTML report to FILE.",
    )
    return parser


def report_main(argv: Sequence[str] | None = None) -> int:
    """Render one analysis file to a self-contained HTML report; return the status."""
    parser = _parser()
    args = parser.parse_args(argv)

    # Expand patterns before the overwrite check counts them. The Windows shell
    # doesn't.
    analyses = expand_globs(args.analyses)
    if len(analyses) != 1:
        parser.error("--html renders one analysis file into one page")
    (path,) = analyses

    # Refuse before reading anything, while the input is still intact.
    if same_file(args.html, path):
        print(
            f"ERROR: --html {args.html} would overwrite the input {path}",
            file=sys.stderr,
        )
        return 1

    try:
        analysis = load_analysis(path)
    except InvalidAnalysisFileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Deferred so `--help` and `--version` never import the renderer.
    from fmriqa_report.formats.html import render_run_page

    # Render before touching the destination, so a failed render leaves an
    # existing report alone and creates no directory.
    try:
        page = render_run_page(analysis, title=_title(analysis, path))
        write_text_atomically(args.html, page)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
        print(f"ERROR: could not write HTML {args.html}: {exc}", file=sys.stderr)
        return 1
    print(f"# wrote {args.html} (1 scan)")
    return 0


if __name__ == "__main__":
    raise SystemExit(report_main())
