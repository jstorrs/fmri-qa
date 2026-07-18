import argparse
import sys

import fmriqc as q

_AXIS_LETTER = {0: "i", 1: "j", 2: "k", None: "?"}


def _run_one(path, trim_sec, pe_axis, detrend, center, roi_size):
    scan = q.QAScan.from_nifti(path)
    metrics = q.run_qa(
        scan, trim_sec=trim_sec, pe_axis=pe_axis,
        detrend=detrend, center=center, roi_size=roi_size,
    )
    axis = pe_axis if pe_axis is not None else scan.pe_axis
    return {
        "path": path,
        "pe_axis": _AXIS_LETTER.get(axis, "?"),
        "snr": metrics.snr,
        "sfnr": metrics.sfnr,
        "rdc": metrics.rdc,
        "ghost_ratio": metrics.ghost_ratio,
    }


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
    args = parser.parse_args(argv)

    print(
        f"# detrend={args.detrend}  trim_sec={args.trim_sec}  "
        f"center={args.center}  roi_size={args.roi_size}"
    )
    header = (
        f"{'scan':40s} {'PE':>3s} "
        f"{'SNR':>9s} {'SFNR':>9s} {'RDC':>8s} {'ghost':>8s}"
    )
    print(header)
    print("-" * len(header))

    failed = False
    for path in args.paths:
        name = path.rsplit("/", 1)[-1]
        try:
            r = _run_one(
                path, args.trim_sec, args.pe_axis,
                args.detrend, args.center, args.roi_size,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            failed = True
            print(f"{name:40s} ERROR: {exc}", file=sys.stderr)
            continue
        print(
            f"{name:40s} {r['pe_axis']:>3s} "
            f"{r['snr']:>9.1f} {r['sfnr']:>9.1f} "
            f"{r['rdc']:>8.3f} {r['ghost_ratio']:>8.4f}"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
