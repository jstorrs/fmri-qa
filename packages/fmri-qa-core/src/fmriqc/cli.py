"""Command-line entry points for the calculation half.

`main` (`fmri-qa`) analyzes one or more series and reports the metrics as a
fixed-width table or a JSON document, optionally saving each run's full
`QAArtifact` to disk. `hilo_main` (`fmri-qa-hilo`) runs the high/low flip-angle
noise separation. Rendering an artifact into a PDF is the separate
`fmri-qa-report` distribution's job (`fmri-qa-report`), so nothing here imports
matplotlib or ReportLab.
"""

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import fmriqc as q

_JSON_SCHEMA_VERSION = 2
# Suffix for a saved artifact, so a batch's files are recognizable at a glance.
_ARTIFACT_SUFFIX = ".qa.npz"


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


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "expected an integer greater than or equal to 0"
        )
    return parsed


def _scan_stem(path: str) -> str:
    """The scan's base name with any NIfTI extension removed."""
    name = Path(path).name
    for ext in (".nii.gz", ".nii"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return Path(name).stem


def _artifact_path(base: str, path: str, batch: bool) -> Path:
    """Where one scan's artifact is written under `--artifact BASE`.

    A single-scan run writes exactly `BASE`. A batch cannot share one file, so
    `BASE` is a directory and each scan gets `<scan stem>.qa.npz` inside it.
    """
    if not batch:
        return Path(base)
    return Path(base) / f"{_scan_stem(path)}{_ARTIFACT_SUFFIX}"


def _artifact_collisions(base: str, paths: Sequence[str]) -> dict[Path, list[str]]:
    """Destinations that more than one input scan would be written to.

    A batch names each artifact by the scan's stem, so inputs from different
    directories with the same file name (`sub-01/qa.nii.gz`, `sub-02/qa.nii.gz`)
    collide. Writing them in turn would leave one file holding the last scan's
    analysis and silently drop the rest, and a later `fmri-qa-report BASE/*.npz`
    would render a packet quietly missing scans. `main` checks this up front and
    refuses rather than analyze work it cannot keep.
    """
    destinations: dict[Path, list[str]] = {}
    for path in paths:
        destinations.setdefault(_artifact_path(base, path, batch=True), []).append(path)
    return {dest: srcs for dest, srcs in destinations.items() if len(srcs) > 1}


def _localization_flag(m: q.Measurements) -> str:
    """The table's `loc` cell: `ok`, or which localization failed.

    A collapsed phantom mask or an ROI that is not inside the phantom makes every
    mask-based number on the row a measurement of background, while leaving it
    looking like an ordinary value. The table's other columns cannot show that,
    so it gets a column of its own — in capitals, ahead of the metrics it
    invalidates.
    """
    failed = [
        name
        for name, ok in (("MASK", m.phantom_mask_ok), ("ROI", m.roi_inside_phantom))
        if not ok
    ]
    return "+".join(failed) if failed else "ok"


def _metric_record(artifact: q.QAArtifact) -> dict[str, object]:
    """The scalar metrics for one scan as a JSON-serializable record.

    Mirrors the human table's columns, but as raw numbers (not the fixed-width
    formatting), so downstream tools can consume `--json` directly. The table's
    one `loc` cell is three fields here: a consumer that files these away —
    the trend database this output exists for — needs the measured fraction and
    both verdicts, not the abbreviation an operator reads.
    """
    m = artifact.measurements
    record: dict[str, object] = {
        "scan": artifact.provenance.scan,
        "pe": m.pe_label,
        "pe_axis": m.pe_axis,
        # Localization first: these say whether the rest of the row means
        # anything (see `_localization_flag`).
        "phantom_fraction": m.phantom_fraction,
        "phantom_mask_ok": m.phantom_mask_ok,
        "roi_inside_phantom": m.roi_inside_phantom,
        "snr": m.snr,
        "sfnr": m.sfnr,
        "rdc": m.rdc,
        "drift_pct": m.drift_pct,
        "ghost_pct": m.ghost_pct,
        "ghost_top_pct": m.ghost_top_pct,
        "ro_ghost_pct": m.ro_ghost_pct,
        "acr_ghost_pct": m.acr_ghost_pct,
        "outl_pct": m.outlier_max_pct,
        "tc_outlier": m.tc_outlier,
        "spec_outlier": m.spec_outlier,
        "clip": m.n_clipped_kept,
        "clip_kept": m.clipped_kept,  # any clip biases the analyzed data
        "clip_pre": m.n_clipped_pre,
        "motn": m.max_translation,
        "scl_pct": m.max_scale_pct,
        "shr_pct": m.max_shear_pct,
        "com": m.max_com_displacement,
        "fw_pe": m.fwhm_pe if m.fwhm_pe is not None else m.fwhm,
        "fw_ro": m.fwhm_ro if m.fwhm_ro is not None else m.fwhm,
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
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {q.core_version()}"
    )
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
        "(informational lines move to stderr).",
    )
    parser.add_argument(
        "--artifact",
        metavar="PATH",
        default=None,
        help="Save the full analysis artifact (settings, provenance, curves, "
        "images) for later reporting. With one scan PATH is the output file; "
        f"with several it is a directory taking one <scan>{_ARTIFACT_SUFFIX} "
        "per scan. Render one with `fmri-qa-report`.",
    )
    args = parser.parse_args(argv)

    batch = len(args.paths) > 1
    # Refuse before analyzing anything: a collision would silently discard a
    # completed analysis, so it is a usage error, not a per-scan failure.
    if args.artifact and batch:
        collisions = _artifact_collisions(args.artifact, args.paths)
        if collisions:
            for dest, sources in sorted(collisions.items()):
                print(
                    f"ERROR: {' and '.join(sources)} would both be saved as {dest}",
                    file=sys.stderr,
                )
            print(
                "ERROR: --artifact names each file after the scan, so scans "
                "sharing a name overwrite each other; rename them or analyze "
                "them in separate runs.",
                file=sys.stderr,
            )
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
        _print_header()

    failed = False
    records = []
    for path in args.paths:
        try:
            scan = q.QAScan.from_nifti(path)
            artifact = q.analyze(scan, settings, name=Path(path).name, source=str(path))
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failed = True
            print(f"{Path(path).name:40s} ERROR: {exc}", file=sys.stderr)
            continue
        if args.json:
            records.append(_metric_record(artifact))
        else:
            _print_row(artifact)
        if args.artifact and not _save(artifact, args.artifact, path, batch, info):
            failed = True

    if args.json:
        document = {
            "schema_version": _JSON_SCHEMA_VERSION,
            "config": _config(args),
            "scans": records,
        }
        json.dump(document, sys.stdout, indent=2, allow_nan=False)
        print()

    return 1 if failed else 0


def _save(
    artifact: q.QAArtifact, base: str, path: str, batch: bool, info: TextIO
) -> bool:
    """Write one artifact, reporting a failure cleanly. True if it was written."""
    out = _artifact_path(base, path, batch)
    try:
        q.save_artifact(artifact, out)
    except OSError as exc:  # a bad destination is a user error, not a crash
        print(f"ERROR: could not write artifact {out}: {exc}", file=sys.stderr)
        return False
    print(f"# wrote {out}", file=info)
    return True


def _config(args: argparse.Namespace) -> dict[str, object]:
    """The run parameters echoed into the JSON document's header."""
    return {
        "version": q.core_version(),
        "detrend": args.detrend,
        "trim_sec": args.trim_sec,
        "center": args.center,
        "roi_size": args.roi_size,
        "pe_axis_override": args.pe_axis,
    }


def _print_header() -> None:
    """Print the fixed-width table header and its rule."""
    header = (
        f"{'scan':40s} {'PE':>3s} {'loc':>8s} "
        f"{'SNR':>9s} {'SFNR':>9s} {'RDC':>8s} {'drift%':>8s} "
        f"{'ghost%':>8s} {'ghT%':>8s} {'RO%':>8s} {'ACRg%':>8s} {'outl%':>7s} "
        f"{'tcOut':>7s} {'spcOut':>7s} "
        f"{'clip':>6s} {'clipPre':>8s} {'motn':>7s} {'scl%':>7s} {'shr%':>7s} "
        f"{'com':>6s} {'fwPE':>6s} {'fwRO':>6s}"
    )
    print(header)
    print("-" * len(header))


def _print_row(artifact: q.QAArtifact) -> None:
    """Print one fixed-width metrics row for the human table."""
    m = artifact.measurements
    # loc: whether the phantom mask and the summary ROI landed where they must.
    # "ok", or MASK/ROI naming what failed -- in which case every mask-based
    # column to its right was measured on background (see `_localization_flag`).
    # ghT%: PE percent ghost of the brightest 10% of ghost voxels (Greve /
    # bxh fmriqa_ghostiness), same scale as ghost% -- a localized bright ghost
    # the region-mean ghost% dilutes shows here (ghT% >= ghost% always).
    # clip: samples clipped in the analyzed data (they bias the metrics); a
    # trailing "!" flags any. clipPre: samples clipped only in the dropped
    # warm-up volumes -- reported apart because they don't reach the stats.
    clip = f"{m.n_clipped_kept}{'!' if m.clipped_kept else ''}"
    # outl%: worst single-frame outlier-voxel fraction (3dToutcount); a clean
    # run sits near the per-voxel chance level (qthr, ~0.1%).
    # motn/scl%/shr%: peak per-volume in-plane phantom motion vs the temporal
    # mean (3dvolreg-style, rotation dropped) -- translation (voxels), and the
    # gradient-heating scale/shear strain (percent).
    # tcOut/spcOut: cran MAD-normalized spike scores of the ROI-mean residual
    # -- peak / robust spread in the time domain (a transient volume) and on
    # its DC-dropped FFT magnitude (a dominant periodic artifact). Unitless; a
    # clean phantom sits low (a few), a spike stands well above.
    # com: peak per-volume shift of the whole-slice intensity centroid from
    # its temporal mean (circular COM, bxh volmeasures), in voxels -- the
    # circular mean cancels uniform background and the N/2 ghost, so no phantom
    # mask is used (only a Siemens zeroed edge is healed); a cheap first-moment
    # jump/drift trace complementing motn.
    # fwPE/fwRO: spatial smoothness of the noise field along the phase-encode
    # and readout axes (AFNI 3dFWHMx), in mm when the voxel size is known --
    # the RDC smoothness confound; PE/RO asymmetry is anisotropic smoothing.
    fw_pe = m.fwhm_pe if m.fwhm_pe is not None else m.fwhm
    fw_ro = m.fwhm_ro if m.fwhm_ro is not None else m.fwhm
    print(
        f"{artifact.provenance.scan:40s} {m.pe_label:>3s} "
        f"{_localization_flag(m):>8s} "
        f"{m.snr:>9.1f} {m.sfnr:>9.1f} {m.rdc:>8.3f} "
        f"{m.drift_pct:>8.3f} {m.ghost_pct:>8.3f} {m.ghost_top_pct:>8.3f} "
        f"{m.ro_ghost_pct:>8.3f} {m.acr_ghost_pct:>8.3f} {m.outlier_max_pct:>7.3f} "
        f"{m.tc_outlier:>7.2f} {m.spec_outlier:>7.2f} "
        f"{clip:>6s} {m.n_clipped_pre:>8d} "
        f"{m.max_translation:>7.3f} "
        f"{m.max_scale_pct:>7.3f} {m.max_shear_pct:>7.3f} "
        f"{m.max_com_displacement:>6.3f} {fw_pe:>6.2f} {fw_ro:>6.2f}"
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
        type=_nonnegative_float,
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
        type=_nonnegative_int,
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
