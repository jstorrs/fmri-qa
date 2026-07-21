"""ReportLab PDF driver: compose the format-agnostic panels/text onto pages.

The page layout (title, metadata, metric tiles, and the placement grid) is drawn
natively with ReportLab; every matplotlib figure from `report.panels` is
embedded as vector SVG (via svglib) so the axes, curves, and labels stay crisp.
The phantom images inside `imshow` are inherently raster and ride along inside
the SVG. See `_patch_svglib_image_alignment` for the one svglib defect this has
to work around. This is the plug point for other output formats: a new driver
reuses `report.panels` and `report.summary` and only re-implements composition.
"""

import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from matplotlib.figure import Figure
from reportlab.graphics.shapes import Group, Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from svglib import svglib as _svglib
from svglib.svglib import svg2rlg

import fmriqc as q

from ..panels.images import _panel_figs
from ..panels.timeseries import (
    _plot_com,
    _plot_fig,
    _plot_motion,
    _plot_outliers,
    _plot_psf,
    _plot_rdc,
    _plot_residual,
    _plot_signal,
    _plot_spectrum,
    _plot_weisskoff,
    _timeseries,
)
from ..summary import (
    _acquisition_line,
    _device_line,
    _metric_tiles,
    _provenance_line,
)

_PAGE_W: float
_PAGE_H: float
_PAGE_W, _PAGE_H = letter  # 612 x 792 pt
_MARGIN = 40.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN

_TILE_H = 34.0  # metric-tile height (pt)
_TILE_GAP = 6.0


def _patch_svglib_image_alignment() -> None:
    """Fix svglib truncating embedded-image geometry to whole points.

    svglib's `convertImage` builds the ReportLab `Image` from `int(x)`,
    `int(y + height)`, `int(width)`, `int(height)` while flipping the enclosing
    group by the *un*-truncated `(y + height) * 2`. For an `imshow` panel the
    raster then lands up to a point off from the mask contour and ROI box (which
    keep full precision), so the phantom outline visibly drifts off the image.
    This reinstates the method verbatim without the `int()` casts. Pinned to the
    svglib in `uv.lock`; revisit on upgrade.
    """

    def convertImage(self: Any, node: Any) -> Any:
        x, y, width, height = self.convert_length_attrs(
            node, "x", "y", "width", "height"
        )
        image = node._resolved_target
        image = Image(x, y + height, width, height, image)
        group = Group(image)
        group.translate(0, (y + height) * 2)
        group.scale(1, -1)
        return group

    _svglib.Svg2RlgShapeConverter.convertImage = convertImage


_patch_svglib_image_alignment()


def _draw_fig(
    c: canvas.Canvas, fig: Figure, x: float, top: float, w: float, h: float
) -> None:
    """Embed a matplotlib `Figure` as vector SVG in a box, top-aligned/centered.

    The figure is scaled uniformly to fit `w` x `h` (preserving aspect) with its
    top edge at `top` and centered horizontally within the box.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="svg")
    buf.seek(0)
    drawing = svg2rlg(buf)
    if drawing is None:  # svg2rlg returns None only on a parse failure
        raise RuntimeError("svg2rlg failed to render the figure SVG")
    scale = min(w / drawing.width, h / drawing.height)
    dw, dh = drawing.width * scale, drawing.height * scale
    drawing.scale(scale, scale)
    drawing.width, drawing.height = dw, dh
    drawing.drawOn(c, x + (w - dw) / 2, top - dh)


def _draw_tiles(c: canvas.Canvas, tiles: list[tuple[str, str]], top: float) -> float:
    """Draw the metric tiles as an even strip across the content width."""
    n = len(tiles)
    tw = (_CONTENT_W - (n - 1) * _TILE_GAP) / n
    bottom = top - _TILE_H
    for i, (label, value) in enumerate(tiles):
        x = _MARGIN + i * (tw + _TILE_GAP)
        cx = x + tw / 2
        c.setFillGray(0.96)
        c.setStrokeGray(0.80)
        c.setLineWidth(0.5)
        c.rect(x, bottom, tw, _TILE_H, stroke=1, fill=1)
        c.setFillGray(0.10)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(cx, bottom + 18, value)
        c.setFillGray(0.45)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(cx, bottom + 6, label)
    c.setFillGray(0.0)
    return bottom


def _header(c: canvas.Canvas, result: q.QAResult, title: str) -> float:
    """Draw the scan name, metadata lines, and metric tiles; return the y below."""
    y = _PAGE_H - 32
    if title:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(_MARGIN, y, title)
    device = _device_line(result.meta)
    if device:
        c.setFont("Helvetica", 9)
        c.setFillGray(0.40)
        c.drawRightString(_PAGE_W - _MARGIN, y, device)
    if title or device:
        y -= 14

    c.setFont("Helvetica", 8.3)
    c.setFillGray(0.40)
    c.drawString(_MARGIN, y, _acquisition_line(result))
    prov = _provenance_line(result.meta)
    if prov:
        y -= 11
        c.drawString(_MARGIN, y, prov)
    c.setFillGray(0.0)

    bottom = _draw_tiles(c, _metric_tiles(result.metrics), y - 12)
    return bottom - 10


def _panel_row(
    c: canvas.Canvas, figs: list[Figure], top: float, *, gap: float = 8.0
) -> float:
    """Draw the panels in one row across the content width; return the y below."""
    n = len(figs)
    pw = (_CONTENT_W - (n - 1) * gap) / n
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        _draw_fig(c, fig, _MARGIN + i * (pw + gap), top, pw, ph)
    return top - ph


def _panel_grid(
    c: canvas.Canvas, figs: list[Figure], top: float, *, ncol: int, gap: float = 14.0
) -> float:
    """Draw the panels in a grid of `ncol` columns; return the y below the grid."""
    pw = (_CONTENT_W - (ncol - 1) * gap) / ncol
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        r, col = divmod(i, ncol)
        _draw_fig(c, fig, _MARGIN + col * (pw + gap), top - r * (ph + gap), pw, ph)
    rows = -(-len(figs) // ncol)  # ceil
    return top - rows * ph - (rows - 1) * gap


def _one_page(c: canvas.Canvas, result: q.QAResult, title: str) -> None:
    wk = result.metrics.weisskoff
    y = _header(c, result, title)

    y = _panel_row(c, _panel_figs(result), y - 6)

    t, signal, trend, resid = _timeseries(result)
    gap, row_h = 16.0, 150.0
    half = (_CONTENT_W - gap) / 2

    y -= 10
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk), (3.6, 2.5)),
        _MARGIN,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_rdc(ax, wk), (3.6, 2.5)),
        _MARGIN + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 6

    spikes = result.metrics.spikes
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend), (3.6, 2.5)),
        _MARGIN,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_residual(ax, t, resid, tc_outlier=spikes.tc_outlier),
            (3.6, 2.5),
        ),
        _MARGIN + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 6

    fifth = (_CONTENT_W - 4 * gap) / 5
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_spectrum(
                ax, resid, result.images.tr, spec_outlier=spikes.spec_outlier
            ),
            (3.0, 2.0),
        ),
        _MARGIN,
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_outliers(ax, t, result.metrics.outliers), (3.0, 2.0)
        ),
        _MARGIN + fifth + gap,
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_motion(ax, t, result.metrics.motion), (3.0, 2.0)),
        _MARGIN + 2 * (fifth + gap),
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_com(ax, t, result.metrics.center_of_mass), (3.0, 2.0)
        ),
        _MARGIN + 3 * (fifth + gap),
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_psf(ax, result.metrics.smoothness), (3.0, 2.0)),
        _MARGIN + 4 * (fifth + gap),
        y,
        fifth,
        120.0,
    )


def _summary_page(c: canvas.Canvas, result: q.QAResult, title: str) -> None:
    y = _header(c, result, title)
    # Five image panels (signal, SFNR, fluct/static noise, N/2 ghost) in a grid.
    _panel_grid(c, _panel_figs(result), y - 8, ncol=3)


def _analysis_page(c: canvas.Canvas, result: q.QAResult, title: str) -> None:
    wk = result.metrics.weisskoff
    t, signal, trend, resid = _timeseries(result)

    y = _PAGE_H - 34
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(
        _PAGE_W / 2, y, f"{title} — stability" if title else "stability"
    )
    y -= 24

    gap, row_h = 16.0, 200.0
    half = (_CONTENT_W - gap) / 2
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk, fs=10), (3.6, 3.0)),
        _MARGIN,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_rdc(ax, wk, fs=10), (3.6, 3.0)),
        _MARGIN + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 12

    spikes = result.metrics.spikes
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend, fs=10), (3.6, 3.0)),
        _MARGIN,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_residual(
                ax, t, resid, fs=10, tc_outlier=spikes.tc_outlier
            ),
            (3.6, 3.0),
        ),
        _MARGIN + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 12

    fifth = (_CONTENT_W - 4 * gap) / 5
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_spectrum(
                ax, resid, result.images.tr, fs=10, spec_outlier=spikes.spec_outlier
            ),
            (3.0, 2.2),
        ),
        _MARGIN,
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_outliers(ax, t, result.metrics.outliers, fs=10), (3.0, 2.2)
        ),
        _MARGIN + fifth + gap,
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_motion(ax, t, result.metrics.motion, fs=10), (3.0, 2.2)
        ),
        _MARGIN + 2 * (fifth + gap),
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_com(ax, t, result.metrics.center_of_mass, fs=10),
            (3.0, 2.2),
        ),
        _MARGIN + 3 * (fifth + gap),
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_psf(ax, result.metrics.smoothness, fs=10), (3.0, 2.2)
        ),
        _MARGIN + 4 * (fifth + gap),
        y,
        fifth,
        150.0,
    )


REPORT_LAYOUTS = ("one", "two")


def add_report_pages(
    c: canvas.Canvas, result: "q.QAResult", title: str = "", layout: str = "one"
) -> None:
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


def write_report(
    items: Iterable[tuple[str, q.QAResult]] | q.QAResult,
    pdf_path: str | Path,
    layout: str = "one",
) -> None:
    """Write a combined PDF, one scan after another.

    `items` is an iterable of `(title, QAResult)`, or a single `QAResult`.
    """
    if isinstance(items, q.QAResult):
        items = [("", items)]
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    for title, result in items:
        add_report_pages(c, result, title, layout)
    c.save()
