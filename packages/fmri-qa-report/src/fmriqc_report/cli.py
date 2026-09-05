"""`fmri-qa-report`: render saved analysis artifacts into a PDF packet.

The presentation half's entry point. It reads `.npz` artifacts written by
`fmri-qa --artifact` — never a NIfTI series — so reporting is a separate step
that can run on a different machine, long after the calculation, with none of
the acquisition data at hand.
"""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fmriqc.analysis import QAArtifact, load_artifact

from . import write_report
from .document import TIERS


def _version() -> str:
    """The installed `fmri-qa-report` version, or "unknown" from a source tree."""
    try:
        return version("fmri-qa-report")
    except PackageNotFoundError:
        return "unknown"


def _title(artifact: QAArtifact, path: str) -> str:
    """The section title for one artifact: its recorded scan name, else the file."""
    return artifact.provenance.scan or Path(path).name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fmri-qa-report",
        description="Render fmri-qa analysis artifacts (.npz) into a PDF report.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
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
    args = parser.parse_args(argv)

    failed = False
    items = []
    for path in args.artifacts:
        try:
            artifact = load_artifact(path)
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failed = True
            print(f"ERROR: {exc}", file=sys.stderr)
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
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
        print(f"ERROR: could not write PDF {args.pdf}: {exc}", file=sys.stderr)
        return 1
    print(f"# wrote {args.pdf} ({len(items)} scan(s), {pages} pages)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
