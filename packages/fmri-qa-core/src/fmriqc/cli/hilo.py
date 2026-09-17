"""`fmri-qa-hilo`: separate thermal from instability noise on a flip-angle pair.

Greve's high/low flip-angle QA: two phantom runs differing only in flip angle,
analyzed together. Its own command because it takes a *pair* of scans and
reports a different set of numbers than the single-scan table.
"""

import argparse
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

import fmriqc as q

from .arguments import PrintVersion, nonnegative_float, nonnegative_int, print_warnings


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-hilo",
        description="High/low flip-angle phantom QA: separate thermal from "
        "instability noise (Greve). Pass the HIGH-flip scan first.",
    )
    parser.add_argument("--version", action=PrintVersion, nargs=0)
    parser.add_argument("high", help="High-flip-angle NIfTI (.nii/.nii.gz) QA scan")
    parser.add_argument("low", help="Low-flip-angle NIfTI (.nii/.nii.gz) QA scan")
    parser.add_argument(
        "--trim-sec",
        type=nonnegative_float,
        default=5.0,
        help="Seconds of initial (non-steady-state) volumes to drop (default: 5).",
    )
    parser.add_argument(
        "--detrend",
        choices=q.DETREND_METHODS,
        default="poly",
        help="Detrending method applied before the SD map (default: poly).",
    )
    parser.add_argument(
        "--erode",
        type=nonnegative_int,
        default=q.HILO_ERODE,
        help=f"Voxel layers peeled off the phantom for the core mask "
        f"(default: {q.HILO_ERODE}).",
    )
    return parser


def hilo_main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    hi_name = Path(args.high).name
    lo_name = Path(args.low).name
    res: q.HiLoResult | None = None
    # The pair is analyzed together, so a warning belongs to both scans; naming
    # them is still the difference between an actionable line and one that only
    # names a source file inside this package (see `print_warnings`).
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            high = q.QAScan.from_nifti(args.high)
            low = q.QAScan.from_nifti(args.low)
            res = q.run_hilo(
                high,
                low,
                trim_sec=args.trim_sec,
                detrend=args.detrend,
                erode=args.erode,
            )
        except Exception as exc:  # noqa: BLE001 - report cleanly and exit non-zero
            print(f"ERROR: {exc}", file=sys.stderr)
    print_warnings(caught, f"{hi_name} + {lo_name}")
    if res is None:
        return 1

    hi_flip = f" (flip {res.flip_high:g})" if res.flip_high is not None else ""
    lo_flip = f" (flip {res.flip_low:g})" if res.flip_low is not None else ""
    print("# hi/lo flip-angle thermal/instability noise separation (Greve)")
    print(f"# high = {hi_name}{hi_flip}")
    print(f"# low  = {lo_name}{lo_flip}")
    note = "   [instability<0: var_low fallback]" if res.fell_back else ""
    print(f"# core voxels = {res.n_voxels}{note}")
    rows = (
        ("ThermalFSNR", res.thermal_fsnr),
        ("InstabilityFSNR", res.instability_fsnr),
        ("MeanHigh", res.mean_high),
        ("MeanLow", res.mean_low),
        ("VarHigh", res.var_high),
        ("VarLow", res.var_low),
        ("ThermalVar", res.thermal_var),
        ("InstabilityVar", res.instability_var),
        ("M", res.m),
        ("InstabilityFraction", res.instability_fraction),
    )
    for name, val in rows:
        print(f"{name:20s} {val:14.4f}")
    return 0
