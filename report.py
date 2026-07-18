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
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.25,
                          left=0.1, right=0.94, top=0.92, bottom=0.07)

    # Weisskoff plot: measured CV vs the ideal 1/N (slope -1) line
    ax = fig.add_subplot(gs[0, 0])
    ax.loglog(wk.roi_sizes, wk.cv, "o-", ms=3, label="measured")
    ideal = wk.cv[0] * wk.roi_sizes[0] / wk.roi_sizes
    ax.loglog(wk.roi_sizes, ideal, "--", color="gray", label="ideal 1/N")
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("CV")
    ax.set_title(f"Weisskoff  (RDC = {wk.rdc:.1f})", fontsize=10)
    ax.legend(fontsize=8)

    n = images.center_slice.shape[-1]
    t = np.arange(n) * images.tr
    signal = _roi_series(images.center_slice, roi)
    trend = _roi_series(images.trend, roi)
    resid = _roi_series(images.fluctuations, roi)

    ax = fig.add_subplot(gs[0, 1])
    ax.plot(t, signal, lw=0.5, label="ROI signal")
    ax.plot(t, trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=10)
    ax.legend(fontsize=8)

    ax = fig.add_subplot(gs[1, 0])
    ax.plot(t, resid, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    ax.set_title("ROI mean residual", fontsize=10)

    ax = fig.add_subplot(gs[1, 1])
    freqs = np.fft.rfftfreq(n, d=images.tr)
    mag = np.abs(np.fft.rfft(resid))
    ax.plot(freqs[1:], mag[1:], lw=0.7)  # skip DC
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    ax.set_title("residual spectrum", fontsize=10)
    return fig


def add_report_pages(pdf: PdfPages, result: "q.QAResult", title: str = "") -> None:
    """Append the two report pages for one scan to an open `PdfPages`."""
    pdf.savefig(_summary_page(result, title))
    pdf.savefig(_analysis_page(result, title))


def write_report(items, pdf_path) -> None:
    """Write a combined PDF: two pages per scan.

    `items` is an iterable of `(title, QAResult)`, or a single `QAResult`.
    """
    if isinstance(items, q.QAResult):
        items = [("", items)]
    with PdfPages(pdf_path) as pdf:
        for title, result in items:
            add_report_pages(pdf, result, title)
