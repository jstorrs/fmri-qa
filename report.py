"""Multi-page PDF QA reports rendered from `fmriqc.QAResult` objects.

The page layout (title, metadata, metric line, and the placement grid) is drawn
natively with ReportLab; every matplotlib figure — the image panels and the
stability plots — is embedded as vector SVG (via svglib) so the axes, curves,
and labels stay crisp. The phantom images inside `imshow` are inherently raster
and ride along inside the SVG. See `_patch_svglib_image_alignment` for the one
svglib defect this has to work around.
"""

import io

import matplotlib

matplotlib.use("Agg")  # headless; no display needed

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle
from reportlab.graphics.shapes import Group, Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from scipy.spatial import ConvexHull
from svglib import svglib as _svglib
from svglib.svglib import svg2rlg

import fmriqc as q

_AXIS_LETTER = {0: "i", 1: "j", 2: "k"}

_PAGE_W, _PAGE_H = letter  # 612 x 792 pt
_MARGIN = 40.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN


# --------------------------------------------------------------------------- #
# matplotlib panels/plots -> embeddable vector drawings
# --------------------------------------------------------------------------- #

def _patch_svglib_image_alignment():
    """Fix svglib truncating embedded-image geometry to whole points.

    svglib's `convertImage` builds the ReportLab `Image` from `int(x)`,
    `int(y + height)`, `int(width)`, `int(height)` while flipping the enclosing
    group by the *un*-truncated `(y + height) * 2`. For an `imshow` panel the
    raster then lands up to a point off from the mask contour and ROI box (which
    keep full precision), so the phantom outline visibly drifts off the image.
    This reinstates the method verbatim without the `int()` casts. Pinned to the
    svglib in `uv.lock`; revisit on upgrade.
    """
    def convertImage(self, node):
        x, y, width, height = self.convert_length_attrs(
            node, "x", "y", "width", "height")
        image = node._resolved_target
        image = Image(x, y + height, width, height, image)
        group = Group(image)
        group.translate(0, (y + height) * 2)
        group.scale(1, -1)
        return group

    _svglib.Svg2RlgShapeConverter.convertImage = convertImage


_patch_svglib_image_alignment()


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


def _data_per_point(ax):
    """Length of one typographic point (1/72 in) in axes data units.

    `imshow` uses equal aspect, so x and y share a scale; `apply_aspect` finalizes
    that scaling first so the measured transform is the one that will render. The
    figure dpi cancels, making the result resolution-independent -- call only
    after the axes position (subplots_adjust) is final.
    """
    ax.apply_aspect()
    (x0, x1) = ax.transData.transform([(0, 0), (1, 0)])[:, 0]
    return (ax.figure.dpi / 72.0) / abs(x1 - x0)


def _draw_roi(ax, roi, *, lw=1.3):
    """Outline the ROI just outside its pixels so the stroke doesn't cover them.

    The ROI's outer boundary in imshow coordinates runs from `start - 0.5` to
    `stop - 0.5`. The stroke is centered on the path, so drawing on that boundary
    spills half the line width inward and hides the edge ROI pixels. Pad outward
    by exactly half the line width -- converted from points to data units via the
    axes scale -- so the stroke's inner edge lands back on the boundary and every
    ROI pixel stays visible.
    """
    (r, c) = roi.index
    pad = 0.5 * lw * _data_per_point(ax)
    ax.add_patch(Rectangle(
        (c.start - 0.5 - pad, r.start - 0.5 - pad),
        (c.stop - c.start) + 2 * pad, (r.stop - r.start) + 2 * pad,
        edgecolor="red", facecolor="none", lw=lw,
    ))


def _draw_hull(ax, mask, *, color="tab:cyan", lw=1.0):
    """Outline the convex hull of a boolean mask as a closed polygon.

    The hull smooths the ragged phantom-mask boundary into a clean convex
    outline. `imshow` maps column -> x and row -> y, so the mask's (row, col)
    pixel coordinates plot as (col, row).
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 3:
        return
    pts = np.column_stack([xs, ys]).astype(float)
    verts = ConvexHull(pts).vertices
    loop = np.append(verts, verts[0])  # close the polygon
    ax.plot(pts[loop, 0], pts[loop, 1], color=color, lw=lw)


def _panel_fig(img, title, *, mask=None, roi=None, log=False, aspect=1.15):
    """A single labelled image panel as a square-ish figure."""
    fig = Figure(figsize=(2.0, 2.0 * aspect))
    ax = fig.add_subplot(111)
    data = np.log(np.clip(img, 1e-9, None)) if log else img
    finite = data[np.isfinite(data)]
    vmin, vmax = (np.percentile(finite, [2, 98]) if finite.size else (0, 1))
    ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    # Fix the axes box before drawing the ROI: its pad is derived from the axes
    # scale (see `_draw_roi`/`_data_per_point`), which subplots_adjust finalizes.
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.90)
    if mask is not None:
        _draw_hull(ax, mask, lw=1.0)
    if roi is not None:
        _draw_roi(ax, roi)
    ax.set_title(title, fontsize=9)
    return fig


_GHOST_SRC_RGB = (0.20, 0.85, 1.0)  # PE signal source region (cyan)
_GHOST_RGB = (1.0, 0.30, 0.30)  # PE ghost region (red)
_RO_SRC_RGB = (0.45, 1.0, 0.35)  # RO signal source region (green)
_RO_GHOST_RGB = (1.0, 0.72, 0.15)  # RO ghost region (amber)
_INVALID_RGB = (1.0, 0.15, 0.90)  # zeroed image edge, excluded from stats (magenta)


def _overlay(ax, mask, rgb, alpha=0.45):
    """Tint the True pixels of `mask` with a translucent color over the image."""
    rgba = np.zeros((*mask.shape, 4))
    rgba[mask] = (*rgb, alpha)
    ax.imshow(rgba, interpolation="nearest")


def _ghost_panel_fig(mean_image, phantom_mask, pe_axis, *, aspect=1.15):
    """Mean image with the region-matched ghost/signal masks for both axes.

    Draws the exact masks the ghost metrics average: for each in-plane axis, the
    ghost patch (where the phantom rolled half the FOV lands clear of the phantom)
    and its source on the phantom (that patch rolled back). The PE pair (cyan/red)
    feeds ghost%; the readout pair (green/amber) feeds RO% -- the background-
    relative baseline whose difference from ghost% is ACRg -- so both reported
    percentages can be checked against where they are sampled. Any zeroed image
    edge dropped from the statistics (magenta) is marked when present. The ghost
    pairs are blank if the PE axis is unknown.
    """
    fig = Figure(figsize=(2.0, 2.0 * aspect))
    ax = fig.add_subplot(111)
    ax.imshow(mean_image, cmap="gray", vmin=0, vmax=np.percentile(mean_image, 99),
              interpolation="nearest")
    valid_mask = q.edge_valid_mask(mean_image)
    handles = []
    if pe_axis in (0, 1):
        ro_axis = 1 - pe_axis
        ro_signal, ro_ghost = q._ghost_masks(phantom_mask, ro_axis, 3, valid_mask)
        signal_mask, ghost_mask = q._ghost_masks(phantom_mask, pe_axis, 3, valid_mask)
        _overlay(ax, ro_signal, _RO_SRC_RGB)
        _overlay(ax, ro_ghost, _RO_GHOST_RGB)
        _overlay(ax, signal_mask, _GHOST_SRC_RGB)
        _overlay(ax, ghost_mask, _GHOST_RGB)
        handles += [Patch(color=_GHOST_SRC_RGB, label="PE signal"),
                    Patch(color=_GHOST_RGB, label="PE ghost"),
                    Patch(color=_RO_SRC_RGB, label="RO signal"),
                    Patch(color=_RO_GHOST_RGB, label="RO ghost")]
    invalid = ~valid_mask
    if invalid.any():
        _overlay(ax, invalid, _INVALID_RGB, alpha=0.9)
        handles.append(Patch(color=_INVALID_RGB, label="invalid edge"))
    if handles:
        ax.legend(
            handles=handles, fontsize=5, loc="lower right", framealpha=0.6,
            handlelength=1.0, borderpad=0.3, labelspacing=0.2,
        )
    ax.set_title("N/2 ghost", fontsize=9)
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
    pe = _AXIS_LETTER.get(m.pe_axis, "?")
    line1 = (f"TR {images.tr:.3g}s   voxel {images.voxel_size:.3g}mm   "
             f"frames {images.center_slice.shape[-1]}   PE {pe}   "
             f"detrend {images.detrend_method}   "
             f"ROI {roi.size}x{roi.size} @ ({int(roi.center[0])},{int(roi.center[1])})")
    line2 = (f"SNR {m.snr:.1f}   SFNR {m.sfnr:.1f}   RDC {m.rdc:.2f}   "
             f"ghost {m.ghost_pct:.2f}%   RO {m.ro_ghost_pct:.2f}%   "
             f"ACRg {m.acr_ghost_pct:.2f}%   "
             f"drift {m.drift_pct:.3f}%   fluct {m.percent_fluctuation:.3f}%")

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
    """The summary image panels, in row order (last is the N/2 ghost overlay)."""
    images, geom, roi, m = result.images, result.geom, result.roi, result.metrics
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
        _ghost_panel_fig(images.mean_image, geom.phantom_mask, m.pe_axis),
    ]


def _panel_row(c, figs, top, *, gap=8.0):
    """Draw the panels in one row across the content width; return the y below."""
    n = len(figs)
    pw = (_CONTENT_W - (n - 1) * gap) / n
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        _draw_fig(c, fig, _MARGIN + i * (pw + gap), top, pw, ph)
    return top - ph


def _panel_grid(c, figs, top, *, ncol, gap=14.0):
    """Draw the panels in a grid of `ncol` columns; return the y below the grid."""
    pw = (_CONTENT_W - (ncol - 1) * gap) / ncol
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        r, col = divmod(i, ncol)
        _draw_fig(c, fig, _MARGIN + col * (pw + gap), top - r * (ph + gap), pw, ph)
    rows = -(-len(figs) // ncol)  # ceil
    return top - rows * ph - (rows - 1) * gap


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
    y = _header(c, result, title, meta_fs=9.0, metric_fs=10.0)
    # Five image panels (signal, SFNR, fluct/static noise, N/2 ghost) in a grid.
    _panel_grid(c, _panel_figs(result), y - 8, ncol=3)


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
