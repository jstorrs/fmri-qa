"""`fmri-qa-report`: render a saved artifact into a one-file HTML report.

The presentation half's entry point. It reads `.qa.nc` artifacts written by
`fmri-qa --artifact`, never a NIfTI series, so it can run on another machine,
long after the calculation, without the acquisition data.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fmriqa.analysis import InvalidArtifactError, QAArtifact
from fmriqa.path_arguments import expand_globs, same_file
from fmriqa_io.artifact import load_artifact

from .summary import package_version


def _title(artifact: QAArtifact, path: str) -> str:
    """Choose the section title for one artifact: its scan name, else the file."""
    return artifact.provenance.scan or Path(path).name


def _parser() -> argparse.ArgumentParser:
    """Build the parser for the command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-report",
        description="Render an fmri-qa analysis artifact (.qa.nc) into a "
        "single-file HTML report.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {package_version()}"
    )
    parser.add_argument(
        "artifacts",
        nargs="+",
        metavar="ARTIFACT",
        help="One analysis artifact from `fmri-qa --artifact`, or a pattern naming one",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        required=True,
        help="Write the self-contained HTML report to FILE.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Render one artifact to a self-contained HTML report; return the status."""
    parser = _parser()
    args = parser.parse_args(argv)

    # Expand patterns before the overwrite check counts them. The Windows shell
    # doesn't.
    artifacts = expand_globs(args.artifacts)
    if len(artifacts) != 1:
        parser.error("--html renders one artifact to one file")
    (path,) = artifacts

    # Refuse before reading anything, while the input is still intact.
    if same_file(args.html, path):
        print(
            f"ERROR: --html {args.html} would overwrite the input {path}",
            file=sys.stderr,
        )
        return 1

    try:
        artifact = load_artifact(path)
    except InvalidArtifactError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    from .formats.html import write_run_page

    try:
        write_run_page(artifact, args.html, title=_title(artifact, path))
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
        print(f"ERROR: could not write HTML {args.html}: {exc}", file=sys.stderr)
        return 1
    print(f"# wrote {args.html} (1 scan)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
