"""Stability plots: Weisskoff/RDC, signal, residual, spectrum, outliers, motion.

Each `_plot_*` draws one stability panel onto a matplotlib `Axes`; `_plot_fig`
wraps a draw callback into a fresh `Figure`, and `_timeseries` extracts the
ROI-mean series the plots share. Format-agnostic — a driver embeds the figures.
"""

from collections.abc import Callable

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

import fmriqc as q
from fmriqc.types import FloatArray


def _roi_series(arr: FloatArray, roi: q.ROI) -> FloatArray:
    """ROI-mean time series of a 3-D (X, Y, T) array."""
    return np.asarray(arr[roi.index].mean(axis=(0, 1)), dtype=np.float64)


def _timeseries(
    result: q.QAResult,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    images, roi = result.images, result.roi
    n = images.center_slice.shape[-1]
    t = np.asarray(np.arange(n) * images.tr, dtype=np.float64)
    return (
        t,
        _roi_series(images.center_slice, roi),
        _roi_series(images.trend, roi),
        _roi_series(images.fluctuations, roi),
    )


def _plot_fig(draw: Callable[[Axes], object], figsize: tuple[float, float]) -> Figure:
    """Run an ax-drawing callback on a fresh constrained-layout figure."""
    fig = Figure(figsize=figsize, layout="constrained")
    draw(fig.add_subplot(111))
    return fig


def _plot_weisskoff(ax: Axes, wk: q.WeisskoffResult, fs: int = 9) -> None:
    """Measured CV vs the ideal slope=-1 line, anchored at the pooled cv1.

    Anchoring the ideal line at `cv1_pooled` (the single-voxel CV pooled over the
    whole ROI) rather than at the single-voxel `cv[0]` makes the graphical RDC —
    where the measured plateau meets this line — equal the reported RDC, and is
    robust to the intensity non-uniformity that biases a single-voxel anchor.
    """
    # Measured data on top (zorder), but first in the legend (call order).
    ax.loglog(wk.roi_sizes, wk.cv, "o-", ms=3, label="measured", zorder=3)
    ax.loglog(
        wk.roi_sizes,
        wk.cv1_pooled / wk.roi_sizes,
        "--",
        color="gray",
        label="ideal (pooled cv1)",
        zorder=2,
    )
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("CV")
    ax.set_title(f"Weisskoff (RDC {wk.rdc:.1f})", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_rdc(ax: Axes, wk: q.WeisskoffResult, fs: int = 9) -> None:
    """RDC vs ROI size: pooled single-voxel CV / ROI-averaged CV, vs identity."""
    r, rdc = wk.roi_sizes, wk.rdc_curve
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


def _plot_signal(
    ax: Axes, t: FloatArray, signal: FloatArray, trend: FloatArray, fs: int = 9
) -> None:
    ax.plot(t, signal, lw=0.5, label="ROI signal")
    ax.plot(t, trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_residual(
    ax: Axes,
    t: FloatArray,
    resid: FloatArray,
    fs: int = 9,
    tc_outlier: float | None = None,
) -> None:
    """ROI-mean detrended residual; the title carries the cran `tc_outlier` score.

    `tc_outlier` (max|residual| / MAD) is the peak-to-spread ratio of exactly this
    series, so a lone volume standing far off the baseline is both visible here and
    quantified in the title.
    """
    ax.plot(t, resid, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    title = "ROI mean residual"
    if tc_outlier is not None:
        title += f" (tcOut {tc_outlier:.1f})"
    ax.set_title(title, fontsize=fs)


def _plot_outliers(ax: Axes, t: FloatArray, outl: q.OutlierResult, fs: int = 9) -> None:
    """Per-TR outlier-voxel fraction (3dToutcount) with the chance-level line.

    A clean run hovers near `qthr` (the per-voxel chance fraction, dashed); a
    frame standing well above it flags a bad volume.
    """
    ax.plot(t, 100.0 * outl.fraction, lw=0.7)
    ax.axhline(100.0 * outl.qthr, color="gray", ls="--", lw=0.6, label="chance")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("outliers (%)")
    ax.set_title("outlier fraction", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_motion(ax: Axes, t: FloatArray, motion: q.MotionResult, fs: int = 9) -> None:
    """Per-volume in-plane phantom motion: translation (voxels) + strain (%).

    3dvolreg-style registration to the temporal mean with the rotation dropped
    (a rigid phantom cannot rotate). Translation drifts on the left axis; the
    scaling/shear strain -- the gradient-heating signature -- shares a right axis
    in percent. A stable phantom stays flat near zero; a slow ramp is thermal.
    """
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(t, motion.translation[:, 0], lw=0.7, color="tab:blue", label="trans0")
    ax.plot(t, motion.translation[:, 1], lw=0.7, color="tab:cyan", label="trans1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("translation (vox)")
    ax.set_title("in-plane motion", fontsize=fs)
    ax2 = ax.twinx()
    ax2.plot(t, motion.scale_pct[:, 0], lw=0.7, color="tab:red", label="scale0")
    ax2.plot(t, motion.scale_pct[:, 1], lw=0.7, color="tab:orange", label="scale1")
    ax2.plot(t, motion.shear_pct, lw=0.7, color="tab:green", label="shear")
    ax2.set_ylabel("strain (%)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=fs - 4, ncol=2, loc="upper left")


def _plot_com(ax: Axes, t: FloatArray, com: q.CenterOfMassResult, fs: int = 9) -> None:
    """Per-volume phantom center-of-mass shift from the temporal mean (voxels).

    Circular intensity centroid (bxh volmeasures) along each in-plane axis,
    plotted as its signed deviation from the run's mean centroid. A rigid, stable
    phantom stays flat near zero; a slow ramp is drift and a spike is a transient
    jump -- gross first-moment instability the ROI summaries miss. Complements the
    registration-based in-plane motion plot.
    """
    dev = com.deviation
    ax.axhline(0, color="gray", lw=0.5)
    ax.plot(t, dev[:, 0], lw=0.7, color="tab:blue", label="com0")
    ax.plot(t, dev[:, 1], lw=0.7, color="tab:cyan", label="com1")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("COM shift (vox)")
    ax.set_title("center of mass", fontsize=fs)
    ax.legend(fontsize=fs - 2, ncol=2, loc="upper left")


def _plot_spectrum(
    ax: Axes,
    resid: FloatArray,
    tr: float,
    fs: int = 9,
    spec_outlier: float | None = None,
) -> None:
    """Residual FFT magnitude (DC dropped); title carries cran `spec_outlier`.

    `spec_outlier` (max magnitude / MAD) is the peak-to-spread ratio of exactly
    this DC-dropped spectrum, so a dominant periodic artifact shows as a spike here
    and as a large number in the title.
    """
    freqs = np.fft.rfftfreq(resid.size, d=tr)
    ax.plot(freqs[1:], np.abs(np.fft.rfft(resid))[1:], lw=0.7)  # skip DC
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    title = "residual spectrum"
    if spec_outlier is not None:
        title += f" (spec {spec_outlier:.1f})"
    ax.set_title(title, fontsize=fs)


def _plot_psf(ax: Axes, s: q.SmoothnessResult, fs: int = 9) -> None:
    """Directional point-spread profiles (PE, RO) of the noise field (3dFWHMx).

    Markers are the empirical PSF (the squared spatial autocorrelation of the
    detrended noise field at each lag -- the point spread implied by the data
    under the Gaussian random-field model); the line is the Gaussian PSF whose
    FWHM is the Classic first-difference estimate for that axis. PE/RO asymmetry,
    or empirical points falling off the Gaussian, flag anisotropic or non-Gaussian
    reconstruction smoothing.
    """
    unit = "mm" if s.voxel_mm is not None else "vox"
    if s.pe_axis is not None:
        # ro_axis == 1 - pe_axis; spell it out so both entries are concrete ints.
        dirs = [("PE", s.pe_axis, "tab:blue"), ("RO", 1 - s.pe_axis, "tab:orange")]
    else:  # no PE axis resolved -- fall back to raw array axes
        dirs = [("axis0", 0, "tab:blue"), ("axis1", 1, "tab:orange")]
    # Zoom to a few FWHM (but at least 3 voxels), so a narrow PSF isn't squashed
    # by the full lag range -- coarse voxels decorrelate within ~1 voxel.
    xmax = max(max(2.6 * s.fwhm_axis(a), 3.0 * s._mm_per(a)) for _, a, _ in dirs)
    for name, axis, color in dirs:
        x = s.displacement(axis)
        fw = s.fwhm_axis(axis)
        xs = np.linspace(0.0, xmax, 100)
        ax.plot(
            xs,
            s.psf_model(xs, axis),
            "-",
            color=color,
            lw=1.1,
            label=f"{name} {fw:.2f}{unit}",
        )
        vis = x <= xmax
        ax.plot(x[vis], s.psf_empirical(axis)[vis], "o", ms=3, color=color)
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, 1.03)
    ax.set_xlabel(f"displacement ({unit})")
    ax.set_ylabel("PSF")
    ax.set_title("PSF (PE / RO)", fontsize=fs)
    ax.legend(fontsize=fs - 2)
