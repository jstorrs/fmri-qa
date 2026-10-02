"""`fmri-qa`: analyze one or more series and report the metrics.

Reads NIfTI scans, runs the pipeline on each, and prints either the fixed-width
table (`table`) or a JSON document (`record`), optionally saving each run's
`QAArtifact` (`destinations`). A batch keeps going after a failed scan and
reports every failure at the end, so one bad file does not cost the rest.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import fmriqc as q
from fmriqc.path_arguments import expand_globs

from .arguments import (
    PrintVersion,
    attributed_warnings,
    nonempty,
    nonnegative_float,
    positive_int,
)
from .destinations import (
    ARTIFACT_SUFFIX,
    artifact_destinations,
    report_destination_problems,
    write_artifact,
)
from .record import JSON_SCHEMA_VERSION, config_record, metric_record
from .table import format_row, header_lines


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa",
        description="Phantom fMRI QA: SNR, SFNR, RDC (Weisskoff), Nyquist ghost.",
    )
    # `action="version"` would need the string built here, and reading
    # `q.core_version` is what drags the whole calculation stack in before
    # argparse has looked at a single flag (see `fmriqc.__init__`). Resolve it
    # when the flag is actually used instead, so `--help` and a usage error
    # stay as cheap as parsing.
    parser.add_argument("--version", action=PrintVersion, nargs=0)
    parser.add_argument("paths", nargs="+", help="NIfTI (.nii/.nii.gz) QA scans")
    # Every analysis default is read off the record `main` goes on to build, so
    # a bare `fmri-qa scan` and a bare `q.analyze(scan)` are the same run and the
    # help text cannot name a default the command does not use.
    defaults = q.AnalysisSettings()
    parser.add_argument(
        "--trim-sec",
        type=nonnegative_float,
        default=defaults.trim_sec,
        help="Seconds of initial (non-steady-state) volumes to drop "
        f"(default: {defaults.trim_sec:g}).",
    )
    parser.add_argument(
        "--pe-axis",
        type=int,
        choices=q.PE_AXES,
        default=defaults.pe_axis_override,
        help="Override the in-plane phase-encode axis (default: read from the header).",
    )
    parser.add_argument(
        "--detrend",
        choices=q.DETREND_METHODS,
        default=defaults.detrend,
        help=f"Detrending method (default: {defaults.detrend}).",
    )
    parser.add_argument(
        "--center",
        choices=q.ROI_CENTER_MODES,
        default=defaults.center,
        help="Slice + ROI localization: 'image' (middle slice + image center, "
        "Glover) or 'phantom' (largest slice + detected center). "
        f"Default: {defaults.center}.",
    )
    parser.add_argument(
        "--roi-size",
        type=positive_int,
        default=defaults.roi_size,
        help="Fixed summary/Weisskoff ROI side in voxels "
        f"(default: {defaults.roi_size}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the metrics as JSON on stdout instead of the text table "
        "(informational lines move to stderr).",
    )
    parser.add_argument(
        "--artifact",
        type=nonempty,
        metavar="PATH",
        default=None,
        help="Save the full analysis artifact (settings, provenance, curves, "
        "images) for later reporting. With one scan PATH is the output file, "
        "unless it is a directory that already exists; with several, or into "
        f"an existing directory, it takes one <scan>{ARTIFACT_SUFFIX} per "
        "scan. Render one with `fmri-qa-report`.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Before anything counts the scans: on Windows the wildcard is still here.
    args.paths = expand_globs(args.paths)

    # Resolved once, up front: the check that clears a destination and the
    # write that uses it are handed the same `Path`, so they cannot disagree.
    # A duplicated input maps to one destination here, but such a run has
    # already been refused below, so nothing is lost collapsing it.
    destinations: dict[str, Path] = {}
    if args.artifact:
        pairs = artifact_destinations(args.artifact, args.paths)
        # Refuse before analyzing anything: a destination that lands on an
        # input or on another scan's artifact would silently discard a
        # completed analysis or the data it came from, so it is a usage
        # error, not a per-scan failure.
        if report_destination_problems(pairs):
            return 1
        destinations = dict(pairs)

    settings = q.AnalysisSettings(
        trim_sec=args.trim_sec,
        detrend=args.detrend,
        center=args.center,
        roi_size=args.roi_size,
        pe_axis_override=args.pe_axis,
    )
    # In --json mode stdout carries only the JSON document; the config banner,
    # table, and save notices go to stderr so a consumer can pipe stdout cleanly.
    info = sys.stderr if args.json else sys.stdout
    print(
        f"# detrend={settings.detrend}  trim_sec={settings.trim_sec}  "
        f"center={settings.center}  roi_size={settings.roi_size}",
        file=info,
    )
    if not args.json:
        header, rule = header_lines()
        print(header)
        print(rule)

    # Every per-scan failure, kept as well as printed: the JSON document lists
    # them beside the scans that ran, so a consumer holding only the output can
    # tell an omitted scan from one that was never requested.
    errors: list[dict[str, str]] = []
    records = []
    for path in args.paths:
        name = Path(path).name
        artifact: q.QAArtifact | None = None
        # The attempt's own ERROR line prints inside the manager, so it comes
        # first; a scan that failed may well have warned on the way down, and
        # that warning is part of the diagnosis.
        with attributed_warnings(name):
            try:
                scan = q.QAScan.from_nifti(path)
                artifact = q.analyze(scan, settings, name=name, source=str(path))
            except Exception as exc:  # noqa: BLE001 - report and continue the batch
                errors.append({"scan": name, "source": str(path), "error": str(exc)})
                print(f"{name:40s} ERROR: {exc}", file=sys.stderr)
        if artifact is None:
            continue
        if args.json:
            records.append(metric_record(artifact))
        else:
            print(format_row(artifact))
        if args.artifact:
            problem = write_artifact(artifact, destinations[path], info)
            if problem:
                errors.append({"scan": name, "source": str(path), "error": problem})

    if args.json:
        document = {
            "schema_version": JSON_SCHEMA_VERSION,
            "config": config_record(settings),
            "requested": list(args.paths),
            "scans": records,
            "errors": errors,
        }
        json.dump(document, sys.stdout, indent=2, allow_nan=False)
        print()
    if errors:
        names = ", ".join(sorted({e["scan"] for e in errors}))
        print(
            f"# {len(errors)} of {len(args.paths)} scan(s) failed: {names}",
            file=sys.stderr,
        )

    return 1 if errors else 0
