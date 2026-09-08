"""Stability plots: Weisskoff/RDC, signal, residual, spectrum, outliers, motion.

Each `plot_*` draws one stability panel onto a matplotlib `Axes` from the
artifact's `Curves` — every trace arrives precomputed, so these functions only
choose colors, labels, and limits. `plot_fig` wraps a draw callback into a
fresh `Figure`. Format-agnostic — a driver embeds the figures.
"""

from collections.abc import Callable

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fmriqc.analysis import Curves, PsfCurves, WeisskoffCurve
from fmriqc.types import FloatArray


def plot_fig(draw: Callable[[Axes], object], figsize: tuple[float, float]) -> Figure:
    """Run an ax-drawing callback on a fresh constrained-layout figure."""
    fig = Figure(figsize=figsize, layout="constrained")
    draw(fig.add_subplot(111))
    return fig


def plot_weisskoff(ax: Axes, wk: WeisskoffCurve, rdc: float, fs: int = 9) -> None:
    """Measured CV vs the ideal slope=-1 line, anchored at the pooled cv1.

    The ideal line is anchored at `cv1_pooled` (the single-voxel CV pooled over
    the whole ROI) rather than at the single-voxel `cv[0]`, which makes the
    graphical RDC — where the measured plateau meets this line — equal the
    reported RDC, and is robust to the intensity non-uniformity that biases a
    single-voxel anchor. The artifact carries the anchored line as `cv_ideal`.
    """
    # Measured data on top (zorder), but first in the legend (call order).
    ax.loglog(wk.roi_sizes, wk.cv, "o-", ms=3, label="measured", zorder=3)
    ax.loglog(
        wk.roi_sizes,
        wk.cv_ideal,
        "--",
        color="gray",
        label="ideal (pooled cv1)",
        zorder=2,
    )
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("CV")
    ax.set_title(f"Weisskoff (RDC {rdc:.1f})", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def plot_rdc(ax: Axes, wk: WeisskoffCurve, fs: int = 9) -> None:
    """RDC vs ROI size: pooled single-voxel CV / ROI-averaged CV, vs identity."""
    r, rdc = wk.roi_sizes, wk.rdc
    # Match the Weisskoff plot: measured is C0/"o-" on top and first in the
    # legend; the ideal reference is a gray dashed line beneath it.
    ax.plot(r, rdc, "o-", ms=3, label="measured", zorder=3)
    ax.plot(r, r, "--", color="gray", label="ideal (RDC = width)", zorder=2)
    ax.axhline(float(rdc.max()), ls="--", color="gray", lw=0.8, zorder=1)
    ax.set_ylim(0, 1.5 * float(rdc.max()))
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("RDC")
    ax.set_title("RDC vs ROI size", fontsize=fs)
    ax.legend(fontsize=fs - 2, loc="upper left")


def plot_signal(ax: Axes, curves: Curves, fs: int = 9) -> None:
    ax.plot(curves.time, curves.roi_signal, lw=0.5, label="ROI signal")
    ax.plot(curves.time, curves.roi_trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def plot_residual(
    ax: Axes, curves: Curves, fs: int = 9, tc_outlier: float | None = None
) -> None:
    """ROI-mean detrended residual; the title carries the cran `tc_outlier` score.

    `tc_outlier` (max|residual| / MAD) is the peak-to-spread ratio of exactly this
    series, so a lone volume standing far off the baseline is both visible here and
    quantified in the title.
    """
    ax.plot(curves.time, curves.roi_residual, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    title = "ROI mean residual"
    if tc_outlier is not None:
        title += f" (tcOut {tc_outlier:.1f})"
    ax.set_title(title, fontsize=fs)


def plot_outliers(ax: Axes, curves: Curves, fs: int = 9) -> None:
    """Per-TR outlier-voxel fraction (3dToutcount) with the chance-level line.

    A clean run hovers near `outlier_qthr` (the per-voxel chance fraction,
    dashed); a frame standing well above it flags a bad volume.
    """
    ax.plot(curves.time, 100.0 * curves.outlier_fraction, lw=0.7)
    ax.axhline(
        100.0 * curves.outlier_qthr, color="gray", ls="--", lw=0.6, label="chance"
    )
    ax.set_xlabel("time (s)")
    ax.set_ylabel("outliers (%)")
    ax.set_title("outlier fraction", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def plot_motion(ax: Axes, curves: Curves, fs: int = 9) -> None:
    """Per-volume in-plane phantom motion: translation (voxels) + strain (%).

    3dvolreg-style registration to the temporal mean with the rotation dropped
    (a rigid phantom cannot rotate). Translation drifts on the left axis; the
    scaling/shear strain -- the gradient-heating signature -- shares a right axis
    in percent. A stable phantom stays flat near zero; a slow ramp is thermal.
    """
    t = curves.time
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(t, curves.translation[:, 0], lw=0.7, color="tab:blue", label="trans0")
    ax.plot(t, curves.translation[:, 1], lw=0.7, color="tab:cyan", label="trans1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("translation (vox)")
    ax.set_title("in-plane motion", fontsize=fs)
    valid = (
        np.isfinite(curves.translation).all(axis=1)
        & np.isfinite(curves.scale_pct).all(axis=1)
        & np.isfinite(curves.shear_pct)
    )
    if not valid.all():
        ax.text(
            0.98,
            0.02,
            f"{int((~valid).sum())}/{t.size} frames unresolved",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=fs - 2,
        )
    ax2 = ax.twinx()
    ax2.plot(t, curves.scale_pct[:, 0], lw=0.7, color="tab:red", label="scale0")
    ax2.plot(t, curves.scale_pct[:, 1], lw=0.7, color="tab:orange", label="scale1")
    ax2.plot(t, curves.shear_pct, lw=0.7, color="tab:green", label="shear")
    ax2.set_ylabel("strain (%)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=fs - 4, ncol=2, loc="upper left")


def plot_com(ax: Axes, curves: Curves, fs: int = 9) -> None:
    """Per-volume phantom center-of-mass shift from the temporal mean (voxels).

    Circular intensity centroid (bxh volmeasures) along each in-plane axis,
    plotted as its signed deviation from the run's mean centroid. A rigid, stable
    phantom stays flat near zero; a slow ramp is drift and a spike is a transient
    jump -- gross first-moment instability the ROI summaries miss. Complements the
    registration-based in-plane motion plot.
    """
    dev = curves.com_deviation
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(curves.time, dev[:, 0], lw=0.7, color="tab:blue", label="com0")
    ax.plot(curves.time, dev[:, 1], lw=0.7, color="tab:cyan", label="com1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("COM shift (vox)")
    ax.set_title("center of mass", fontsize=fs)
    ax.legend(fontsize=fs - 2, ncol=2, loc="upper left")


def plot_spectrum(
    ax: Axes, curves: Curves, fs: int = 9, spec_outlier: float | None = None
) -> None:
    """Residual FFT magnitude (DC dropped); title carries cran `spec_outlier`.

    `spec_outlier` (max magnitude / MAD) is the peak-to-spread ratio of exactly
    this DC-dropped spectrum, so a dominant periodic artifact shows as a spike here
    and as a large number in the title.
    """
    ax.plot(curves.spectrum_hz, curves.spectrum_magnitude, lw=0.7)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    title = "residual spectrum"
    if spec_outlier is not None:
        title += f" (spec {spec_outlier:.1f})"
    ax.set_title(title, fontsize=fs)


def plot_psf(ax: Axes, psf: PsfCurves, fs: int = 9) -> None:
    """Directional point-spread profiles (PE, RO) of the noise field (3dFWHMx).

    Markers are the empirical PSF (the squared spatial autocorrelation of the
    detrended noise field at each lag -- the point spread implied by the data
    under the Gaussian random-field model); the line is the Gaussian PSF whose
    FWHM is the Classic first-difference estimate for that axis. PE/RO asymmetry,
    or empirical points falling off the Gaussian, flag anisotropic or non-Gaussian
    reconstruction smoothing. The analysis fixes `xmax` -- a few FWHM, so a narrow
    PSF isn't squashed by the full lag range -- and the empirical points are
    clipped to it here.
    """
    colors = ("tab:blue", "tab:orange")
    for i, (label, color) in enumerate(zip(psf.labels, colors, strict=True)):
        ax.plot(
            psf.model_x[i],
            psf.model[i],
            "-",
            color=color,
            lw=1.1,
            label=f"{label} {psf.fwhm[i]:.2f}{psf.unit}",
        )
        x: FloatArray = psf.displacement[i]
        visible = x <= psf.xmax
        ax.plot(x[visible], psf.empirical[i][visible], "o", ms=3, color=color)
    ax.set_xlim(0, psf.xmax)
    ax.set_ylim(0, 1.03)
    ax.set_xlabel(f"displacement ({psf.unit})")
    ax.set_ylabel("PSF")
    ax.set_title("PSF (PE / RO)", fontsize=fs)
    ax.legend(fontsize=fs - 2)
