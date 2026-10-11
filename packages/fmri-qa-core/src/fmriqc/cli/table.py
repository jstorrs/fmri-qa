"""The fixed-width metrics table: what an operator reads in the terminal.

One row per scan, aligned so a batch reads as a column of each metric. The
column comments say what each abbreviation means, since the header has no room.
The machine-readable form of the same numbers is `record`.
"""

# The `q.*` parameter annotations below name artifact types behind `fmriqc`'s
# lazy re-exports. Evaluated at `def` time, they would load the whole
# calculation stack just to import this module. Deferring them keeps `--help`
# and usage errors from importing numpy, scipy and nibabel.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import fmriqc as q


def localization_flag(m: q.Measurements) -> str:
    """Format the table's `loc` cell: `ok`, or which localization failed.

    A collapsed phantom mask or an ROI outside the phantom makes every
    mask-based number on the row a measurement of background that still looks
    ordinary. No other column shows that, so it gets a column of its own, in
    capitals, ahead of the metrics it invalidates.

    `?` is the third answer. An artifact migrated from a schema that predates
    the check carries no verdict, which is not the same as passing it.
    """
    verdicts = (("MASK", m.phantom_mask_ok), ("ROI", m.roi_inside_phantom))
    failed = [name for name, ok in verdicts if ok is False]
    if failed:
        return "+".join(failed)
    return "?" if any(ok is None for _, ok in verdicts) else "ok"


def fwhm_cell(value: float | None) -> str:
    """Format a directional FWHM cell: the number, or `?` if unmeasured.

    `fwhm_pe`/`fwhm_ro` are None when no phase-encode axis resolved, so neither
    direction has a name. The combined FWHM is not shown in their place. It is
    the geometric mean of both axes, and printing it under `fwPE` would label a
    number that answers a different question.
    """
    return "?" if value is None else f"{value:.2f}"


def clip_cell(count: int | None, *, flag: bool = False) -> str:
    """Format a clipping count cell: the number, or `?` if undeterminable.

    None means the rail test never ran, because the series did not reach the
    analysis as integer samples. Printing 0 there would report a clean scanner
    on the strength of a check that never happened.
    """
    return "?" if count is None else f"{count}{'!' if flag else ''}"


@dataclass(frozen=True)
class Column:
    """One table column: its header title, field width and how a row fills it.

    `cell` returns the unpadded text; the width and alignment are applied by
    `Column.pad`, so the header and every row share them.
    """

    title: str
    width: int
    cell: Callable[[q.QAArtifact], str]
    left: bool = False

    def pad(self, text: str) -> str:
        """Pad `text` to this column's width (right-aligned unless `left`)."""
        return f"{text:<{self.width}s}" if self.left else f"{text:>{self.width}s}"


def _clip_kept(a: q.QAArtifact) -> str:
    m = a.measurements
    return clip_cell(m.n_clipped_kept, flag=bool(m.clipped_kept))


# Each entry's comment says what the column means; the header has no room to.
COLUMNS: tuple[Column, ...] = (
    Column("scan", 40, lambda a: a.provenance.scan, left=True),
    Column("PE", 3, lambda a: a.measurements.pe_label),
    # loc: whether the phantom mask and the summary ROI landed where they must.
    # "ok", or MASK/ROI naming what failed, in which case every mask-based
    # column to its right was measured on background (see `localization_flag`).
    Column("loc", 8, lambda a: localization_flag(a.measurements)),
    Column("SNR", 9, lambda a: f"{a.measurements.snr:.1f}"),
    Column("SFNR", 9, lambda a: f"{a.measurements.sfnr:.1f}"),
    Column("RDC", 8, lambda a: f"{a.measurements.rdc:.3f}"),
    Column("drift%", 8, lambda a: f"{a.measurements.drift_pct:.3f}"),
    Column("ghost%", 8, lambda a: f"{a.measurements.ghost_pct:.3f}"),
    # ghT%: PE percent ghost of the brightest 10% of ghost voxels (Greve /
    # bxh fmriqa_ghostiness), on the same scale as ghost%. A localized bright
    # ghost that the region-mean ghost% dilutes shows here (ghT% >= ghost%
    # always).
    Column("ghT%", 8, lambda a: f"{a.measurements.ghost_top_pct:.3f}"),
    Column("RO%", 8, lambda a: f"{a.measurements.ro_ghost_pct:.3f}"),
    Column("ACRg%", 8, lambda a: f"{a.measurements.acr_ghost_pct:.3f}"),
    # outl%: worst single-frame outlier-voxel fraction (3dToutcount), using a
    # threshold tuned by qthr and the number of analyzed frames.
    Column("outl%", 7, lambda a: f"{a.measurements.outlier_max_pct:.3f}"),
    # tcOut/spcOut: cran MAD-normalized spike scores of the ROI-mean residual,
    # as peak / robust spread in the time domain (a transient volume) and on its
    # DC-dropped FFT magnitude (a dominant periodic artifact). Unitless. A clean
    # phantom sits low (a few); a spike stands well above.
    Column("tcOut", 7, lambda a: f"{a.measurements.tc_outlier:.2f}"),
    Column("spcOut", 7, lambda a: f"{a.measurements.spec_outlier:.2f}"),
    # clip: samples clipped in the analyzed data (they bias the metrics); a
    # trailing "!" flags any. clipPre: samples clipped only in the dropped
    # warm-up volumes -- reported apart because they don't reach the stats.
    # "?" in both: the series did not arrive as the scanner's integers, so the
    # rail test could not run. That is not the same as finding no clipping, so
    # it is not shown as 0 (see `Measurements`).
    Column("clip", 6, _clip_kept),
    Column("clipPre", 8, lambda a: clip_cell(a.measurements.n_clipped_pre)),
    # motn/scl%/shr%: peak per-volume in-plane phantom motion vs the temporal
    # mean (3dvolreg-style, rotation dropped). motn is translation (mm when the
    # voxel size is known, else voxels; same convention as fwPE/fwRO). scl% and
    # shr% are the gradient-heating scale/shear strain (percent).
    Column("motn", 7, lambda a: f"{a.measurements.max_translation:.3f}"),
    Column("scl%", 7, lambda a: f"{a.measurements.max_scale_pct:.3f}"),
    Column("shr%", 7, lambda a: f"{a.measurements.max_shear_pct:.3f}"),
    # com: peak per-volume shift of the whole-slice intensity centroid from its
    # temporal mean (circular COM, bxh volmeasures), in mm when the voxel size
    # is known, else voxels. The circular mean cancels uniform background and
    # the N/2 ghost, so no phantom mask is used (only a Siemens zeroed edge is
    # healed). A cheap first-moment jump/drift trace that complements motn.
    Column("com", 6, lambda a: f"{a.measurements.max_com_displacement:.3f}"),
    # fwPE/fwRO: spatial smoothness of the noise field along the phase-encode
    # and readout axes (AFNI 3dFWHMx), in mm when the voxel size is known. This
    # is the RDC smoothness confound; PE/RO asymmetry is anisotropic smoothing.
    # "?" where no PE axis resolved, so neither direction has a name (the
    # combined FWHM is not substituted; see `fwhm_cell`).
    Column("fwPE", 6, lambda a: fwhm_cell(a.measurements.fwhm_pe)),
    Column("fwRO", 6, lambda a: fwhm_cell(a.measurements.fwhm_ro)),
)


def header_lines() -> tuple[str, str]:
    """Return the fixed-width table header and its rule, as literal strings."""
    header = " ".join(c.pad(c.title) for c in COLUMNS)
    return header, "-" * len(header)


def format_row(artifact: q.QAArtifact) -> str:
    """Format one fixed-width metrics row for the human table."""
    return " ".join(c.pad(c.cell(artifact)) for c in COLUMNS)
