"""The ``fmri-qa-site`` command: artifacts on disk in, an offline site out."""

import argparse
import hashlib
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from fmriqc.analysis import InvalidArtifactError, QAArtifact, load_artifact

from .cli_shared import _expand_globs
from .formats.html import SiteResult, SiteStatus, write_site
from .summary import package_version
from .web_summary import OmittedInput, RenderedRun

_DISPLAY_NAME = "<unnamed input>"
_COPY_CHUNK_SIZE = 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    """Build the static-site command parser."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-site",
        description="Publish fmri-qa analysis artifacts (.qa.nc) as an offline site.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {package_version()}"
    )
    parser.add_argument(
        "artifacts", nargs="+", help="Analysis artifacts from `fmri-qa --artifact`"
    )
    parser.add_argument(
        "--output", metavar="DIRECTORY", required=True, help="Write a new site here."
    )
    return parser


def _input_name(path: str) -> str:
    """Return the portable, non-empty display name for one requested input."""
    return Path(path).name or _DISPLAY_NAME


def _snapshot_artifact(path: str, snapshots: Path) -> tuple[str, QAArtifact]:
    """Hash an exact byte snapshot, then load that same immutable snapshot."""
    snapshot = snapshots / "artifact.qa.nc"
    digest = hashlib.sha256()
    with Path(path).open("rb") as source, snapshot.open("xb") as destination:
        while chunk := source.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
            destination.write(chunk)
    return digest.hexdigest(), load_artifact(snapshot)


def _omission(path: str, reason: str) -> OmittedInput:
    """Build an inventory-safe omission without exposing temporary paths."""
    return OmittedInput(_input_name(path), reason)


def _reported_reason(reason: str, snapshot: Path | None, input_path: str) -> str:
    """Replace a private snapshot name with the input the user supplied."""
    if snapshot:
        reason = reason.replace(str(snapshot), input_path).replace(
            str(snapshot.parent), input_path
        )
    return reason


def _load_runs(paths: Sequence[str]) -> tuple[list[RenderedRun], list[OmittedInput]]:
    """Read each request through a private snapshot, retaining failed requests."""
    runs: list[RenderedRun] = []
    omitted: list[OmittedInput] = []
    for path in paths:
        snapshot: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="fmri-qa-site-") as temporary:
                snapshot_directory = Path(temporary)
                snapshot = snapshot_directory / "artifact.qa.nc"
                digest, artifact = _snapshot_artifact(path, snapshot_directory)
        except InvalidArtifactError as exc:
            omitted.append(
                _omission(
                    path,
                    _reported_reason(exc.reason, snapshot, path) or type(exc).__name__,
                )
            )
        except OSError as exc:
            omitted.append(
                _omission(
                    path,
                    _reported_reason(str(exc), snapshot, path) or type(exc).__name__,
                )
            )
        else:
            runs.append(RenderedRun(digest, artifact, (_input_name(path),)))
    return runs, omitted


def _print_result(result: SiteResult) -> None:
    """Print the request-level publication summary to stderr."""
    requested = result.successful_inputs + result.omitted_count
    duplicates = result.successful_inputs - result.successful_runs
    print(
        f"# wrote {result.output} ({requested} requested input(s), "
        f"{result.successful_runs} distinct run report(s), {duplicates} duplicate "
        f"input(s), {result.omitted_count} omitted input(s))",
        file=sys.stderr,
    )
    for omitted in result.omitted_inputs:
        print(f"ERROR: {omitted.input_name}: {omitted.reason}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Publish a fresh static site and return its command-line status."""
    args = _parser().parse_args(argv)
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        print(
            f"ERROR: refusing to replace existing report site: {output}",
            file=sys.stderr,
        )
        return 1

    try:
        paths = _expand_globs(args.artifacts)
        runs, omitted = _load_runs(paths)
        result = write_site(runs, output, omitted=omitted)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports cleanly
        print(f"ERROR: could not write report site {output}: {exc}", file=sys.stderr)
        return 1

    _print_result(result)
    return 0 if result.status is SiteStatus.COMPLETE else 1


if __name__ == "__main__":
    raise SystemExit(main())
