import argparse
import sys

import fmriqc as q

_PE_LABEL = {0: "row", 1: "col", 2: "k", None: "?"}  # DICOM row/col (i->row, j->col)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fmri-qa",
        description="Phantom fMRI QA: SNR, SFNR, RDC (Weisskoff), Nyquist ghost.",
    )
    parser.add_argument("paths", nargs="+", help="NIfTI (.nii/.nii.gz) QA scans")
    parser.add_argument(
        "--trim-sec", type=float, default=5.0,
        help="Seconds of initial (non-steady-state) volumes to drop (default: 5).",
    )
    parser.add_argument(
        "--pe-axis", type=int, choices=(0, 1, 2), default=None,
        help="Override the phase-encode axis (default: read from the header).",
    )
    parser.add_argument(
        "--detrend", choices=q.DETREND_METHODS, default="poly",
        help="Detrending method (default: poly).",
    )
    parser.add_argument(
        "--center", choices=q.ROI_CENTER_MODES, default="image",
        help="Slice + ROI localization: 'image' (middle slice + image center, "
             "Glover) or 'phantom' (largest slice + detected center). Default: image.",
    )
    parser.add_argument(
        "--roi-size", type=int, default=q.FBIRN_ROI_SIZE,
        help=f"Fixed summary/Weisskoff ROI side in voxels (default: {q.FBIRN_ROI_SIZE}).",
    )
    parser.add_argument(
        "--pdf", metavar="FILE", default=None,
        help="Write a PDF report to FILE.",
    )
    parser.add_argument(
        "--pdf-layout", choices=("one", "two"), default="one",
        help="Report layout: 'one' condensed page or 'two' pages per scan "
             "(default: one).",
    )
    args = parser.parse_args(argv)

    print(
        f"# detrend={args.detrend}  trim_sec={args.trim_sec}  "
        f"center={args.center}  roi_size={args.roi_size}"
    )
    header = (
        f"{'scan':40s} {'PE':>3s} "
        f"{'SNR':>9s} {'SFNR':>9s} {'RDC':>8s} {'drift%':>8s} "
        f"{'ghost%':>8s} {'RO%':>8s} {'ACRg%':>8s} {'outl%':>7s} "
        f"{'clip':>6s} {'clipPre':>8s} {'motn':>7s} {'scl%':>7s} {'shr%':>7s}"
    )
    print(header)
    print("-" * len(header))

    failed = False
    reports = []
    for path in args.paths:
        name = path.rsplit("/", 1)[-1]
        try:
            scan = q.QAScan.from_nifti(path)
            result = q.run_qa(
                scan, trim_sec=args.trim_sec, pe_axis=args.pe_axis,
                detrend=args.detrend, center=args.center, roi_size=args.roi_size,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failed = True
            print(f"{name:40s} ERROR: {exc}", file=sys.stderr)
            continue
        m = result.metrics
        # Prefer the sidecar's DICOM row/col; fall back to the axis mapping.
        if args.pe_axis is None and result.meta and result.meta.pe_dir:
            pe = result.meta.pe_dir
        else:
            axis = args.pe_axis if args.pe_axis is not None else scan.pe_axis
            pe = _PE_LABEL.get(axis, "?")
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
        print(
            f"{name:40s} {pe:>3s} "
            f"{m.snr:>9.1f} {m.sfnr:>9.1f} {m.rdc:>8.3f} "
            f"{m.drift_pct:>8.3f} {m.ghost_pct:>8.3f} {m.ro_ghost_pct:>8.3f} "
            f"{m.acr_ghost_pct:>8.3f} {outl:>7.3f} {clip:>6s} {sat.n_clipped_pre:>8d} "
            f"{mo.max_translation:>7.3f} {mo.max_scale_pct:>7.3f} {mo.max_shear_pct:>7.3f}"
        )
        reports.append((name, result))

    if args.pdf and reports:
        from . import report as report_mod

        report_mod.write_report(reports, args.pdf, layout=args.pdf_layout)
        pages = len(reports) * (1 if args.pdf_layout == "one" else 2)
        print(f"# wrote {args.pdf} ({len(reports)} scan(s), {pages} pages)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
