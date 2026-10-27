"""`fmri-qa-hilo`: separate thermal from instability noise on a flip-angle pair.

Greve's high/low flip-angle QA: two phantom runs differing only in flip angle,
analyzed together. It is its own command because it takes a pair of scans and
reports different numbers than the single-scan table.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import fmriqa as q
import fmriqa_io

from .arguments import (
    PrintVersion,
    attributed_warnings,
    nonnegative_float,
    nonnegative_int,
)


def _parser() -> argparse.ArgumentParser:
    """Build the parser for the command line this command accepts."""
    defaults = q.AnalysisSettings()
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
        default=defaults.trim_sec,
        help="Seconds of initial (non-steady-state) volumes to drop "
        f"(default: {defaults.trim_sec:g}).",
    )
    parser.add_argument(
        "--detrend",
        choices=q.DETREND_METHODS,
        default=defaults.detrend,
        help="Detrending method applied before the SD map "
        f"(default: {defaults.detrend}).",
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
    """Run `fmri-qa-hilo`; return the process exit status."""
    args = _parser().parse_args(argv)

    hi_name = Path(args.high).name
    lo_name = Path(args.low).name
    res: q.HiLoResult | None = None
    # The pair is analyzed together, so a warning belongs to both scans. Naming
    # them still makes the line actionable (see `print_warnings`).
    with attributed_warnings(f"{hi_name} + {lo_name}"):
        try:
            high = fmriqa_io.load_scan(args.high)
            low = fmriqa_io.load_scan(args.low)
            res = q.run_hilo(
                high,
                low,
                trim_sec=args.trim_sec,
                detrend=args.detrend,
                erode=args.erode,
            )
        except Exception as exc:  # noqa: BLE001 - report cleanly and exit non-zero
            print(f"ERROR: {exc}", file=sys.stderr)
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
