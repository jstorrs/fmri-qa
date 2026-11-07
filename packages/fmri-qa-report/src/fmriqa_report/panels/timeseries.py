"""Stability plots drawn onto matplotlib axes.

Each `plot_*` (`plot_weisskoff`, `plot_rdc`, `plot_signal`, `plot_residual`,
`plot_outliers`, `plot_motion`, `plot_com`, `plot_spectrum`, `plot_psf`) draws
one stability panel onto a matplotlib `Axes` from the analysis file's `Curves`.
Every trace arrives precomputed, so these functions only choose colors, labels
and limits. `plot_fig` wraps a draw callback into a fresh `Figure` that a
format driver can embed.
"""

from collections.abc import Callable

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fmriqa.analysis import Curves, PsfCurves, WeisskoffCurve
from fmriqa.types import FloatArray

# Base font size (pt) for panel titles; legends and annotations derive from it.
_FONT_SIZE = 11


def plot_fig(draw: Callable[[Axes], object], figsize: tuple[float, float]) -> Figure:
    """Run an ax-drawing callback on a fresh constrained-layout figure."""
    fig = Figure(figsize=figsize, layout="constrained")
    draw(fig.add_subplot(111))
    return fig


def plot_weisskoff(ax: Axes, wk: WeisskoffCurve, rdc: float) -> None:
    """Plot measured CV against the ideal slope=-1 line anchored at pooled cv1.

    The ideal line is anchored at `cv1_pooled` (the single-voxel CV pooled over
    the whole ROI), not at the single-voxel `cv[0]`. That makes the graphical
    RDC, where the measured plateau meets this line, equal the reported RDC, and
    resists the intensity non-uniformity that biases a single-voxel anchor. The
    analysis file carries the line as `cv_ideal`.
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
    ax.set_title(f"Weisskoff (RDC {rdc:.1f})", fontsize=_FONT_SIZE)
    ax.legend(fontsize=_FONT_SIZE - 2)


def plot_rdc(ax: Axes, wk: WeisskoffCurve) -> None:
    """Plot RDC (pooled single-voxel CV / ROI CV) vs ROI size, with identity."""
    r, rdc = wk.roi_sizes, wk.rdc
    # Match the Weisskoff plot: measured is C0/"o-" on top and first in the
    # legend; the ideal reference is a gray dashed line beneath it.
    ax.plot(r, rdc, "o-", ms=3, label="measured", zorder=3)
    ax.plot(r, r, "--", color="gray", label="ideal (RDC = width)", zorder=2)
    valid = np.isfinite(rdc)
    maximum = float(rdc[valid].max()) if valid.any() else 0.0
    if valid.any():
        ax.axhline(maximum, ls="--", color="gray", lw=0.8, zorder=1)
    scale = maximum if maximum > 0 else max(1.0, float(r.max()))
    ax.set_ylim(0, min(1.5 * scale, np.finfo(float).max))
    if not valid.all():
        ax.text(
            0.98,
            0.02,
            f"{int((~valid).sum())}/{rdc.size} points unresolved",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=_FONT_SIZE - 2,
        )
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("RDC")
    ax.set_title("RDC vs ROI size", fontsize=_FONT_SIZE)
    ax.legend(fontsize=_FONT_SIZE - 2, loc="upper left")


def plot_signal(ax: Axes, curves: Curves) -> None:
    """Plot the ROI mean signal over time with its fitted trend."""
    ax.plot(curves.time, curves.roi_signal, lw=0.5, label="ROI signal")
    ax.plot(curves.time, curves.roi_trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=_FONT_SIZE)
    ax.legend(fontsize=_FONT_SIZE - 2)


def plot_residual(ax: Axes, curves: Curves, tc_outlier: float) -> None:
    """Plot the ROI-mean detrended residual with its cran `tc_outlier` score.

    `tc_outlier` (max|residual| / MAD) is the peak-to-spread ratio of this
    series, so a lone volume far off the baseline is visible here and quantified
    in the title.
    """
    ax.plot(curves.time, curves.roi_residual, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    ax.set_title(f"ROI mean residual (tcOut {tc_outlier:.1f})", fontsize=_FONT_SIZE)


def plot_outliers(ax: Axes, curves: Curves) -> None:
    """Plot the per-TR outlier-voxel fraction (3dToutcount) as a percentage."""
    ax.plot(curves.time, 100.0 * curves.outlier_fraction, lw=0.7)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("outliers (%)")
    ax.set_title("outlier fraction", fontsize=_FONT_SIZE)


def plot_motion(ax: Axes, curves: Curves) -> None:
    """Plot per-volume in-plane phantom motion: translation and strain.

    3dvolreg-style registration to the temporal mean, with rotation dropped
    (a rigid phantom cannot rotate). Translation is on the left axis and the
    scaling/shear strain, the gradient-heating signature, on a right axis in
    percent. A stable phantom stays flat near zero; a slow ramp is thermal.
    """
    t = curves.time
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(t, curves.translation[:, 0], lw=0.7, color="tab:blue", label="trans0")
    ax.plot(t, curves.translation[:, 1], lw=0.7, color="tab:cyan", label="trans1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("translation (vox)")
    ax.set_title("in-plane motion", fontsize=_FONT_SIZE)
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
            fontsize=_FONT_SIZE - 2,
        )
    ax2 = ax.twinx()
    ax2.plot(t, curves.scale_pct[:, 0], lw=0.7, color="tab:red", label="scale0")
    ax2.plot(t, curves.scale_pct[:, 1], lw=0.7, color="tab:orange", label="scale1")
    ax2.plot(t, curves.shear_pct, lw=0.7, color="tab:green", label="shear")
    ax2.set_ylabel("strain (%)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=_FONT_SIZE - 4, ncol=2, loc="upper left")


def plot_com(ax: Axes, curves: Curves) -> None:
    """Plot the per-volume phantom center-of-mass shift (voxels).

    Circular intensity centroid (bxh volmeasures) along each in-plane axis, as
    its signed deviation from the run's mean. A stable phantom stays flat near
    zero; a slow ramp is drift and a spike is a transient jump. Both are gross
    first-moment instabilities the ROI summaries miss. Complements the
    registration-based in-plane motion plot.
    """
    dev = curves.com_deviation
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(curves.time, dev[:, 0], lw=0.7, color="tab:blue", label="com0")
    ax.plot(curves.time, dev[:, 1], lw=0.7, color="tab:cyan", label="com1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("COM shift (vox)")
    ax.set_title("center of mass", fontsize=_FONT_SIZE)
    ax.legend(fontsize=_FONT_SIZE - 2, ncol=2, loc="upper left")


def plot_spectrum(ax: Axes, curves: Curves, spec_outlier: float) -> None:
    """Plot the residual FFT magnitude (DC dropped) with cran `spec_outlier`.

    `spec_outlier` (max magnitude / MAD) is the peak-to-spread ratio of this
    DC-dropped spectrum, so a dominant periodic artifact shows as a spike here
    and as a large number in the title.
    """
    ax.plot(curves.spectrum_hz, curves.spectrum_magnitude, lw=0.7)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    ax.set_title(f"residual spectrum (spec {spec_outlier:.1f})", fontsize=_FONT_SIZE)


def plot_psf(ax: Axes, psf: PsfCurves) -> None:
    """Plot PE and RO point-spread profiles of the noise field (3dFWHMx).

    Markers are the empirical PSF: the squared spatial autocorrelation of the
    detrended noise field at each lag, the point spread the data imply under the
    Gaussian random-field model. The line is the Gaussian PSF whose FWHM is the
    Classic first-difference estimate for that axis. PE/RO asymmetry, or
    empirical points off the Gaussian, flag anisotropic or non-Gaussian
    reconstruction smoothing. The analysis fixes `xmax` at a few FWHM so a
    narrow PSF isn't squashed, and the empirical points are clipped to it here.
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
    ax.set_title("PSF (PE / RO)", fontsize=_FONT_SIZE)
    ax.legend(fontsize=_FONT_SIZE - 2)
