"""One function per page the PDF driver can draw.

Each renderer draws a single page's content onto an open ReportLab `Canvas` and
leaves the `showPage()` to `packet`, which assembles them. The content itself —
the metric vocabulary, the text lines, the matplotlib panels — arrives from the
format-agnostic modules; everything here is placement: where a figure, a tile,
or a line of prose lands on the sheet. `layout` does the arithmetic.
"""

import io
from collections.abc import Callable

from matplotlib.axes import Axes
from matplotlib.figure import Figure
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

from fmriqc.analysis import Curves, Measurements, QAArtifact

from ...content import METRIC_DOCS, characterization_rows, metric_tiles
from ...document import Appendix, Cover, Part
from ...panels.images import panel_figs
from ...panels.timeseries import (
    plot_com,
    plot_fig,
    plot_motion,
    plot_outliers,
    plot_psf,
    plot_rdc,
    plot_residual,
    plot_signal,
    plot_spectrum,
    plot_weisskoff,
)
from ...summary import acquisition_line, acquisition_notes, device_line, provenance_line
from ...theme import Theme
from .layout import (
    APPENDIX_DETAIL_DROP,
    APPENDIX_NAME_DROP,
    COVER_ROW_H,
    TILE_GAP,
    TILE_H,
    CoverRow,
    appendix_cursors,
    cover_cursors,
    dashboard_heights,
    fit_text,
    tile_geometry,
    title_baseline,
    wrap_text,
)
from .svglib_patch import ensure_installed

# A page-part renderer: draw one scan's part onto the canvas (no showPage).
PageRenderer = Callable[[canvas.Canvas, QAArtifact, str, Theme], None]


def _draw_fig(
    c: canvas.Canvas, fig: Figure, x: float, top: float, w: float, h: float
) -> None:
    """Embed a matplotlib `Figure` as vector SVG in a box, top-aligned/centered.

    The figure is scaled uniformly to fit `w` x `h` (preserving aspect) with its
    top edge at `top` and centered horizontally within the box.
    """
    ensure_installed()  # the raster/vector alignment fix; see its docstring
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


def _draw_plot(
    c: canvas.Canvas,
    draw: Callable[[Axes], object],
    figsize: tuple[float, float],
    x: float,
    top: float,
    w: float,
    h: float,
) -> None:
    """Build a one-axes figure with `draw` and embed it in the box at (x, top)."""
    _draw_fig(c, plot_fig(draw, figsize), x, top, w, h)


def _draw_tiles(
    c: canvas.Canvas, tiles: list[tuple[str, str]], top: float, theme: Theme
) -> float:
    """Draw measured metric tiles in as many rows as their text needs."""
    columns, tw = tile_geometry(tiles, theme)
    bottom = top
    for i, (label, value) in enumerate(tiles):
        row, column = divmod(i, columns)
        bottom = top - row * (TILE_H + TILE_GAP) - TILE_H
        x = theme.margin + column * (tw + TILE_GAP)
        cx = x + tw / 2
        c.setFillGray(theme.tile_fill_gray)
        c.setStrokeGray(theme.tile_stroke_gray)
        c.setLineWidth(0.5)
        c.rect(x, bottom, tw, TILE_H, stroke=1, fill=1)
        c.setFillGray(theme.tile_value_gray)
        c.setFont(theme.font_numeric, 12)
        c.drawCentredString(cx, bottom + 18, value)
        c.setFillGray(theme.tile_label_gray)
        c.setFont(theme.font_body, 6.5)
        c.drawCentredString(cx, bottom + 6, label)
    c.setFillGray(theme.text_primary_gray)
    return bottom


def _header(c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme) -> float:
    """Draw the scan name, metadata lines, and metric tiles; return the y below."""
    y = theme.page_height - 32
    rows = (
        (title, theme.font_title, 14.0, 17.0, theme.text_primary_gray),
        (
            device_line(artifact.provenance),
            theme.font_body,
            9.0,
            12.0,
            theme.text_muted_gray,
        ),
        (acquisition_line(artifact), theme.font_body, 8.3, 11.0, theme.text_muted_gray),
        (
            provenance_line(artifact.provenance),
            theme.font_body,
            8.3,
            11.0,
            theme.text_muted_gray,
        ),
        (
            acquisition_notes(artifact),
            theme.font_body,
            8.3,
            11.0,
            theme.text_primary_gray,
        ),
    )
    for text, font, size, pitch, gray in rows:
        if not text:
            continue
        c.setFont(font, size)
        c.setFillGray(gray)
        for line in wrap_text(text, font, size, theme.content_width):
            c.drawString(theme.margin, y, line)
            y -= pitch
    bottom = _draw_tiles(c, metric_tiles(artifact.measurements), y - 1, theme)
    return bottom - 10


def _panel_row(
    c: canvas.Canvas,
    figs: list[Figure],
    top: float,
    theme: Theme,
    *,
    height: float,
    gap: float = 8.0,
) -> float:
    """Draw the panels in one row across the content width; return the y below."""
    n = len(figs)
    pw = (theme.content_width - (n - 1) * gap) / n
    for i, fig in enumerate(figs):
        _draw_fig(c, fig, theme.margin + i * (pw + gap), top, pw, height)
    return top - height


def _curve_grid(
    c: canvas.Canvas,
    curves: Curves,
    m: Measurements,
    theme: Theme,
    y: float,
    *,
    fs: int,
    figsize: tuple[float, float],
    row_h: float,
    row_gap: float,
    gap: float = 16.0,
) -> float:
    """Draw the four core stability curves in a 2x2 grid; return the y below.

    Weisskoff and RDC on the first row, ROI signal and residual on the second.
    Both the dashboard overview and the physics stability page draw this same
    grid; only the type size, figure size, and drawn height differ, so they
    cannot disagree about which curves the core four are.
    """
    half = (theme.content_width - gap) / 2
    right = theme.margin + half + gap
    wk = curves.weisskoff
    rows: tuple[tuple[Callable[[Axes], object], Callable[[Axes], object]], ...] = (
        (
            lambda ax: plot_weisskoff(ax, wk, m.rdc, fs=fs),
            lambda ax: plot_rdc(ax, wk, fs=fs),
        ),
        (
            lambda ax: plot_signal(ax, curves, fs=fs),
            lambda ax: plot_residual(ax, curves, fs=fs, tc_outlier=m.tc_outlier),
        ),
    )
    for left_draw, right_draw in rows:
        _draw_plot(c, left_draw, figsize, theme.margin, y, half, row_h)
        _draw_plot(c, right_draw, figsize, right, y, half, row_h)
        y -= row_h + row_gap
    return y


def _stability_strip(
    c: canvas.Canvas,
    curves: Curves,
    m: Measurements,
    theme: Theme,
    y: float,
    *,
    fs: int,
    figsize: tuple[float, float],
    height: float,
    gap: float = 16.0,
) -> None:
    """Draw the five narrow stability panels in one row across the content width.

    The same strip closes the dashboard overview and the physics stability page;
    only the type size, figure size, and drawn height differ between them.
    """
    draws: tuple[Callable[[Axes], object], ...] = (
        lambda ax: plot_spectrum(ax, curves, fs=fs, spec_outlier=m.spec_outlier),
        lambda ax: plot_outliers(ax, curves, fs=fs),
        lambda ax: plot_motion(ax, curves, fs=fs),
        lambda ax: plot_com(ax, curves, fs=fs),
        lambda ax: plot_psf(ax, curves.psf, fs=fs),
    )
    width = (theme.content_width - (len(draws) - 1) * gap) / len(draws)
    for i, draw in enumerate(draws):
        _draw_plot(c, draw, figsize, theme.margin + i * (width + gap), y, width, height)


def condensed_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Dashboard: header tiles, the phantom-image row, and the core curves."""
    curves, m = artifact.curves, artifact.measurements
    y = _header(c, artifact, title, theme)
    figs = panel_figs(artifact)
    image_width = (theme.content_width - (len(figs) - 1) * 8) / len(figs)
    aspect = max(fig.get_figheight() / fig.get_figwidth() for fig in figs)
    image_h, curve_h, strip_h = dashboard_heights(y, image_width * aspect, theme)
    y = _panel_row(c, figs, y - 6, theme, height=image_h)
    y = _curve_grid(
        c,
        curves,
        m,
        theme,
        y - 10,
        fs=9,
        figsize=(3.6, 2.5),
        row_h=curve_h,
        row_gap=6.0,
    )
    _stability_strip(c, curves, m, theme, y, fs=9, figsize=(3.0, 2.0), height=strip_h)


def analysis_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: the same stability curves at full page size."""
    curves, m = artifact.curves, artifact.measurements
    y = title_baseline(theme)
    c.setFont(theme.font_title, 13)
    c.drawCentredString(
        theme.page_width / 2, y, f"{title} — stability" if title else "stability"
    )
    y = _curve_grid(
        c,
        curves,
        m,
        theme,
        y - 24,
        fs=10,
        figsize=(3.6, 3.0),
        row_h=200.0,
        row_gap=12.0,
    )
    _stability_strip(c, curves, m, theme, y, fs=10, figsize=(3.0, 2.2), height=150.0)


def _page_title(c: canvas.Canvas, title: str, heading: str, theme: Theme) -> float:
    """Draw a physics page heading ("<title> — <heading>"); return the y below."""
    y = title_baseline(theme)
    c.setFont(theme.font_title, 13)
    label = f"{title} — {heading}" if title else heading
    c.drawString(theme.margin, y, label)
    c.setFillGray(theme.text_primary_gray)
    return y - 22


def _draw_prose(
    c: canvas.Canvas, text: str, x: float, y: float, width: float, theme: Theme
) -> float:
    """Draw a wrapped paragraph of catalog prose; return the y below it.

    Sets both the face and the colour rather than inheriting whatever the row
    above left on the canvas, so prose reads the same on every page that draws
    it, and restores the primary fill for the row that follows.
    """
    c.setFont(theme.font_body, 8)
    c.setFillGray(theme.text_muted_gray)
    for line in wrap_text(text, theme.font_body, 8, width):
        c.drawString(x, y, line)
        y -= 10
    c.setFillGray(theme.text_primary_gray)
    return y - 7


def characterization_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: a per-metric table of value, definition, and acceptance window.

    The acceptance column is a placeholder ("--") until the deferred threshold
    subsystem lands; see `notes/report_redesign.md`.
    """
    y = _page_title(c, title, "characterization", theme)
    value_x = theme.margin + 90
    accept_x = theme.page_width - theme.margin
    for doc, value in characterization_rows(artifact.measurements):
        c.setFont(theme.font_title, 9)
        c.setFillGray(theme.text_primary_gray)
        c.drawString(theme.margin, y, doc.label)
        c.setFont(theme.font_numeric, 9)
        c.drawString(value_x, y, value)
        c.setFont(theme.font_body, 7)
        c.setFillGray(theme.text_muted_gray)
        c.drawRightString(accept_x, y, "accept --")
        y -= 11
        y = _draw_prose(
            c, doc.definition, theme.margin + 8, y, theme.content_width - 8, theme
        )


def methods_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: the per-metric methods/provenance narrative."""
    y = _page_title(c, title, "methods", theme)
    for doc in METRIC_DOCS:
        c.setFont(theme.font_title, 9)
        c.setFillGray(theme.text_primary_gray)
        c.drawString(theme.margin, y, doc.label)
        y -= 11
        y = _draw_prose(
            c, doc.method, theme.margin + 8, y, theme.content_width - 8, theme
        )


# One renderer per page `Part` (see `document`). Each draws its content for a
# scan; `packet` finalizes each with `showPage()`.
PART_RENDERERS: dict[Part, PageRenderer] = {
    "overview": condensed_page,
    "characterization": characterization_page,
    "methods": methods_page,
    "stability": analysis_page,
}


def draw_footer(
    c: canvas.Canvas, theme: Theme, page_no: int, total: int, note: str = ""
) -> None:
    """Draw the running footer: brand text left, `note` centred, page number right.

    Suppressed on a single-page report with no footer text and no note, so a
    lone dashboard page stays clean; the page number appears only once a packet
    spans pages. `note` is the packet-level flag (an incomplete packet) that
    must be visible on every page a reader might be handed alone.
    """
    if total <= 1 and not theme.footer and not note:
        return
    y = theme.margin - 22
    c.setFont(theme.font_body, 7.5)
    c.setFillGray(theme.text_muted_gray)
    if theme.footer:
        c.drawString(theme.margin, y, theme.footer)
    if note:
        c.drawCentredString(theme.page_width / 2, y, note)
    if total > 1:
        c.drawRightString(theme.page_width - theme.margin, y, f"{page_no} / {total}")
    c.setFillGray(theme.text_primary_gray)


def cover_page(
    c: canvas.Canvas,
    cover: Cover,
    rows: tuple[CoverRow, ...],
    theme: Theme,
    *,
    continuation: bool,
) -> None:
    """Draw the branded cover: logo, title, optional subtitle, scan inventory.

    The inventory heading counts the scans against those requested when any
    were omitted ("Scans (3 of 5)"), and the omitted ones follow the list under
    their own heading with the reason each was left out.
    """
    cursors = cover_cursors(theme, continuation=continuation)
    cx = theme.page_width / 2
    if cursors.logo is not None:
        logo, logo_y = cursors.logo
        c.drawImage(
            str(logo),
            cx - 60,
            logo_y,
            width=120,
            height=54,
            preserveAspectRatio=True,
            mask="auto",
        )
    c.setFillGray(theme.text_primary_gray)
    c.setFont(theme.font_title, 14 if continuation else 22)
    title = "Scan inventory (continued)" if continuation else theme.cover_title
    c.drawCentredString(cx, cursors.title_y, title)
    if not continuation and cover.subtitle:
        c.setFont(theme.font_body, 12)
        c.setFillGray(theme.text_muted_gray)
        c.drawCentredString(cx, cursors.subtitle_y, cover.subtitle)

    c.setFillGray(theme.text_primary_gray)
    c.setFont(theme.font_title, 11)
    count = str(len(cover.scans))
    if cover.omitted:
        count += f" of {len(cover.scans) + len(cover.omitted)}"
    c.drawString(theme.margin, cursors.heading_y, f"Scans ({count})")
    y = cursors.first_row_y
    for kind, text in rows:
        if kind == "heading":
            c.setFont(theme.font_title, 11)
            c.setFillGray(theme.text_primary_gray)
            c.drawString(theme.margin, y, text)
        else:
            c.setFont(theme.font_body, 10)
            c.setFillGray(theme.text_muted_gray)
            line = fit_text(f"·  {text}", theme.font_body, 10, theme.content_width - 10)
            c.drawString(theme.margin + 10, y, line)
        y -= COVER_ROW_H
    c.setFillGray(theme.text_primary_gray)


def appendix_page(
    c: canvas.Canvas,
    appendix: Appendix,
    rows: tuple[tuple[str, str], ...],
    theme: Theme,
    *,
    continuation: bool,
) -> None:
    """Draw the provenance appendix: the package version and per-scan rows."""
    cursors = appendix_cursors(
        theme, continuation=continuation, has_version=bool(appendix.version)
    )
    c.setFont(theme.font_title, 14)
    title = "Provenance (continued)" if continuation else "Provenance"
    c.drawString(theme.margin, cursors.title_y, title)
    if cursors.version_y is not None:
        c.setFont(theme.font_body, 9)
        c.setFillGray(theme.text_muted_gray)
        c.drawString(
            theme.margin, cursors.version_y, f"fmri-qa-report {appendix.version}"
        )
        c.setFillGray(theme.text_primary_gray)
    y = cursors.first_row_y
    for name, detail in rows:
        c.setFont(theme.font_title, 10)
        c.drawString(
            theme.margin, y, fit_text(name, theme.font_title, 10, theme.content_width)
        )
        y -= APPENDIX_NAME_DROP
        c.setFont(theme.font_body, 8.5)
        c.setFillGray(theme.text_muted_gray)
        c.drawString(
            theme.margin + 10,
            y,
            fit_text(detail, theme.font_body, 8.5, theme.content_width - 10),
        )
        c.setFillGray(theme.text_primary_gray)
        y -= APPENDIX_DETAIL_DROP
