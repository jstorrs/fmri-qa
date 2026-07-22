import argparse
import json
import math
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import fmriqc as q

# Shared in-plane row/col labels (i->row, j->col).
_PE_LABEL = q.PE_ROWCOL
_JSON_SCHEMA_VERSION = 1


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected a finite number greater than or equal to 0"
        )
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def _version() -> str:
    try:
        return version("fmri-qa")
    except PackageNotFoundError:  # running from a source tree without an install
        return "unknown"


def _metric_record(name: str, pe: str, result: q.QAResult) -> dict[str, object]:
    """The scalar metrics for one scan as a JSON-serializable record.

    Mirrors the human table's columns one-to-one, but as raw numbers (not the
    fixed-width formatting), so downstream tools can consume `--json` directly.
    """
    m = result.metrics
    sat = m.saturation
    sm = m.smoothness
    record: dict[str, object] = {
        "scan": name,
        "pe": pe,
        "pe_axis": m.pe_axis,
        "snr": m.snr,
        "sfnr": m.sfnr,
        "rdc": m.rdc,
        "drift_pct": m.drift_pct,
        "ghost_pct": m.ghost_pct,
        "ghost_top_pct": m.ghost_top_pct,
        "ro_ghost_pct": m.ro_ghost_pct,
        "acr_ghost_pct": m.acr_ghost_pct,
        "outl_pct": 100.0 * m.outliers.max_fraction,
        "tc_outlier": m.spikes.tc_outlier,
        "spec_outlier": m.spikes.spec_outlier,
        "clip": sat.n_clipped_kept,
        "clip_kept": sat.clipped_kept,  # any clip biases the analyzed data
        "clip_pre": sat.n_clipped_pre,
        "motn": m.motion.max_translation,
        "scl_pct": m.motion.max_scale_pct,
        "shr_pct": m.motion.max_shear_pct,
        "com": m.center_of_mass.max_displacement,
        "fw_pe": sm.fwhm_pe if sm.fwhm_pe is not None else sm.fwhm,
        "fw_ro": sm.fwhm_ro if sm.fwhm_ro is not None else sm.fwhm,
    }
    # Undefined numerical metrics are JSON null, not Python's non-standard NaN
    # or Infinity tokens. This keeps stdout consumable by strict JSON parsers.
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in record.items()
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fmri-qa",
        description="Phantom fMRI QA: SNR, SFNR, RDC (Weisskoff), Nyquist ghost.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    parser.add_argument("paths", nargs="+", help="NIfTI (.nii/.nii.gz) QA scans")
    parser.add_argument(
        "--trim-sec",
        type=_nonnegative_float,
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
        type=_positive_int,
        default=q.FBIRN_ROI_SIZE,
        help=(
            f"Fixed summary/Weisskoff ROI side in voxels (default: {q.FBIRN_ROI_SIZE})."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the metrics as JSON on stdout instead of the text table "
        "(informational lines and the PDF notice move to stderr).",
    )
    parser.add_argument(
        "--pdf",
        metavar="FILE",
        default=None,
        help="Write a PDF report to FILE.",
    )
    parser.add_argument(
        "--pdf-tier",
        choices=("dashboard", "physics"),
        default="dashboard",
        help="Report depth per scan: 'dashboard' (condensed overview) or 'physics' "
        "(adds a full-size stability page) (default: dashboard).",
    )
    parser.add_argument(
        "--pdf-cover",
        action="store_true",
        help="Prepend a cover page listing the scans in the PDF packet.",
    )
    parser.add_argument(
        "--pdf-appendix",
        action="store_true",
        help="Append a provenance page (per-scan metadata + version) to the PDF.",
    )
    args = parser.parse_args(argv)

    # In --json mode stdout carries only the JSON document; the config banner,
    # table, and PDF notice go to stderr so a consumer can pipe stdout cleanly.
    info = sys.stderr if args.json else sys.stdout
    print(
        f"# detrend={args.detrend}  trim_sec={args.trim_sec}  "
        f"center={args.center}  roi_size={args.roi_size}",
        file=info,
    )
    if not args.json:
        header = (
            f"{'scan':40s} {'PE':>3s} "
            f"{'SNR':>9s} {'SFNR':>9s} {'RDC':>8s} {'drift%':>8s} "
            f"{'ghost%':>8s} {'ghT%':>8s} {'RO%':>8s} {'ACRg%':>8s} {'outl%':>7s} "
            f"{'tcOut':>7s} {'spcOut':>7s} "
            f"{'clip':>6s} {'clipPre':>8s} {'motn':>7s} {'scl%':>7s} {'shr%':>7s} "
            f"{'com':>6s} {'fwPE':>6s} {'fwRO':>6s}"
        )
        print(header)
        print("-" * len(header))

    failed = False
    reports = []
    records = []
    for path in args.paths:
        name = Path(path).name
        try:
            scan = q.QAScan.from_nifti(path)
            result = q.run_qa(
                scan,
                trim_sec=args.trim_sec,
                pe_axis=args.pe_axis,
                detrend=args.detrend,
                center=args.center,
                roi_size=args.roi_size,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failed = True
            print(f"{name:40s} ERROR: {exc}", file=sys.stderr)
            continue
        # Prefer the sidecar's DICOM row/col; fall back to the axis mapping.
        if args.pe_axis is None and result.meta and result.meta.pe_dir:
            pe = result.meta.pe_dir
        else:
            axis = args.pe_axis if args.pe_axis is not None else scan.pe_axis
            pe = "?" if axis is None else _PE_LABEL.get(axis, "?")
        reports.append((name, result))
        if args.json:
            records.append(_metric_record(name, pe, result))
        else:
            _print_row(name, pe, result)

    if args.pdf and reports:
        from . import report as report_mod

        pages = report_mod.write_report(
            reports,
            args.pdf,
            tier=args.pdf_tier,
            cover=args.pdf_cover,
            appendix=args.pdf_appendix,
        )
        print(f"# wrote {args.pdf} ({len(reports)} scan(s), {pages} pages)", file=info)

    if args.json:
        document = {
            "schema_version": _JSON_SCHEMA_VERSION,
            "config": _config(args),
            "scans": records,
        }
        json.dump(document, sys.stdout, indent=2, allow_nan=False)
        print()

    return 1 if failed else 0


def _config(args: argparse.Namespace) -> dict[str, object]:
    """The run parameters echoed into the JSON document's header."""
    return {
        "version": _version(),
        "detrend": args.detrend,
        "trim_sec": args.trim_sec,
        "center": args.center,
        "roi_size": args.roi_size,
        "pe_axis_override": args.pe_axis,
    }


def _print_row(name: str, pe: str, result: q.QAResult) -> None:
    """Print one fixed-width metrics row for the human table."""
    m = result.metrics
    # ghT%: PE percent ghost of the brightest 10% of ghost voxels (Greve /
    # bxh fmriqa_ghostiness), same scale as ghost% -- a localized bright ghost
    # the region-mean ghost% dilutes shows here (ghT% >= ghost% always).
    # clip: samples clipped in the analyzed data (they bias the metrics); a
    # trailing "!" flags any. clipPre: samples clipped only in the dropped
    # warm-up volumes -- reported apart because they don't reach the stats.
    sat = m.saturation
    clip = f"{sat.n_clipped_kept}{'!' if sat.clipped_kept else ''}"
    # outl%: worst single-frame outlier-voxel fraction (3dToutcount); a clean
    # run sits near the per-voxel chance level (qthr, ~0.1%).
    outl = 100.0 * m.outliers.max_fraction
    # motn/scl%/shr%: peak per-volume in-plane phantom motion vs the temporal
    # mean (3dvolreg-style, rotation dropped) -- translation (voxels), and the
    # gradient-heating scale/shear strain (percent).
    mo = m.motion
    # tcOut/spcOut: cran MAD-normalized spike scores of the ROI-mean residual
    # -- peak / robust spread in the time domain (a transient volume) and on
    # its DC-dropped FFT magnitude (a dominant periodic artifact). Unitless; a
    # clean phantom sits low (a few), a spike stands well above.
    sp = m.spikes
    # com: peak per-volume shift of the whole-slice intensity centroid from
    # its temporal mean (circular COM, bxh volmeasures), in voxels -- the
    # circular mean cancels uniform background and the N/2 ghost, so no phantom
    # mask is used (only a Siemens zeroed edge is healed); a cheap first-moment
    # jump/drift trace complementing motn.
    com = m.center_of_mass.max_displacement
    # fwPE/fwRO: spatial smoothness of the noise field along the phase-encode
    # and readout axes (AFNI 3dFWHMx), in mm when the voxel size is known --
    # the RDC smoothness confound; PE/RO asymmetry is anisotropic smoothing.
    sm = m.smoothness
    fw_pe = sm.fwhm_pe if sm.fwhm_pe is not None else sm.fwhm
    fw_ro = sm.fwhm_ro if sm.fwhm_ro is not None else sm.fwhm
    print(
        f"{name:40s} {pe:>3s} "
        f"{m.snr:>9.1f} {m.sfnr:>9.1f} {m.rdc:>8.3f} "
        f"{m.drift_pct:>8.3f} {m.ghost_pct:>8.3f} {m.ghost_top_pct:>8.3f} "
        f"{m.ro_ghost_pct:>8.3f} {m.acr_ghost_pct:>8.3f} {outl:>7.3f} "
        f"{sp.tc_outlier:>7.2f} {sp.spec_outlier:>7.2f} "
        f"{clip:>6s} {sat.n_clipped_pre:>8d} "
        f"{mo.max_translation:>7.3f} "
        f"{mo.max_scale_pct:>7.3f} {mo.max_shear_pct:>7.3f} "
        f"{com:>6.3f} {fw_pe:>6.2f} {fw_ro:>6.2f}"
    )


def hilo_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fmri-qa-hilo",
        description="High/low flip-angle phantom QA: separate thermal from "
        "instability noise (Greve). Pass the HIGH-flip scan first.",
    )
    parser.add_argument("high", help="High-flip-angle NIfTI (.nii/.nii.gz) QA scan")
    parser.add_argument("low", help="Low-flip-angle NIfTI (.nii/.nii.gz) QA scan")
    parser.add_argument(
        "--trim-sec",
        type=float,
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
        type=int,
        default=q.HILO_ERODE,
        help=f"Voxel layers peeled off the phantom for the core mask "
        f"(default: {q.HILO_ERODE}).",
    )
    args = parser.parse_args(argv)

    try:
        high = q.QAScan.from_nifti(args.high)
        low = q.QAScan.from_nifti(args.low)
        res = q.run_hilo(
            high, low, trim_sec=args.trim_sec, detrend=args.detrend, erode=args.erode
        )
    except Exception as exc:  # noqa: BLE001 - report cleanly and exit non-zero
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    hi_name = Path(args.high).name
    lo_name = Path(args.low).name
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


if __name__ == "__main__":
    raise SystemExit(main())
