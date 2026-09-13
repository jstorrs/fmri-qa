"""`fmri-qa-report`: render saved analysis artifacts into a PDF packet.

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

from fmriqc.analysis import QAArtifact, load_artifact

from . import write_report
from .document import TIERS
from .summary import package_version

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


def _expand_globs(paths: Sequence[str]) -> list[str]:
    """Every path, with any wildcard pattern that named nothing expanded here.

    PowerShell and cmd do not expand a wildcard before starting the command, so
    `fmri-qa-report artifacts/*.qa.nc` -- the line the README gives -- reaches
    this process with the `*` still in it and fails as a missing artifact.

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


def _same_file(a: Path, b: Path) -> bool:
    """Whether two paths name one file — through relative forms and links alike.

    The PDF is written by moving a finished file over its destination, and the
    artifacts are read first, so `--pdf` naming one of them would succeed and
    leave a PDF where the archive was. Existing files are compared by identity;
    a path that does not exist yet can only be compared by where it would go.
    (The calculation half's command line keeps the same rule for its own
    outputs; the report deliberately imports nothing from that side but the
    artifact.)
    """
    try:
        return a.samefile(b)
    except OSError:
        return a.resolve() == b.resolve()


def _title(artifact: QAArtifact, path: str) -> str:
    """The section title for one artifact: its recorded scan name, else the file."""
    return artifact.provenance.scan or Path(path).name


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-report",
        description="Render fmri-qa analysis artifacts (.qa.nc) into a PDF report.",
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
        required=True,
        help="Write the PDF report to FILE.",
    )
    parser.add_argument(
        "--tier",
        choices=TIERS,
        default="dashboard",
        help="Report depth per scan: 'dashboard' (condensed overview) or 'physics' "
        "(adds a full-size stability page, a per-metric characterization table, "
        "and a methods page) (default: dashboard).",
    )
    parser.add_argument(
        "--cover",
        action="store_true",
        help="Prepend a cover page listing the scans in the packet.",
    )
    parser.add_argument(
        "--appendix",
        action="store_true",
        help="Append a provenance page (per-scan metadata + version).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Before the overwrite check counts them: on Windows the wildcard is here.
    args.artifacts = _expand_globs(args.artifacts)

    # Refuse before reading anything: an output that names an input is a usage
    # error, and one that must be caught while the input is still intact.
    overwritten = [a for a in args.artifacts if _same_file(Path(args.pdf), Path(a))]
    if overwritten:
        for path in overwritten:
            print(
                f"ERROR: --pdf {args.pdf} would overwrite the input {path}",
                file=sys.stderr,
            )
        return 1

    items = []
    # The artifacts that could not be read, by file name and reason: rendered
    # into the packet itself, since whoever receives the PDF may never see this
    # terminal and must be able to tell an omitted scan from an absent one.
    omitted: list[tuple[str, str]] = []
    for path in args.artifacts:
        try:
            artifact = load_artifact(path)
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            print(f"ERROR: {exc}", file=sys.stderr)
            omitted.append((Path(path).name, str(getattr(exc, "reason", exc))))
            continue
        items.append((_title(artifact, path), artifact))

    if not items:
        print("ERROR: no artifacts could be read; nothing to render", file=sys.stderr)
        return 1

    try:
        pages = write_report(
            items,
            args.pdf,
            tier=args.tier,
            cover=args.cover,
            appendix=args.appendix,
            omitted=omitted,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
        print(f"ERROR: could not write PDF {args.pdf}: {exc}", file=sys.stderr)
        return 1
    print(f"# wrote {args.pdf} ({len(items)} scan(s), {pages} pages)")
    if omitted:
        print(
            f"# {len(omitted)} of {len(args.artifacts)} artifact(s) could not be "
            f"read; the packet is marked incomplete and lists them as omitted",
            file=sys.stderr,
        )
    return 1 if omitted else 0


if __name__ == "__main__":
    raise SystemExit(main())
