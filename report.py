"""Multi-page PDF QA reports rendered from `fmriqc.QAResult` objects.

The page layout (title, metadata, metric line, and the placement grid) is drawn
natively with ReportLab; the individual image panels and stability plots are
rendered by matplotlib as SVG and embedded as vector drawings. Keeping the
plotting in matplotlib preserves the scientific figures while letting ReportLab
own the page composition and text, and the SVG path keeps the axes, curves, and
labels as crisp vectors (the phantom images inside `imshow` remain raster, as
they inherently are).
"""

import io

import matplotlib

matplotlib.use("Agg")  # headless; no display needed

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

import fmriqc as q

_AXIS_LETTER = {0: "i", 1: "j", 2: "k"}

_PAGE_W, _PAGE_H = letter  # 612 x 792 pt
_MARGIN = 40.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN


# --------------------------------------------------------------------------- #
# matplotlib panels/plots -> embeddable vector drawings
# --------------------------------------------------------------------------- #

def _draw_fig(c, fig, x, top, w, h):
    """Embed a matplotlib `Figure` as vector SVG in a box, top-aligned/centered.

    The figure is scaled uniformly to fit `w` x `h` (preserving aspect) with its
    top edge at `top` and centered horizontally within the box.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="svg")
    buf.seek(0)
    drawing = svg2rlg(buf)
    scale = min(w / drawing.width, h / drawing.height)
    dw, dh = drawing.width * scale, drawing.height * scale
    drawing.scale(scale, scale)
    drawing.width, drawing.height = dw, dh
    drawing.drawOn(c, x + (w - dw) / 2, top - dh)


def _roi_series(arr, roi):
    """ROI-mean time series of a 3-D (X, Y, T) array."""
    return arr[roi.index].mean(axis=(0, 1))


def _draw_roi(ax, roi):
    (r, c) = roi.index
    ax.add_patch(Rectangle(
        (c.start - 0.5, r.start - 0.5), c.stop - c.start, r.stop - r.start,
        edgecolor="red", facecolor="none", lw=1.0,
    ))


def _panel_fig(img, title, *, mask=None, roi=None, log=False, aspect=1.15):
    """A single labelled image panel as a square-ish figure."""
    fig = Figure(figsize=(2.0, 2.0 * aspect))
    ax = fig.add_subplot(111)
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
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.90)
    return fig


def _plot_fig(draw, figsize):
    """Run an ax-drawing callback on a fresh constrained-layout figure."""
    fig = Figure(figsize=figsize, layout="constrained")
    draw(fig.add_subplot(111))
    return fig


def _plot_weisskoff(ax, wk, fs=9):
    """Measured CV vs the ideal slope=-1 line, anchored at the pooled cv1.

    Anchoring the ideal line at `cv1_pooled` (the single-voxel CV pooled over the
    whole ROI) rather than at the single-voxel `cv[0]` makes the graphical RDC —
    where the measured plateau meets this line — equal the reported RDC, and is
    robust to the intensity non-uniformity that biases a single-voxel anchor.
    """
    ax.loglog(wk.roi_sizes, wk.cv, "o-", ms=3, label="measured")
    ax.loglog(wk.roi_sizes, wk.cv1_pooled / wk.roi_sizes,
              "--", color="gray", label="ideal (pooled cv1)")
    ax.set_xlabel("ROI width (voxels)")
    ax.set_ylabel("CV")
    ax.set_title(f"Weisskoff (RDC {wk.rdc:.1f})", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_rdc(ax, wk, fs=9):
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


def _plot_signal(ax, t, signal, trend, fs=9):
    ax.plot(t, signal, lw=0.5, label="ROI signal")
    ax.plot(t, trend, "r", lw=1.2, label="trend")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("intensity")
    ax.set_title("ROI mean signal", fontsize=fs)
    ax.legend(fontsize=fs - 2)


def _plot_residual(ax, t, resid, fs=9):
    ax.plot(t, resid, lw=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("residual")
    ax.set_title("ROI mean residual", fontsize=fs)


def _plot_spectrum(ax, resid, tr, fs=9):
    freqs = np.fft.rfftfreq(resid.size, d=tr)
    ax.plot(freqs[1:], np.abs(np.fft.rfft(resid))[1:], lw=0.7)  # skip DC
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude")
    ax.set_title("residual spectrum", fontsize=fs)


# --------------------------------------------------------------------------- #
# ReportLab page composition
# --------------------------------------------------------------------------- #

def _header(c, result, title, *, meta_fs, metric_fs):
    """Draw the title + metadata/metric lines; return the y below them."""
    images, roi, m = result.images, result.roi, result.metrics
    pe = _AXIS_LETTER.get(images.pe_axis, "?")
    line1 = (f"TR {images.tr:.3g}s   voxel {images.voxel_size:.3g}mm   "
             f"frames {images.center_slice.shape[-1]}   PE {pe}   "
             f"detrend {images.detrend_method}   "
             f"ROI {roi.size}x{roi.size} @ ({int(roi.center[0])},{int(roi.center[1])})")
    line2 = (f"SNR {m.snr:.1f}   SFNR {m.sfnr:.1f}   RDC {m.rdc:.2f}   "
             f"ghost {m.ghost_ratio:.4f}   drift {m.drift_pct:.3f}%   "
             f"fluct {m.percent_fluctuation:.3f}%")

    y = _PAGE_H - 34
    if title:
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(_PAGE_W / 2, y, title)
    y -= 24
    c.setFont("Courier", meta_fs)
    c.drawString(_MARGIN, y, line1)
    y -= 16
    c.setFont("Courier-Bold", metric_fs)
    c.drawString(_MARGIN, y, line2)
    return y - 14


def _panel_figs(result):
    """The four summary image panels, in row order."""
    images, geom, roi = result.images, result.geom, result.roi
    sfnr_img = np.where(geom.phantom_mask,
                        images.mean_image / (images.fluctuation_noise + 1e-9), 0.0)
    return [
        _panel_fig(images.mean_image, "signal",
                   mask=geom.phantom_mask, roi=roi),
        _panel_fig(sfnr_img, "SFNR", roi=roi),
        _panel_fig(images.fluctuation_noise, "fluct noise (log)",
                   mask=geom.phantom_mask, roi=roi, log=True),
        _panel_fig(images.static_noise, "static noise",
                   mask=geom.phantom_mask, roi=roi),
    ]


def _panel_row(c, figs, top):
    """Draw four panels across the content width; return the y below them."""
    gap = 8.0
    pw = (_CONTENT_W - 3 * gap) / 4
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        _draw_fig(c, fig, _MARGIN + i * (pw + gap), top, pw, ph)
    return top - ph


def _timeseries(result):
    images, roi = result.images, result.roi
    n = images.center_slice.shape[-1]
    t = np.arange(n) * images.tr
    return (t,
            _roi_series(images.center_slice, roi),
            _roi_series(images.trend, roi),
            _roi_series(images.fluctuations, roi))


def _one_page(c, result, title):
    wk = result.metrics.weisskoff
    y = _header(c, result, title, meta_fs=8.3, metric_fs=10.0)

    y = _panel_row(c, _panel_figs(result), y - 6)

    t, signal, trend, resid = _timeseries(result)
    gap, row_h = 16.0, 150.0
    half = (_CONTENT_W - gap) / 2

    y -= 10
    _draw_fig(c, _plot_fig(lambda ax: _plot_weisskoff(ax, wk), (3.6, 2.5)),
                _MARGIN, y, half, row_h)
    _draw_fig(c, _plot_fig(lambda ax: _plot_rdc(ax, wk), (3.6, 2.5)),
                _MARGIN + half + gap, y, half, row_h)
    y -= row_h + 6

    _draw_fig(c, _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend),
                             (3.6, 2.5)), _MARGIN, y, half, row_h)
    _draw_fig(c, _plot_fig(lambda ax: _plot_residual(ax, t, resid), (3.6, 2.5)),
                _MARGIN + half + gap, y, half, row_h)
    y -= row_h + 6

    _draw_fig(c, _plot_fig(lambda ax: _plot_spectrum(ax, resid, result.images.tr),
                             (7.2, 1.9)), _MARGIN, y, _CONTENT_W, 120.0)


def _summary_page(c, result, title):
    y = _header(c, result, title, meta_fs=9.0, metric_fs=11.0)
    # Two large image rows: signal/SFNR then fluct-noise/static-noise.
    figs = _panel_figs(result)
    gap = 16.0
    half = (_CONTENT_W - gap) / 2
    ph = half * 1.05
    y -= 8
    for row in (figs[:2], figs[2:]):
        for i, fig in enumerate(row):
            _draw_fig(c, fig, _MARGIN + i * (half + gap), y, half, ph)
        y -= ph + 14


def _analysis_page(c, result, title):
    wk = result.metrics.weisskoff
    t, signal, trend, resid = _timeseries(result)

    y = _PAGE_H - 34
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(_PAGE_W / 2, y, f"{title} — stability" if title else "stability")
    y -= 24

    gap, row_h = 16.0, 200.0
    half = (_CONTENT_W - gap) / 2
    _draw_fig(c, _plot_fig(lambda ax: _plot_weisskoff(ax, wk, fs=10), (3.6, 3.0)),
                _MARGIN, y, half, row_h)
    _draw_fig(c, _plot_fig(lambda ax: _plot_rdc(ax, wk, fs=10), (3.6, 3.0)),
                _MARGIN + half + gap, y, half, row_h)
    y -= row_h + 12

    _draw_fig(c, _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend, fs=10),
                             (3.6, 3.0)), _MARGIN, y, half, row_h)
    _draw_fig(c, _plot_fig(lambda ax: _plot_residual(ax, t, resid, fs=10),
                             (3.6, 3.0)), _MARGIN + half + gap, y, half, row_h)
    y -= row_h + 12

    _draw_fig(c, _plot_fig(lambda ax: _plot_spectrum(ax, resid, result.images.tr, fs=10),
                             (7.2, 2.2)), _MARGIN, y, _CONTENT_W, 150.0)


REPORT_LAYOUTS = ("one", "two")


def add_report_pages(c: canvas.Canvas, result: "q.QAResult", title: str = "",
                     layout: str = "one") -> None:
    """Draw a scan's report page(s) onto an open ReportLab `Canvas`.

    `layout="one"` renders a single condensed page; `layout="two"` renders a
    summary page and a separate stability page. Each page is finalized with
    `showPage()`.
    """
    if layout == "one":
        _one_page(c, result, title)
        c.showPage()
    elif layout == "two":
        _summary_page(c, result, title)
        c.showPage()
        _analysis_page(c, result, title)
        c.showPage()
    else:
        raise ValueError(f"unknown layout {layout!r}; choose from {REPORT_LAYOUTS}")


def write_report(items, pdf_path, layout: str = "one") -> None:
    """Write a combined PDF, one scan after another.

    `items` is an iterable of `(title, QAResult)`, or a single `QAResult`.
    """
    if isinstance(items, q.QAResult):
        items = [("", items)]
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    for title, result in items:
        add_report_pages(c, result, title, layout)
    c.save()
