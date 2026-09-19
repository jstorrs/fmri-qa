"""`fmri-qa-report`: render saved analysis artifacts into a PDF packet or a
single-file HTML report.

The presentation half's entry point. It reads the `.qa.nc` artifacts written by
`fmri-qa --artifact` — never a NIfTI series — so reporting is a separate step
that can run on a different machine, long after the calculation, with none of
the acquisition data at hand.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from fmriqc.analysis import InvalidArtifactError, QAArtifact, load_artifact

from .cli_shared import _expand_globs
from .document import TIERS, Tier
from .summary import package_version


def _same_file(a: str | Path, b: str | Path) -> bool:
    """Whether two paths name one file — through relative forms and links alike.

    The PDF is written by moving a finished file over its destination, and the
    artifacts are read first, so `--pdf` naming one of them would succeed and
    leave a PDF where the archive was. Existing files are compared by identity;
    a path that does not exist yet can only be compared by where it would go.
    (The calculation half's command line keeps the same rule for its own
    outputs; the report deliberately imports nothing from that side but the
    artifact.)
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
        description="Render fmri-qa analysis artifacts (.qa.nc) into a PDF "
        "report or a single-file HTML report.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {package_version()}"
    )
    parser.add_argument(
        "artifacts", nargs="+", help="Analysis artifacts from `fmri-qa --artifact`"
    )
    parser.add_argument(
        "--pdf",
        metavar="FILE",
        help="Write the PDF report to FILE.",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="Write one self-contained HTML report for one artifact to FILE.",
    )
    parser.add_argument(
        "--tier",
        choices=TIERS,
        default=None,
        help="Report depth per scan: 'dashboard' (condensed overview) or 'physics' "
        "(adds a full-size stability page, a per-metric characterization table, "
        "and a methods page) (default: dashboard). Applies only to --pdf.",
    )
    parser.add_argument(
        "--cover",
        action="store_true",
        default=None,
        help="Prepend a cover page listing the scans in the packet. Applies only "
        "to --pdf.",
    )
    parser.add_argument(
        "--appendix",
        action="store_true",
        default=None,
        help="Append a provenance page (per-scan metadata + version). Applies "
        "only to --pdf.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.pdf and not args.html:
        parser.error("one of --pdf or --html is required")

    pdf_only = [
        flag
        for flag, value in (
            ("--tier", args.tier),
            ("--cover", args.cover),
            ("--appendix", args.appendix),
        )
        if value is not None
    ]
    if args.html and not args.pdf and pdf_only:
        parser.error(f"{', '.join(pdf_only)} only apply to --pdf")
    tier: Tier = "dashboard" if args.tier is None else args.tier
    cover = bool(args.cover)
    appendix = bool(args.appendix)

    # Before the overwrite check counts them: on Windows the wildcard is here.
    args.artifacts = _expand_globs(args.artifacts)

    if args.html and len(args.artifacts) != 1:
        parser.error(
            "--html renders one artifact to one file; use fmri-qa-site for several"
        )

    # Refuse before reading anything: an output that names an input is a usage
    # error, and one that must be caught while the input is still intact.
    if _refuse_overwrites(args.pdf, args.html, args.artifacts):
        return 1

    items = []
    # The artifacts that could not be read, by file name and reason: rendered
    # into the packet itself, since whoever receives the PDF may never see this
    # terminal and must be able to tell an omitted scan from an absent one.
    omitted: list[tuple[str, str]] = []
    for path in args.artifacts:
        try:
            artifact = load_artifact(path)
        except InvalidArtifactError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            omitted.append((Path(path).name, exc.reason))
            continue
        items.append((_title(artifact, path), artifact))

    if not items:
        print("ERROR: no artifacts could be read; nothing to render", file=sys.stderr)
        return 1

    if args.pdf:
        from . import write_report

        try:
            pages = write_report(
                items,
                args.pdf,
                tier=tier,
                cover=cover,
                appendix=appendix,
                omitted=omitted,
            )
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
            print(f"ERROR: could not write PDF {args.pdf}: {exc}", file=sys.stderr)
            return 1
        print(f"# wrote {args.pdf} ({len(items)} scan(s), {pages} pages)")

    if args.html:
        from .formats.html import write_run_page

        title, artifact = items[0]
        try:
            write_run_page(artifact, args.html, title=title, site=None)
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
            print(f"ERROR: could not write HTML {args.html}: {exc}", file=sys.stderr)
            return 1
        print(f"# wrote {args.html} (1 scan)")

    if omitted:
        print(
            f"# {len(omitted)} of {len(args.artifacts)} artifact(s) could not be "
            f"read; the packet is marked incomplete and lists them as omitted",
            file=sys.stderr,
        )
    return 1 if omitted else 0


def _refuse_overwrites(
    pdf: str | None, html: str | None, artifacts: Sequence[str]
) -> bool:
    """Print and report any output that would overwrite an input or its twin."""
    refused = False
    for flag, output in (("--pdf", pdf), ("--html", html)):
        if not output:
            continue
        for path in artifacts:
            if _same_file(output, path):
                print(
                    f"ERROR: {flag} {output} would overwrite the input {path}",
                    file=sys.stderr,
                )
                refused = True
    if pdf and html and _same_file(pdf, html):
        print(
            f"ERROR: --pdf {pdf} and --html {html} would overwrite each other",
            file=sys.stderr,
        )
        refused = True
    return refused


if __name__ == "__main__":
    raise SystemExit(main())
