"""The ReportLab driver's own machinery: page arithmetic and the svglib fix.

The end-to-end renders live in `test_render.py`; these pin the two things the
driver decides before it draws anything — how much fits on a page, and that the
embedded-image alignment fix is installed and still needed.
"""

from dataclasses import replace
from itertools import pairwise
from typing import get_args

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from svglib import svglib as _svglib

import fmriqc_report as report
from fmriqc_report import content, summary
from fmriqc_report.document import Part
from fmriqc_report.formats.reportlab import pages
from fmriqc_report.formats.reportlab.layout import (
    appendix_chunks,
    appendix_cursors,
    cover_chunks,
    cover_cursors,
    cover_rows,
    fit_text,
    wrap_text,
)
from fmriqc_report.formats.reportlab.pages import (
    PART_RENDERERS,
    appendix_page,
    cover_page,
)
from fmriqc_report.formats.reportlab.svglib_patch import (
    _truncates_image_geometry,
    ensure_installed,
)
from fmriqc_report.theme import DEFAULT_THEME


def test_cover_and_appendix_paginate_without_losing_rows() -> None:
    theme = report.Theme()
    scans = tuple(f"scan-{i:03d}" for i in range(100))
    chunks = cover_chunks(report.Cover(scans), theme)
    assert len(chunks) > 1
    assert tuple(name for chunk in chunks for _, name in chunk) == scans

    rows = tuple((name, f"details for {name}") for name in scans)
    appendix = appendix_chunks(report.Appendix(rows, "0.1.0"), theme)
    assert len(appendix) > 1
    assert tuple(row for chunk in appendix for row in chunk) == rows


SCANS = tuple(f"scan-{i:03d}" for i in range(100))
APPENDIX_ROWS = tuple((name, f"details for {name}") for name in SCANS)


class RecordingCanvas:
    """A stand-in canvas that remembers where a page renderer put things.

    The renderers only place marks, so recording the baseline of every string
    and image is enough to read back what a real render would print — and the
    only way a test can see that the drawer and the measurer agree. The method
    names are ReportLab's, since that is the API the renderers call.
    """

    def __init__(self):
        self.strings = []  # (x, y, text), in the order they were drawn
        self.images = []  # (path, x, y)
        self.text_bounds = []  # (left, bottom, right, top, text)
        self.rectangles = []
        self.font, self.size = "Helvetica", 10

    def setFont(self, font, size):
        self.font, self.size = font, size

    def setStrokeGray(self, gray):
        pass

    def setLineWidth(self, width):
        pass

    def rect(self, x, y, width, height, **kwargs):
        self.rectangles.append((x, y, x + width, y + height))

    def setFillGray(self, gray):
        pass

    def drawString(self, x, y, text):
        self.strings.append((x, y, text))
        width = pdfmetrics.stringWidth(text, self.font, self.size)
        ascent, descent = pdfmetrics.getAscentDescent(self.font, self.size)
        self.text_bounds.append((x, y + descent, x + width, y + ascent, text))

    def drawCentredString(self, x, y, text):
        width = pdfmetrics.stringWidth(text, self.font, self.size)
        self.drawString(x - width / 2, y, text)

    def drawImage(self, path, x, y, **kwargs):
        self.images.append((path, x, y))


def test_the_default_theme_fits_a_known_number_of_cover_rows_per_page() -> None:
    """The pagination of the default letter page, pinned against silent drift.

    The cover's first page is short — its title block sits at 70% of the sheet
    — and its continuations are full.
    """
    chunks = cover_chunks(report.Cover(SCANS), report.Theme())
    assert [len(chunk) for chunk in chunks] == [31, 47, 22]


@pytest.mark.parametrize("version", ["", "1.0"])
def test_the_appendix_version_line_costs_the_default_page_no_row(version: str) -> None:
    """On letter the version line fits in the slack above the first row's pitch."""
    chunks = appendix_chunks(report.Appendix(APPENDIX_ROWS, version), report.Theme())
    assert [len(chunk) for chunk in chunks] == [21, 21, 21, 21, 16]


def test_the_default_theme_puts_each_block_at_a_known_height() -> None:
    """The baselines the cover and appendix draw on, first page and continuation."""
    theme = report.Theme()

    first = cover_cursors(theme, continuation=False)
    assert first.logo is None  # the default theme has no logo
    assert (first.title_y, first.subtitle_y) == pytest.approx((554.4, 528.4))
    assert (first.heading_y, first.first_row_y) == pytest.approx((488.4, 472.4))
    following = cover_cursors(theme, continuation=True)
    assert (following.title_y, following.first_row_y) == pytest.approx((758.0, 704.0))
    assert first.floor == 50.0
    assert following.floor == 50.0

    bare = appendix_cursors(theme, continuation=False, has_version=False)
    assert bare.version_y is None
    assert (bare.title_y, bare.first_row_y) == pytest.approx((758.0, 738.0))
    versioned = appendix_cursors(theme, continuation=False, has_version=True)
    assert versioned.version_y == pytest.approx(738.0)
    assert versioned.first_row_y == pytest.approx(718.0)
    # A continuation repeats the title but not the version line.
    carried = appendix_cursors(theme, continuation=True, has_version=True)
    assert carried.version_y is None
    assert carried.first_row_y == pytest.approx(738.0)
    assert bare.floor == 55.0


def test_a_cover_logo_lowers_the_title_block_and_costs_the_first_page_rows(
    tmp_path,
) -> None:
    """A themed logo pushes the first page's inventory down by its own height.

    The drop is taken only for a logo that is really there, so the measurement
    reads the file system; a theme naming a file that does not exist paginates
    like a theme naming none.
    """
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"")
    theme = report.Theme(logo=logo)

    first = cover_cursors(theme, continuation=False)
    assert first.logo == (logo, pytest.approx(554.4))
    assert (first.title_y, first.subtitle_y) == pytest.approx((536.4, 510.4))
    assert (first.heading_y, first.first_row_y) == pytest.approx((470.4, 454.4))
    assert first.floor == 50.0
    # Only a first page carries the logo; continuations are as they ever were.
    following = cover_cursors(theme, continuation=True)
    assert following.logo is None
    assert following.first_row_y == pytest.approx(704.0)

    assert [len(chunk) for chunk in cover_chunks(report.Cover(SCANS), theme)] == [
        29,
        47,
        24,
    ]
    missing = report.Theme(logo=tmp_path / "absent.png")
    assert cover_cursors(missing, continuation=False).logo is None


@pytest.mark.parametrize("logo", [False, True])
def test_the_cover_draws_every_row_the_chunker_put_on_the_page(
    tmp_path, logo: bool
) -> None:
    """Every inventory row a page is given lands on it, above the block's floor.

    ReportLab writes below the bottom edge without complaint, so a drawer that
    started lower than the chunker counted from would push rows off the sheet
    silently. Driving the real renderer is what says the two still agree.
    """
    if logo:
        (tmp_path / "logo.png").write_bytes(b"")
    theme = report.Theme(logo=tmp_path / "logo.png" if logo else None)
    cover = report.Cover(SCANS)

    chunks = cover_chunks(cover, theme)
    assert len(chunks) > 1  # a single page would prove nothing about continuations
    for index, chunk in enumerate(chunks):
        continuation = index > 0
        cursors = cover_cursors(theme, continuation=continuation)
        c = RecordingCanvas()
        cover_page(c, cover, chunk, theme, continuation=continuation)

        # The title and the "Scans (n)" heading, then one line per row.
        title_y, heading_y, *row_ys = [y for _, y, _ in c.strings]
        assert title_y == pytest.approx(cursors.title_y)
        assert heading_y == pytest.approx(cursors.heading_y)
        assert len(row_ys) == len(chunk)
        assert row_ys[0] == pytest.approx(cursors.first_row_y)
        assert min(row_ys) >= cursors.floor
        assert [y for _, _, y in c.images] == (
            [pytest.approx(cursors.logo[1])] if cursors.logo else []
        )


@pytest.mark.parametrize("version", ["", "1.0"])
def test_the_appendix_draws_every_row_the_chunker_put_on_the_page(version: str) -> None:
    """Every provenance row a page is given lands on it, above the block's floor.

    A row is a name line with its detail line beneath, and the floor bounds the
    name: the detail hangs below it into the footer's slack by design.
    """
    theme = report.Theme()
    appendix = report.Appendix(APPENDIX_ROWS, version)

    chunks = appendix_chunks(appendix, theme)
    assert len(chunks) > 1
    for index, chunk in enumerate(chunks):
        continuation = index > 0
        cursors = appendix_cursors(
            theme, continuation=continuation, has_version=bool(version)
        )
        c = RecordingCanvas()
        appendix_page(c, appendix, chunk, theme, continuation=continuation)

        ys = [y for _, y, _ in c.strings]
        assert ys[0] == pytest.approx(cursors.title_y)
        header = 1
        if cursors.version_y is not None:
            assert ys[1] == pytest.approx(cursors.version_y)
            header = 2
        name_ys = ys[header::2]  # each row draws its name, then its detail
        assert len(name_ys) == len(chunk)
        assert name_ys[0] == pytest.approx(cursors.first_row_y)
        assert min(name_ys) >= cursors.floor


def test_the_cover_lists_omitted_scans_under_their_own_heading() -> None:
    cover = report.Cover(("run-1",), omitted=(("run-2.qa.nc", "unreadable"),))
    assert [kind for kind, _ in cover_rows(cover)] == ["scan", "heading", "omitted"]


def test_catalog_prose_wraps_within_the_content_width() -> None:
    """A definition or method is wrapped, never truncated, and never overruns.

    The catalog's sentences grew when they were made to describe the code
    exactly; the pages that draw them have no right margin to spill into.
    """
    width = DEFAULT_THEME.content_width - 8
    font = DEFAULT_THEME.font_body
    for doc in content.METRIC_DOCS:
        for text in (doc.definition, doc.method):
            lines = wrap_text(text, font, 8, width)
            assert " ".join(lines) == text  # every word survives
            for line in lines:
                assert pdfmetrics.stringWidth(line, font, 8) <= width


def test_report_text_is_truncated_to_the_available_width() -> None:
    fitted = fit_text("a very long scan name" * 20, "Helvetica", 10, 100)
    assert fitted.endswith("...")
    assert pdfmetrics.stringWidth(fitted, "Helvetica", 10) <= 100


def test_every_page_part_has_a_renderer() -> None:
    """The renderer table covers exactly the parts a document can name.

    `PART_RENDERERS` is a `dict[Part, PageRenderer]`, but that annotation does
    not enforce totality: neither mypy nor pyright flags a missing Literal key.
    A `Part` added without a renderer would be a `KeyError` at render time, and
    a stale key left in the table would be a renderer nothing reaches.
    """
    assert set(PART_RENDERERS) == set(get_args(Part))


def test_svglib_converter_preserves_fractional_image_geometry() -> None:
    """Once the alignment fix is installed, the converter keeps fractional geometry.

    The fix is installed on the first render, not at import, so the test
    installs it explicitly: without that it passed only when a render test had
    already run in the same session, and failed alone.
    """
    ensure_installed()
    converter = _svglib.Svg2RlgShapeConverter.convertImage
    assert not _truncates_image_geometry(converter)


def test_svglib_probe_rejects_an_unknown_converter_shape() -> None:
    def unknown_converter(self, node):
        return object()

    with pytest.raises(RuntimeError, match="unsupported image converter API"):
        _truncates_image_geometry(unknown_converter)


@pytest.mark.parametrize(
    "theme",
    [
        report.Theme(footer="Physics"),
        report.Theme(
            page_size=A4, margin=24, font_body="Times-Roman", footer="Physics"
        ),
    ],
)
@pytest.mark.parametrize("warnings", [False, True])
def test_dashboard_text_tiles_and_panels_fit_one_page(
    artifact, monkeypatch, theme, warnings
) -> None:
    if warnings:
        artifact = replace(
            artifact,
            measurements=replace(
                artifact.measurements,
                clipped_any=True,
                clipped_kept=True,
                n_clipped_kept=12,
                n_clipped_pre=3,
                clip_ceiling=4095,
                clip_bits=12,
                phantom_mask_ok=False,
                roi_inside_phantom=False,
            ),
            provenance=replace(
                artifact.provenance,
                model="Research scanner with a long device model name " * 2,
                coil="Head receive array with many channels " * 2,
                software="Extended research software release " * 3,
            ),
        )
    title = "scan_" + "long_identifier_" * 8 if warnings else "scan"
    boxes = []
    monkeypatch.setattr(
        pages,
        "_draw_fig",
        lambda c, fig, x, top, w, h: boxes.append((x, top - h, x + w, top)),
    )
    c = RecordingCanvas()
    pages.condensed_page(c, artifact, title, theme)
    for left, bottom, right, top, _text in c.text_bounds:
        assert theme.margin <= left < right <= theme.page_width - theme.margin
        assert theme.margin <= bottom < top <= theme.page_height
    tile_text = c.text_bounds[-2 * len(content.metric_tiles(artifact.measurements)) :]
    assert len({bottom for _, bottom, _, _ in c.rectangles}) > 1
    for bounds, value, label in zip(
        c.rectangles, tile_text[::2], tile_text[1::2], strict=True
    ):
        left, bottom, right, top = bounds
        for tx0, ty0, tx1, ty1, _ in (value, label):
            assert left < tx0 < tx1 < right
            assert bottom < ty0 < ty1 < top
    assert [
        (label[-1], value[-1])
        for value, label in zip(tile_text[::2], tile_text[1::2], strict=True)
    ] == content.metric_tiles(artifact.measurements)
    header_text = c.text_bounds[: -len(tile_text)]
    for upper, lower in pairwise(header_text):
        assert upper[1] > lower[3]
    assert header_text[-1][1] > max(top for _, _, _, top in c.rectangles)
    rendered = "".join(text for _, _, text in c.strings)
    for text in (
        title,
        summary.device_line(artifact.provenance),
        summary.acquisition_line(artifact),
        summary.provenance_line(artifact.provenance),
        summary.acquisition_notes(artifact),
    ):
        assert "".join(text.split()) in "".join(rendered.split())
    assert min(bottom for _, bottom, _, _ in boxes) >= theme.margin - 1e-9
    assert max(top for _, _, _, top in boxes) < min(
        bottom for _, bottom, _, _ in c.rectangles
    )
    row_tops = sorted({top for _, _, _, top in boxes}, reverse=True)
    assert len(row_tops) == 4  # images, two curve rows, stability strip
    for upper, lower in pairwise(row_tops):
        assert min(bottom for _, bottom, _, top in boxes if top == upper) > lower
