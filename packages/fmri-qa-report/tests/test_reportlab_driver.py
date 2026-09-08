"""The ReportLab driver's own machinery: page arithmetic and the svglib fix.

The end-to-end renders live in `test_render.py`; these pin the two things the
driver decides before it draws anything — how much fits on a page, and that the
embedded-image alignment fix is installed and still needed.
"""

import pytest
from reportlab.pdfbase import pdfmetrics
from svglib import svglib as _svglib

import fmriqc_report as report
from fmriqc_report import content
from fmriqc_report.formats.reportlab.layout import (
    appendix_chunks,
    cover_chunks,
    cover_rows,
    fit_text,
    wrap_text,
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


def test_the_cover_lists_omitted_scans_under_their_own_heading() -> None:
    cover = report.Cover(("run-1",), omitted=(("run-2.qa.npz", "unreadable"),))
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
