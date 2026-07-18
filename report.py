"""Multi-page PDF QA reports rendered from `fmriqc.QAResult` objects."""

import matplotlib

matplotlib.use("Agg")  # headless; no display needed

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

import fmriqc as q

_AXIS_LETTER = {0: "i", 1: "j", 2: "k"}


def _roi_series(arr, roi):
    """ROI-mean time series of a 3-D (X, Y, T) array."""
    return arr[roi.index].mean(axis=(0, 1))


def _draw_roi(ax, roi):
    (r, c) = roi.index
    ax.add_patch(Rectangle(
        (c.start - 0.5, r.start - 0.5), c.stop - c.start, r.stop - r.start,
        edgecolor="red", facecolor="none", lw=1.0,
    ))


def _panel(ax, img, title, *, mask=None, roi=None, log=False):
    data = np.log(np.clip(img, 1e-9, None)) if log else img
    finite = data[np.isfinite(data)]
    vmin, vmax = (np.percentile(finite, [2, 98]) if finite.size else (0, 1))
    ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax)
    if mask is not None:
        ax.contour(mask, levels=[0.5], colors="tab:cyan", linewidths=0.6)
    if roi is not None:
        _draw_roi(ax, roi)
    ax.set_title(title, fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])


def _plot_weisskoff(ax, wk, fs=10):
    """Standard Weisskoff plot: measured CV vs the ideal 1/N (slope -1) line."""
    ax.loglog(wk.roi_sizes, wk.cv, "o-", ms=3, label="measured")
    ax.loglog(wk.roi_sizes, wk.cv[0] * wk.roi_sizes[0] / wk.roi_sizes,
              "--", color="gray", label="ideal 1/N")
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("CV")
    ax.set_title(f"Weisskoff (RDC {wk.rdc:.1f})", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_rdc(ax, wk, fs=10):
    """RDC vs ROI size: pooled single-voxel CV / ROI-averaged CV, vs identity."""
    r, rdc = wk.roi_sizes, wk.rdc_curve
    ax.plot(r, r, "k-", lw=0.8, label="ideal (RDC = width)")
    ax.plot(r, rdc, "r.-", ms=4, label="measured")
    ax.axhline(float(rdc.max()), ls="--", color="gray", lw=0.8)
    ax.set_ylim(0, 1.5 * float(rdc.max()))
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("RDC")
    ax.set_title("RDC vs ROI size", fontsize=fs)
    ax.legend(fontsize=fs - 2, loc="upper left")


def _plot_signal(ax, t, signal, trend, fs=10):
    ax.plot(t, signal, lw=0.5, label="ROI signal")
    ax.plot(t, trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_residual(ax, t, resid, fs=10):
    ax.plot(t, resid, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    ax.set_title("ROI mean residual", fontsize=fs)


def _plot_spectrum(ax, resid, tr, fs=10):
    freqs = np.fft.rfftfreq(resid.size, d=tr)
    ax.plot(freqs[1:], np.abs(np.fft.rfft(resid))[1:], lw=0.7)  # skip DC
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    ax.set_title("residual spectrum", fontsize=fs)


def _summary_page(result, title):
    images, geom, roi, m = result.images, result.geom, result.roi, result.metrics
    fig = Figure(figsize=(8.5, 11))
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.98)
    gs = fig.add_gridspec(3, 2, height_ratios=[0.5, 1.0, 1.0],
                          hspace=0.3, wspace=0.15,
                          left=0.06, right=0.94, top=0.92, bottom=0.05)

    ax = fig.add_subplot(gs[0, :])
    ax.axis("off")
    pe = _AXIS_LETTER.get(images.pe_axis, "?")
    meta = (
        f"TR {images.tr:.3g} s     voxel {images.voxel_size:.3g} mm     "
        f"frames {images.center_slice.shape[-1]}     PE axis {pe}     "
        f"detrend {images.detrend_method}     "
        f"ROI {roi.size}x{roi.size} @ ({int(roi.center[0])},{int(roi.center[1])})"
    )
    metrics = (
        f"SNR {m.snr:.1f}      SFNR {m.sfnr:.1f}      RDC {m.rdc:.2f}\n"
        f"ghost {m.ghost_ratio:.4f}      drift {m.drift_pct:.3f} %      "
        f"fluctuation {m.percent_fluctuation:.3f} %"
    )
    ax.text(0.0, 0.75, meta, fontsize=9, family="monospace", va="top")
    ax.text(0.0, 0.30, metrics, fontsize=11, family="monospace", va="top")

    sfnr_img = np.where(geom.phantom_mask,
                        images.mean_image / (images.fluctuation_noise + 1e-9), 0.0)
    _panel(fig.add_subplot(gs[1, 0]), images.mean_image, "signal (temporal mean)",
           mask=geom.phantom_mask, roi=roi)
    _panel(fig.add_subplot(gs[1, 1]), sfnr_img, "SFNR", roi=roi)
    _panel(fig.add_subplot(gs[2, 0]), images.fluctuation_noise,
           "fluctuation noise (log)", mask=geom.phantom_mask, roi=roi, log=True)
    _panel(fig.add_subplot(gs[2, 1]), images.static_noise,
           "static spatial noise", mask=geom.phantom_mask, roi=roi)
    return fig


def _analysis_page(result, title):
    images, roi, wk = result.images, result.roi, result.metrics.weisskoff
    fig = Figure(figsize=(8.5, 11))
    fig.suptitle(f"{title} — stability", fontsize=13, fontweight="bold", y=0.98)
    gs = fig.add_gridspec(3, 2, hspace=0.35, wspace=0.25,
                          left=0.1, right=0.94, top=0.92, bottom=0.07)

    n = images.center_slice.shape[-1]
    t = np.arange(n) * images.tr
    signal = _roi_series(images.center_slice, roi)
    trend = _roi_series(images.trend, roi)
    resid = _roi_series(images.fluctuations, roi)

    _plot_weisskoff(fig.add_subplot(gs[0, 0]), wk)
    _plot_rdc(fig.add_subplot(gs[0, 1]), wk)
    _plot_signal(fig.add_subplot(gs[1, 0]), t, signal, trend)
    _plot_residual(fig.add_subplot(gs[1, 1]), t, resid)
    _plot_spectrum(fig.add_subplot(gs[2, :]), resid, images.tr)
    return fig


def _one_page(result, title):
    images, geom, roi, m = result.images, result.geom, result.roi, result.metrics
    wk = m.weisskoff
    fig = Figure(figsize=(8.5, 11))
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.985)
    gs = fig.add_gridspec(5, 4, height_ratios=[0.3, 0.85, 1.0, 1.0, 0.9],
                          hspace=0.55, wspace=0.4,
                          left=0.08, right=0.95, top=0.94, bottom=0.05)

    ax = fig.add_subplot(gs[0, :])
    ax.axis("off")
    pe = _AXIS_LETTER.get(images.pe_axis, "?")
    line1 = (f"TR {images.tr:.3g}s   voxel {images.voxel_size:.3g}mm   "
             f"frames {images.center_slice.shape[-1]}   PE {pe}   "
             f"detrend {images.detrend_method}   "
             f"ROI {roi.size}x{roi.size} @ ({int(roi.center[0])},{int(roi.center[1])})")
    line2 = (f"SNR {m.snr:.1f}   SFNR {m.sfnr:.1f}   RDC {m.rdc:.2f}   "
             f"ghost {m.ghost_ratio:.4f}   drift {m.drift_pct:.3f}%   "
             f"fluct {m.percent_fluctuation:.3f}%")
    ax.text(0.0, 0.75, line1, fontsize=8.5, family="monospace", va="top")
    ax.text(0.0, 0.25, line2, fontsize=10.5, family="monospace", va="top",
            fontweight="bold")

    sfnr_img = np.where(geom.phantom_mask,
                        images.mean_image / (images.fluctuation_noise + 1e-9), 0.0)
    _panel(fig.add_subplot(gs[1, 0]), images.mean_image, "signal",
           mask=geom.phantom_mask, roi=roi)
    _panel(fig.add_subplot(gs[1, 1]), sfnr_img, "SFNR", roi=roi)
    _panel(fig.add_subplot(gs[1, 2]), images.fluctuation_noise, "fluct noise (log)",
           mask=geom.phantom_mask, roi=roi, log=True)
    _panel(fig.add_subplot(gs[1, 3]), images.static_noise, "static noise",
           mask=geom.phantom_mask, roi=roi)

    n = images.center_slice.shape[-1]
    t = np.arange(n) * images.tr
    signal = _roi_series(images.center_slice, roi)
    trend = _roi_series(images.trend, roi)
    resid = _roi_series(images.fluctuations, roi)

    _plot_weisskoff(fig.add_subplot(gs[2, :2]), wk, fs=9)
    _plot_rdc(fig.add_subplot(gs[2, 2:]), wk, fs=9)
    _plot_signal(fig.add_subplot(gs[3, :2]), t, signal, trend, fs=9)
    _plot_residual(fig.add_subplot(gs[3, 2:]), t, resid, fs=9)
    _plot_spectrum(fig.add_subplot(gs[4, :]), resid, images.tr, fs=9)
    return fig


REPORT_LAYOUTS = ("one", "two")


def add_report_pages(pdf: PdfPages, result: "q.QAResult", title: str = "",
                     layout: str = "one") -> None:
    """Append a scan's report page(s) to an open `PdfPages`.

    `layout="one"` renders a single condensed page; `layout="two"` renders a
    summary page and a separate stability page.
    """
    if layout == "one":
        pdf.savefig(_one_page(result, title))
    elif layout == "two":
        pdf.savefig(_summary_page(result, title))
        pdf.savefig(_analysis_page(result, title))
    else:
        raise ValueError(f"unknown layout {layout!r}; choose from {REPORT_LAYOUTS}")


def write_report(items, pdf_path, layout: str = "one") -> None:
    """Write a combined PDF, one scan after another.

    `items` is an iterable of `(title, QAResult)`, or a single `QAResult`.
    """
    if isinstance(items, q.QAResult):
        items = [("", items)]
    with PdfPages(pdf_path) as pdf:
        for title, result in items:
            add_report_pages(pdf, result, title, layout)
