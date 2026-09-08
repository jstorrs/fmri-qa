"""`fmri-qa`: analyze one or more series and report the metrics.

Reads NIfTI scans, runs the pipeline on each, and prints either the fixed-width
table (`table`) or a JSON document (`record`), optionally saving each run's
`QAArtifact` (`destinations`). A batch keeps going after a failed scan and
reports every failure at the end, so one bad file does not cost the rest.
"""

import argparse
import json
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

import fmriqc as q

from .arguments import nonnegative_float, positive_int, print_warnings
from .destinations import (
    ARTIFACT_SUFFIX,
    report_destination_problems,
    write_artifact,
)
from .record import JSON_SCHEMA_VERSION, config_record, metric_record
from .table import print_header, print_row


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa",
        description="Phantom fMRI QA: SNR, SFNR, RDC (Weisskoff), Nyquist ghost.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {q.core_version()}"
    )
    parser.add_argument("paths", nargs="+", help="NIfTI (.nii/.nii.gz) QA scans")
    parser.add_argument(
        "--trim-sec",
        type=nonnegative_float,
        default=5.0,
        help="Seconds of initial (non-steady-state) volumes to drop (default: 5).",
    )
    parser.add_argument(
        "--pe-axis",
        type=int,
        choices=(0, 1),
        default=None,
        help="Override the in-plane phase-encode axis (default: read from the header).",
    )
    parser.add_argument(
        "--detrend",
        choices=q.DETREND_METHODS,
        default="poly",
        help="Detrending method (default: poly).",
    )
    parser.add_argument(
        "--center",
        choices=q.ROI_CENTER_MODES,
        default="image",
        help="Slice + ROI localization: 'image' (middle slice + image center, "
        "Glover) or 'phantom' (largest slice + detected center). Default: image.",
    )
    parser.add_argument(
        "--roi-size",
        type=positive_int,
        default=q.FBIRN_ROI_SIZE,
        help=(
            f"Fixed summary/Weisskoff ROI side in voxels (default: {q.FBIRN_ROI_SIZE})."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the metrics as JSON on stdout instead of the text table "
        "(informational lines move to stderr).",
    )
    parser.add_argument(
        "--artifact",
        metavar="PATH",
        default=None,
        help="Save the full analysis artifact (settings, provenance, curves, "
        "images) for later reporting. With one scan PATH is the output file; "
        f"with several it is a directory taking one <scan>{ARTIFACT_SUFFIX} "
        "per scan. Render one with `fmri-qa-report`.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    batch = len(args.paths) > 1
    # Refuse before analyzing anything: a destination that lands on an input or
    # on another scan's artifact would silently discard a completed analysis or
    # the data it came from, so it is a usage error, not a per-scan failure.
    if args.artifact and report_destination_problems(args.artifact, args.paths):
        return 1

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
        f"# detrend={args.detrend}  trim_sec={args.trim_sec}  "
        f"center={args.center}  roi_size={args.roi_size}",
        file=info,
    )
    if not args.json:
        print_header()

    # Every per-scan failure, kept as well as printed: the JSON document lists
    # them beside the scans that ran, so a consumer holding only the output can
    # tell an omitted scan from one that was never requested.
    errors: list[dict[str, str]] = []
    records = []
    for path in args.paths:
        name = Path(path).name
        artifact: q.QAArtifact | None = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                scan = q.QAScan.from_nifti(path)
                artifact = q.analyze(scan, settings, name=name, source=str(path))
            except Exception as exc:  # noqa: BLE001 - report and continue the batch
                errors.append({"scan": name, "source": str(path), "error": str(exc)})
                print(f"{name:40s} ERROR: {exc}", file=sys.stderr)
        # After the attempt either way: a scan that failed may well have warned
        # on the way down, and that warning is part of the diagnosis.
        print_warnings(caught, name)
        if artifact is None:
            continue
        if args.json:
            records.append(metric_record(artifact))
        else:
            print_row(artifact)
        if args.artifact:
            problem = write_artifact(artifact, args.artifact, path, batch, info)
            if problem:
                errors.append({"scan": name, "source": str(path), "error": problem})

    if args.json:
        document = {
            "schema_version": JSON_SCHEMA_VERSION,
            "config": config_record(args),
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
