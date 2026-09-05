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
import os
import tempfile
from collections.abc import Callable, Iterable
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import matplotlib
from matplotlib.figure import Figure
from reportlab.graphics.shapes import Group, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from svglib import svglib as _svglib
from svglib.svglib import svg2rlg

from fmriqc.analysis import Curves, Measurements, QAArtifact

from ..content import METRIC_DOCS, characterization_rows, metric_tiles
from ..document import (
    Appendix,
    Block,
    Cover,
    Part,
    ScanSection,
    Tier,
    compose,
    parts_for,
)
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
)
from ..summary import (
    _acquisition_line,
    _device_line,
    _provenance_line,
)
from ..theme import DEFAULT_THEME, Theme

# A page-part renderer: draw one scan's part onto the canvas (no showPage).
PageRenderer = Callable[[canvas.Canvas, QAArtifact, str, Theme], None]

_TILE_H = 34.0  # metric-tile height (pt)
_TILE_GAP = 6.0
_COVER_ROW_H = 14.0
_APPENDIX_ROW_H = 33.0
_ImageConverter = Callable[[Any, Any], Any]


def _fit_text(text: str, font: str, size: float, width: float) -> str:
    """Truncate one-line report text to ``width``, preserving an ellipsis."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    ellipsis = "..."
    available = width - pdfmetrics.stringWidth(ellipsis, font, size)
    if available <= 0:
        return ""
    end = len(text)
    while end > 0 and pdfmetrics.stringWidth(text[:end], font, size) > available:
        end -= 1
    return text[:end].rstrip() + ellipsis


def _page_chunks[T](
    rows: tuple[T, ...], first_capacity: int, next_capacity: int
) -> list[tuple[T, ...]]:
    """Split rows across a differently sized first page and continuation pages."""
    first_capacity = max(first_capacity, 1)
    next_capacity = max(next_capacity, 1)
    chunks = [rows[:first_capacity]]
    offset = first_capacity
    while offset < len(rows):
        chunks.append(rows[offset : offset + next_capacity])
        offset += next_capacity
    return chunks


def _cover_chunks(cover: Cover, theme: Theme) -> list[tuple[str, ...]]:
    """Paginate a cover inventory for the active page geometry."""
    y = theme.page_size[1] * 0.70
    if theme.logo is not None and theme.logo.is_file():
        y -= 18
    y -= 26
    y -= 40
    y -= 16
    floor = theme.margin + 10
    first = int((y - floor) // _COVER_ROW_H) + 1
    continuation_y = theme.page_size[1] - 34 - 22 - 16 - 16
    following = int((continuation_y - floor) // _COVER_ROW_H) + 1
    return _page_chunks(cover.scans, first, following)


def _appendix_chunks(
    appendix: Appendix, theme: Theme
) -> list[tuple[tuple[str, str], ...]]:
    """Paginate provenance rows above the running-footer area."""
    y = theme.page_size[1] - 34 - 20
    if appendix.version:
        y -= 20
    floor = theme.margin + 15
    first = int((y - floor) // _APPENDIX_ROW_H) + 1
    continuation_y = theme.page_size[1] - 34 - 20
    following = int((continuation_y - floor) // _APPENDIX_ROW_H) + 1
    return _page_chunks(appendix.rows, first, following)


def _svglib_truncates_image_geometry(convert_image: _ImageConverter) -> bool:
    """Probe a converter, returning whether it truncates fractional geometry."""

    class ProbeConverter:
        @staticmethod
        def convert_length_attrs(*args: object) -> tuple[float, float, float, float]:
            return (0.25, 1.25, 2.5, 3.5)

    node = SimpleNamespace(_resolved_target="alignment-probe")
    try:
        group = convert_image(ProbeConverter(), node)
        image = group.contents[0]
        geometry = (image.x, image.y, image.width, image.height)
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"svglib {version('svglib')} has an unsupported image converter API"
        ) from exc

    if geometry == (0.25, 4.75, 2.5, 3.5):
        return False
    if geometry == (0, 4, 2, 3):
        return True
    raise RuntimeError(
        f"svglib {version('svglib')} returned unexpected image geometry {geometry!r}"
    )


def _patch_svglib_image_alignment() -> None:
    """Fix svglib truncating embedded-image geometry to whole points.

    svglib's `convertImage` builds the ReportLab `Image` from `int(x)`,
    `int(y + height)`, `int(width)`, `int(height)` while flipping the enclosing
    group by the *un*-truncated `(y + height) * 2`. For an `imshow` panel the
    raster then lands up to a point off from the mask contour and ROI box (which
    keep full precision), so the phantom outline visibly drifts off the image.
    The converter is behavior-probed before patching. A future svglib that keeps
    fractional geometry needs no patch; an unknown private API fails clearly
    instead of silently misaligning the raster and vector layers. The dependency
    range is capped in `pyproject.toml` until a newer release is verified.
    """

    original = _svglib.Svg2RlgShapeConverter.convertImage
    if not _svglib_truncates_image_geometry(original):
        return

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

    if _svglib_truncates_image_geometry(convertImage):
        raise RuntimeError("failed to install the svglib image-alignment fix")


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


def _header(c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme) -> float:
    """Draw the scan name, metadata lines, and metric tiles; return the y below."""
    page_w, page_h = theme.page_size
    y = page_h - 32
    if title:
        c.setFont(theme.font_title, 14)
        c.drawString(theme.margin, y, title)
    device = _device_line(artifact.provenance)
    if device:
        c.setFont(theme.font_body, 9)
        c.setFillGray(theme.text_muted_gray)
        c.drawRightString(page_w - theme.margin, y, device)
    if title or device:
        y -= 14

    c.setFont(theme.font_body, 8.3)
    c.setFillGray(theme.text_muted_gray)
    c.drawString(theme.margin, y, _acquisition_line(artifact))
    prov = _provenance_line(artifact.provenance)
    if prov:
        y -= 11
        c.drawString(theme.margin, y, prov)
    c.setFillGray(theme.text_primary_gray)

    bottom = _draw_tiles(c, metric_tiles(artifact.measurements), y - 12, theme)
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
    draws: tuple[Callable[[Any], object], ...] = (
        lambda ax: _plot_spectrum(ax, curves, fs=fs, spec_outlier=m.spec_outlier),
        lambda ax: _plot_outliers(ax, curves, fs=fs),
        lambda ax: _plot_motion(ax, curves, fs=fs),
        lambda ax: _plot_com(ax, curves, fs=fs),
        lambda ax: _plot_psf(ax, curves.psf, fs=fs),
    )
    width = (theme.content_width - (len(draws) - 1) * gap) / len(draws)
    for i, draw in enumerate(draws):
        _draw_fig(
            c,
            _plot_fig(draw, figsize),
            theme.margin + i * (width + gap),
            y,
            width,
            height,
        )


def _condensed_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Dashboard: header tiles, the phantom-image row, and the core curves."""
    curves, m = artifact.curves, artifact.measurements
    wk = curves.weisskoff
    y = _header(c, artifact, title, theme)
    y = _panel_row(c, _panel_figs(artifact), y - 6, theme)

    gap, row_h = 16.0, 150.0
    half = (theme.content_width - gap) / 2

    y -= 10
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk, m.rdc), (3.6, 2.5)),
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

    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, curves), (3.6, 2.5)),
        theme.margin,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_residual(ax, curves, tc_outlier=m.tc_outlier), (3.6, 2.5)
        ),
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 6

    _stability_strip(c, curves, m, theme, y, fs=9, figsize=(3.0, 2.0), height=120.0)


def _analysis_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: the same stability curves at full page size."""
    curves, m = artifact.curves, artifact.measurements
    wk = curves.weisskoff

    page_w, page_h = theme.page_size
    y = page_h - 34
    c.setFont(theme.font_title, 13)
    c.drawCentredString(page_w / 2, y, f"{title} — stability" if title else "stability")
    y -= 24

    gap, row_h = 16.0, 200.0
    half = (theme.content_width - gap) / 2
    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_weisskoff(ax, wk, m.rdc, fs=10), (3.6, 3.0)),
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

    _draw_fig(
        c,
        _plot_fig(lambda ax: _plot_signal(ax, curves, fs=10), (3.6, 3.0)),
        theme.margin,
        y,
        half,
        row_h,
    )
    _draw_fig(
        c,
        _plot_fig(
            lambda ax: _plot_residual(ax, curves, fs=10, tc_outlier=m.tc_outlier),
            (3.6, 3.0),
        ),
        theme.margin + half + gap,
        y,
        half,
        row_h,
    )
    y -= row_h + 12

    _stability_strip(c, curves, m, theme, y, fs=10, figsize=(3.0, 2.2), height=150.0)


def _page_title(c: canvas.Canvas, title: str, heading: str, theme: Theme) -> float:
    """Draw a physics page heading ("<title> — <heading>"); return the y below."""
    y = theme.page_size[1] - 34
    c.setFont(theme.font_title, 13)
    label = f"{title} — {heading}" if title else heading
    c.drawString(theme.margin, y, label)
    c.setFillGray(theme.text_primary_gray)
    return y - 22


def _characterization_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: a per-metric table of value, definition, and acceptance window.

    The acceptance column is a placeholder ("--") until the deferred threshold
    subsystem lands; see `notes/report_redesign.md`.
    """
    y = _page_title(c, title, "characterization", theme)
    value_x = theme.margin + 90
    accept_x = theme.page_size[0] - theme.margin
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
        c.setFont(theme.font_body, 8)
        c.drawString(theme.margin + 8, y, doc.definition)
        c.setFillGray(theme.text_primary_gray)
        y -= 17


def _methods_page(
    c: canvas.Canvas, artifact: QAArtifact, title: str, theme: Theme
) -> None:
    """Physics: the per-metric methods/provenance narrative."""
    y = _page_title(c, title, "methods", theme)
    for doc in METRIC_DOCS:
        c.setFont(theme.font_title, 9)
        c.setFillGray(theme.text_primary_gray)
        c.drawString(theme.margin, y, doc.label)
        y -= 11
        c.setFont(theme.font_body, 8)
        c.setFillGray(theme.text_muted_gray)
        c.drawString(theme.margin + 8, y, doc.method)
        c.setFillGray(theme.text_primary_gray)
        y -= 17


# One renderer per page `Part` (see `report.document`). Each draws its content
# for a scan; `add_report_pages` finalizes each with `showPage()`.
_PART_RENDERERS: dict[Part, PageRenderer] = {
    "overview": _condensed_page,
    "characterization": _characterization_page,
    "methods": _methods_page,
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
            _PART_RENDERERS[part](c, section.artifact, section.title, theme)
            c.showPage()
    return len(section.parts)


def add_report_pages(
    c: canvas.Canvas,
    artifact: QAArtifact,
    title: str = "",
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
) -> int:
    """Draw a scan's report page(s) onto an open ReportLab `Canvas`.

    `tier="dashboard"` renders the single condensed overview page; `tier="physics"`
    renders that overview and then a full-size stability page. Each page is
    finalized with `showPage()`. Returns the number of pages drawn. This is the
    per-scan primitive with no packet furniture; `write_report` adds the cover,
    appendix, and page footers.
    """
    return _render_section(c, ScanSection(title, artifact, parts_for(tier)), theme)


def _draw_footer(c: canvas.Canvas, theme: Theme, page_no: int, total: int) -> None:
    """Draw the running footer: brand text at the left, page number at the right.

    Suppressed on a single-page report with no footer text, so a lone dashboard
    page stays clean; the page number appears only once a packet spans pages.
    """
    if total <= 1 and not theme.footer:
        return
    y = theme.margin - 22
    c.setFont(theme.font_body, 7.5)
    c.setFillGray(theme.text_muted_gray)
    if theme.footer:
        c.drawString(theme.margin, y, theme.footer)
    if total > 1:
        c.drawRightString(theme.page_size[0] - theme.margin, y, f"{page_no} / {total}")
    c.setFillGray(theme.text_primary_gray)


def _cover_page(
    c: canvas.Canvas,
    cover: Cover,
    scans: tuple[str, ...],
    theme: Theme,
    *,
    continuation: bool,
) -> None:
    """Draw the branded cover: logo, title, optional subtitle, scan inventory."""
    page_w, page_h = theme.page_size
    cx = page_w / 2
    y = page_h - 34 if continuation else page_h * 0.70
    if not continuation and theme.logo is not None and theme.logo.is_file():
        c.drawImage(
            str(theme.logo),
            cx - 60,
            y,
            width=120,
            height=54,
            preserveAspectRatio=True,
            mask="auto",
        )
        y -= 18
    c.setFillGray(theme.text_primary_gray)
    c.setFont(theme.font_title, 14 if continuation else 22)
    title = "Scan inventory (continued)" if continuation else theme.cover_title
    c.drawCentredString(cx, y, title)
    y -= 22 if continuation else 26
    if not continuation and cover.subtitle:
        c.setFont(theme.font_body, 12)
        c.setFillGray(theme.text_muted_gray)
        c.drawCentredString(cx, y, cover.subtitle)
    y -= 16 if continuation else 40

    c.setFillGray(theme.text_primary_gray)
    c.setFont(theme.font_title, 11)
    c.drawString(theme.margin, y, f"Scans ({len(cover.scans)})")
    y -= 16
    c.setFont(theme.font_body, 10)
    c.setFillGray(theme.text_muted_gray)
    for name in scans:
        line = _fit_text(f"·  {name}", theme.font_body, 10, theme.content_width - 10)
        c.drawString(theme.margin + 10, y, line)
        y -= _COVER_ROW_H
    c.setFillGray(theme.text_primary_gray)


def _appendix_page(
    c: canvas.Canvas,
    appendix: Appendix,
    rows: tuple[tuple[str, str], ...],
    theme: Theme,
    *,
    continuation: bool,
) -> None:
    """Draw the provenance appendix: the package version and per-scan rows."""
    y = theme.page_size[1] - 34
    c.setFont(theme.font_title, 14)
    title = "Provenance (continued)" if continuation else "Provenance"
    c.drawString(theme.margin, y, title)
    y -= 20
    if appendix.version and not continuation:
        c.setFont(theme.font_body, 9)
        c.setFillGray(theme.text_muted_gray)
        c.drawString(theme.margin, y, f"fmri-qa-report {appendix.version}")
        c.setFillGray(theme.text_primary_gray)
        y -= 20
    for name, detail in rows:
        c.setFont(theme.font_title, 10)
        c.drawString(
            theme.margin,
            y,
            _fit_text(name, theme.font_title, 10, theme.content_width),
        )
        y -= 13
        c.setFont(theme.font_body, 8.5)
        c.setFillGray(theme.text_muted_gray)
        c.drawString(
            theme.margin + 10,
            y,
            _fit_text(detail, theme.font_body, 8.5, theme.content_width - 10),
        )
        c.setFillGray(theme.text_primary_gray)
        y -= 20


def _block_pages(block: Block, theme: Theme) -> int:
    """How many pages a block draws: its parts for a scan, else one."""
    if isinstance(block, ScanSection):
        return len(block.parts)
    if isinstance(block, Cover):
        return len(_cover_chunks(block, theme))
    return len(_appendix_chunks(block, theme))


def _render_block(
    c: canvas.Canvas, block: Block, theme: Theme, page_no: int, total: int
) -> int:
    """Draw one block; return the running page number after it.

    The cover carries no footer (it reads as a title page); every other page
    gets the running footer.
    """
    if isinstance(block, Cover):
        for index, scans in enumerate(_cover_chunks(block, theme)):
            _cover_page(c, block, scans, theme, continuation=index > 0)
            c.showPage()
            page_no += 1
        return page_no
    if isinstance(block, Appendix):
        for index, rows in enumerate(_appendix_chunks(block, theme)):
            page_no += 1
            _appendix_page(c, block, rows, theme, continuation=index > 0)
            _draw_footer(c, theme, page_no, total)
            c.showPage()
        return page_no
    with matplotlib.rc_context(cast("Any", theme.rc_params())):
        for part in block.parts:
            page_no += 1
            _PART_RENDERERS[part](c, block.artifact, block.title, theme)
            _draw_footer(c, theme, page_no, total)
            c.showPage()
    return page_no


def write_report(
    items: Iterable[tuple[str, QAArtifact]] | QAArtifact,
    pdf_path: str | Path,
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
    *,
    cover: bool = False,
    appendix: bool = False,
) -> int:
    """Write a combined PDF packet: optional cover, the scans, optional appendix.

    `items` is an iterable of `(title, QAArtifact)`, or a single `QAArtifact`.
    `cover` prepends a branded cover with the scan inventory; `appendix` appends
    a provenance page. Multi-page packets carry a running footer with the theme's
    brand text and page numbers. Returns the total number of pages written.
    """
    if isinstance(items, QAArtifact):
        items = [("", items)]
    blocks = compose(items, tier, cover=cover, appendix=appendix)
    total = sum(_block_pages(b, theme) for b in blocks)
    target = Path(pdf_path)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        c = canvas.Canvas(str(temporary), pagesize=theme.page_size)
        page_no = 0
        for block in blocks:
            page_no = _render_block(c, block, theme, page_no, total)
        c.save()
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return total
