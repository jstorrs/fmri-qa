"""The fixed-width metrics table: what an operator reads in the terminal.

One row per scan, aligned so a batch reads as a column of each metric. The
column comments carry what each abbreviation means — the table is the primary
interface, and its header has no room to say. The machine-readable form of the
same numbers is `record`.
"""

# The `q.*` parameter annotations below name artifact types that live behind
# `fmriqc`'s lazy re-exports; evaluated at `def` time they would resolve the
# whole calculation stack just to import this module. Deferring them keeps a
# `--help` or a usage error from paying for numpy, scipy and nibabel.
from __future__ import annotations

import fmriqc as q


def localization_flag(m: q.Measurements) -> str:
    """The table's `loc` cell: `ok`, or which localization failed.

    A collapsed phantom mask or an ROI that is not inside the phantom makes every
    mask-based number on the row a measurement of background, while leaving it
    looking like an ordinary value. The table's other columns cannot show that,
    so it gets a column of its own — in capitals, ahead of the metrics it
    invalidates.

    `?` is the third answer: an artifact migrated from a schema that predates the
    check carries no verdict, which is not the same as passing it.
    """
    verdicts = (("MASK", m.phantom_mask_ok), ("ROI", m.roi_inside_phantom))
    failed = [name for name, ok in verdicts if ok is False]
    if failed:
        return "+".join(failed)
    return "?" if any(ok is None for _, ok in verdicts) else "ok"


def fwhm_cell(value: float | None) -> str:
    """One directional FWHM as a table cell: the number, or `?` if unmeasured.

    `fwhm_pe`/`fwhm_ro` are None when no phase-encode axis resolved, so neither
    direction has a name. The combined FWHM is *not* shown in their place: it is
    the geometric mean of both axes, and printing it under `fwPE` would label a
    number that answers a different question as the answer to this one.
    """
    return "?" if value is None else f"{value:.2f}"


def clip_cell(count: int | None, *, flag: bool = False) -> str:
    """One clipping count as a table cell: the number, or `?` if undeterminable.

    None means the rail test never ran, because the series did not reach the
    analysis as integer samples. Printing 0 there would report a clean scanner
    on the strength of a check that did not happen.
    """
    return "?" if count is None else f"{count}{'!' if flag else ''}"


def header_lines() -> tuple[str, str]:
    """The fixed-width table header and its rule, as literal strings."""
    header = (
        f"{'scan':40s} {'PE':>3s} {'loc':>8s} "
        f"{'SNR':>9s} {'SFNR':>9s} {'RDC':>8s} {'drift%':>8s} "
        f"{'ghost%':>8s} {'ghT%':>8s} {'RO%':>8s} {'ACRg%':>8s} {'outl%':>7s} "
        f"{'tcOut':>7s} {'spcOut':>7s} "
        f"{'clip':>6s} {'clipPre':>8s} {'motn':>7s} {'scl%':>7s} {'shr%':>7s} "
        f"{'com':>6s} {'fwPE':>6s} {'fwRO':>6s}"
    )
    return header, "-" * len(header)


def format_row(artifact: q.QAArtifact) -> str:
    """Format one fixed-width metrics row for the human table."""
    m = artifact.measurements
    # loc: whether the phantom mask and the summary ROI landed where they must.
    # "ok", or MASK/ROI naming what failed -- in which case every mask-based
    # column to its right was measured on background (see `localization_flag`).
    # ghT%: PE percent ghost of the brightest 10% of ghost voxels (Greve /
    # bxh fmriqa_ghostiness), same scale as ghost% -- a localized bright ghost
    # the region-mean ghost% dilutes shows here (ghT% >= ghost% always).
    # clip: samples clipped in the analyzed data (they bias the metrics); a
    # trailing "!" flags any. clipPre: samples clipped only in the dropped
    # warm-up volumes -- reported apart because they don't reach the stats.
    # "?" in both: the series did not arrive as the scanner's integers, so the
    # rail test could not run -- which is not the same as finding no clipping,
    # and is why it is not shown as 0 (see `Measurements`).
    clip = clip_cell(m.n_clipped_kept, flag=bool(m.clipped_kept))
    clip_pre = clip_cell(m.n_clipped_pre)
    # outl%: worst single-frame outlier-voxel fraction (3dToutcount), using a
    # threshold tuned by qthr and the number of analyzed frames.
    # motn/scl%/shr%: peak per-volume in-plane phantom motion vs the temporal
    # mean (3dvolreg-style, rotation dropped) -- translation (mm when the voxel
    # size is known, else voxels; same convention as fwPE/fwRO), and the
    # gradient-heating scale/shear strain (percent).
    # tcOut/spcOut: cran MAD-normalized spike scores of the ROI-mean residual
    # -- peak / robust spread in the time domain (a transient volume) and on
    # its DC-dropped FFT magnitude (a dominant periodic artifact). Unitless; a
    # clean phantom sits low (a few), a spike stands well above.
    # com: peak per-volume shift of the whole-slice intensity centroid from
    # its temporal mean (circular COM, bxh volmeasures), in mm when the voxel
    # size is known, else voxels -- the circular mean cancels uniform background
    # and the N/2 ghost, so no phantom mask is used (only a Siemens zeroed edge
    # is healed); a cheap first-moment jump/drift trace complementing motn.
    # fwPE/fwRO: spatial smoothness of the noise field along the phase-encode
    # and readout axes (AFNI 3dFWHMx), in mm when the voxel size is known --
    # the RDC smoothness confound; PE/RO asymmetry is anisotropic smoothing.
    # "?" where no PE axis resolved, so neither direction has a name (the
    # combined FWHM is not substituted -- see `fwhm_cell`).
    return (
        f"{artifact.provenance.scan:40s} {m.pe_label:>3s} "
        f"{localization_flag(m):>8s} "
        f"{m.snr:>9.1f} {m.sfnr:>9.1f} {m.rdc:>8.3f} "
        f"{m.drift_pct:>8.3f} {m.ghost_pct:>8.3f} {m.ghost_top_pct:>8.3f} "
        f"{m.ro_ghost_pct:>8.3f} {m.acr_ghost_pct:>8.3f} {m.outlier_max_pct:>7.3f} "
        f"{m.tc_outlier:>7.2f} {m.spec_outlier:>7.2f} "
        f"{clip:>6s} {clip_pre:>8s} "
        f"{m.max_translation:>7.3f} "
        f"{m.max_scale_pct:>7.3f} {m.max_shear_pct:>7.3f} "
        f"{m.max_com_displacement:>6.3f} "
        f"{fwhm_cell(m.fwhm_pe):>6s} {fwhm_cell(m.fwhm_ro):>6s}"
    )
