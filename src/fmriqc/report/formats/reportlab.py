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
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, cast

import matplotlib
from matplotlib.figure import Figure
from reportlab.graphics.shapes import Group, Image
from reportlab.pdfgen import canvas
from svglib import svglib as _svglib
from svglib.svglib import svg2rlg

import fmriqc as q

from ..document import Part, ScanSection, Tier, compose, parts_for
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
from ..theme import DEFAULT_THEME, Theme

# A page-part renderer: draw one scan's part onto the canvas (no showPage).
PageRenderer = Callable[[canvas.Canvas, q.QAResult, str, Theme], None]

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


def _draw_tiles(
    c: canvas.Canvas, tiles: list[tuple[str, str]], top: float, theme: Theme
) -> float:
    """Draw the metric tiles as an even strip across the content width."""
    n = len(tiles)
    tw = (theme.content_width - (n - 1) * _TILE_GAP) / n
    bottom = top - _TILE_H
    for i, (label, value) in enumerate(tiles):
        x = theme.margin + i * (tw + _TILE_GAP)
        cx = x + tw / 2
        c.setFillGray(theme.tile_fill_gray)
        c.setStrokeGray(theme.tile_stroke_gray)
        c.setLineWidth(0.5)
        c.rect(x, bottom, tw, _TILE_H, stroke=1, fill=1)
        c.setFillGray(theme.tile_value_gray)
        c.setFont(theme.font_numeric, 12)
        c.drawCentredString(cx, bottom + 18, value)
        c.setFillGray(theme.tile_label_gray)
        c.setFont(theme.font_body, 6.5)
        c.drawCentredString(cx, bottom + 6, label)
    c.setFillGray(theme.text_primary_gray)
    return bottom


def _header(c: canvas.Canvas, result: q.QAResult, title: str, theme: Theme) -> float:
    """Draw the scan name, metadata lines, and metric tiles; return the y below."""
    page_w, page_h = theme.page_size
    y = page_h - 32
    if title:
        c.setFont(theme.font_title, 14)
        c.drawString(theme.margin, y, title)
    device = _device_line(result.meta)
    if device:
        c.setFont(theme.font_body, 9)
        c.setFillGray(theme.text_muted_gray)
        c.drawRightString(page_w - theme.margin, y, device)
    if title or device:
        y -= 14

    c.setFont(theme.font_body, 8.3)
    c.setFillGray(theme.text_muted_gray)
    c.drawString(theme.margin, y, _acquisition_line(result))
    prov = _provenance_line(result.meta)
    if prov:
        y -= 11
        c.drawString(theme.margin, y, prov)
    c.setFillGray(theme.text_primary_gray)

    bottom = _draw_tiles(c, _metric_tiles(result.metrics), y - 12, theme)
    return bottom - 10


def _panel_row(
    c: canvas.Canvas, figs: list[Figure], top: float, theme: Theme, *, gap: float = 8.0
) -> float:
    """Draw the panels in one row across the content width; return the y below."""
    n = len(figs)
    pw = (theme.content_width - (n - 1) * gap) / n
    ph = pw * 1.15
    for i, fig in enumerate(figs):
        _draw_fig(c, fig, theme.margin + i * (pw + gap), top, pw, ph)
    return top - ph


def _condensed_page(
    c: canvas.Canvas, result: q.QAResult, title: str, theme: Theme
) -> None:
    wk = result.metrics.weisskoff
    y = _header(c, result, title, theme)

    y = _panel_row(c, _panel_figs(result), y - 6, theme)

    t, signal, trend, resid = _timeseries(result)
    gap, row_h = 16.0, 150.0
    half = (theme.content_width - gap) / 2

    y -= 10
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk), (3.6, 2.5)),
        theme.margin,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_rdc(ax, wk), (3.6, 2.5)),
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 6

    spikes = result.metrics.spikes
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend), (3.6, 2.5)),
        theme.margin,
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
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 6

    fifth = (theme.content_width - 4 * gap) / 5
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_spectrum(
                ax, resid, result.images.tr, spec_outlier=spikes.spec_outlier
            ),
            (3.0, 2.0),
        ),
        theme.margin,
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_outliers(ax, t, result.metrics.outliers), (3.0, 2.0)
        ),
        theme.margin + fifth + gap,
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_motion(ax, t, result.metrics.motion), (3.0, 2.0)),
        theme.margin + 2 * (fifth + gap),
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_com(ax, t, result.metrics.center_of_mass), (3.0, 2.0)
        ),
        theme.margin + 3 * (fifth + gap),
        y,
        fifth,
        120.0,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_psf(ax, result.metrics.smoothness), (3.0, 2.0)),
        theme.margin + 4 * (fifth + gap),
        y,
        fifth,
        120.0,
    )


def _analysis_page(
    c: canvas.Canvas, result: q.QAResult, title: str, theme: Theme
) -> None:
    wk = result.metrics.weisskoff
    t, signal, trend, resid = _timeseries(result)

    page_w, page_h = theme.page_size
    y = page_h - 34
    c.setFont(theme.font_title, 13)
    c.drawCentredString(page_w / 2, y, f"{title} — stability" if title else "stability")
    y -= 24

    gap, row_h = 16.0, 200.0
    half = (theme.content_width - gap) / 2
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk, fs=10), (3.6, 3.0)),
        theme.margin,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_rdc(ax, wk, fs=10), (3.6, 3.0)),
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 12

    spikes = result.metrics.spikes
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, t, signal, trend, fs=10), (3.6, 3.0)),
        theme.margin,
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
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 12

    fifth = (theme.content_width - 4 * gap) / 5
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_spectrum(
                ax, resid, result.images.tr, fs=10, spec_outlier=spikes.spec_outlier
            ),
            (3.0, 2.2),
        ),
        theme.margin,
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_outliers(ax, t, result.metrics.outliers, fs=10), (3.0, 2.2)
        ),
        theme.margin + fifth + gap,
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_motion(ax, t, result.metrics.motion, fs=10), (3.0, 2.2)
        ),
        theme.margin + 2 * (fifth + gap),
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
        theme.margin + 3 * (fifth + gap),
        y,
        fifth,
        150.0,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_psf(ax, result.metrics.smoothness, fs=10), (3.0, 2.2)
        ),
        theme.margin + 4 * (fifth + gap),
        y,
        fifth,
        150.0,
    )


# One renderer per page `Part` (see `report.document`). Each draws its content
# for a scan; `add_report_pages` finalizes each with `showPage()`.
_PART_RENDERERS: dict[Part, PageRenderer] = {
    "overview": _condensed_page,
    "stability": _analysis_page,
}


def _render_section(c: canvas.Canvas, section: ScanSection, theme: Theme) -> int:
    """Draw one scan's parts onto the canvas; return the number of pages drawn.

    The parts are built under the theme's `rc_context`, so the phantom colormap
    and the primary-series colour follow the theme along with the furniture.
    """
    # cast: rc_context's stub keys are a Literal union, not str; the values are
    # valid rc keys built by the theme.
    with matplotlib.rc_context(cast("Any", theme.rc_params())):
        for part in section.parts:
            _PART_RENDERERS[part](c, section.result, section.title, theme)
            c.showPage()
    return len(section.parts)


def add_report_pages(
    c: canvas.Canvas,
    result: "q.QAResult",
    title: str = "",
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
) -> int:
    """Draw a scan's report page(s) onto an open ReportLab `Canvas`.

    `tier="dashboard"` renders the single condensed overview page; `tier="physics"`
    renders that overview and then a full-size stability page. Each page is
    finalized with `showPage()`. Returns the number of pages drawn.
    """
    return _render_section(c, ScanSection(title, result, parts_for(tier)), theme)


def write_report(
    items: Iterable[tuple[str, q.QAResult]] | q.QAResult,
    pdf_path: str | Path,
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
) -> int:
    """Write a combined PDF, one scan after another.

    `items` is an iterable of `(title, QAResult)`, or a single `QAResult`.
    Returns the total number of pages written.
    """
    if isinstance(items, q.QAResult):
        items = [("", items)]
    c = canvas.Canvas(str(pdf_path), pagesize=theme.page_size)
    pages = sum(_render_section(c, s, theme) for s in compose(items, tier))
    c.save()
    return pages
