"""`fmri-qa-report`: render a saved analysis artifact into a single-file HTML
report.

The presentation half's entry point. It reads the `.qa.nc` artifacts written by
`fmri-qa --artifact` — never a NIfTI series — so reporting is a separate step
that can run on a different machine, long after the calculation, with none of
the acquisition data at hand.
"""

import argparse
import glob
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from fmriqc.analysis import InvalidArtifactError, QAArtifact, load_artifact

from .summary import package_version

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


def _expand_globs(paths: Sequence[str]) -> list[str]:
    """Every path, with any wildcard pattern that named nothing expanded here.

    PowerShell and cmd do not expand a wildcard before starting the command, so
    `fmri-qa-report artifacts/*.qa.nc` reaches this process with the `*` still
    in it and fails as a missing artifact.

    A deliberate twin of `fmriqc.cli.arguments.expand_globs` rather than an
    import of it: the report package may reach into `fmriqc.analysis` and
    `fmriqc.types` and nothing else (see `tests/test_layering.py`), and a shell
    quirk on the way into a command line is not knowledge worth widening that
    seam for. Keep the two in step.
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


def _same_file(a: str | Path, b: str | Path) -> bool:
    """Whether two paths name one file — through relative forms and links alike.

    The HTML is written by moving a finished file over its destination, and the
    artifact is read first, so `--html` naming it would succeed and leave a
    report where the archive was. Existing files are compared by identity; a
    path that does not exist yet can only be compared by where it would go.
    """
    first, second = Path(a), Path(b)
    try:
        return first.samefile(second)
    except OSError:
        return first.resolve() == second.resolve()


def _title(artifact: QAArtifact, path: str) -> str:
    """The section title for one artifact: its recorded scan name, else the file."""
    return artifact.provenance.scan or Path(path).name


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
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
    parser = _parser()
    args = parser.parse_args(argv)

    # Before the overwrite check counts them: on Windows the wildcard is here.
    artifacts = _expand_globs(args.artifacts)
    if len(artifacts) != 1:
        parser.error("--html renders one artifact to one file")
    (path,) = artifacts

    # Refuse before reading anything: an output that names an input is a usage
    # error, and one that must be caught while the input is still intact.
    if _same_file(args.html, path):
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
