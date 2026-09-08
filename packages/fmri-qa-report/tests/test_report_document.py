"""The report document model: tier -> parts composition and its invariants."""

import pytest
from reportlab.pdfbase import pdfmetrics
from svglib import svglib as _svglib

import fmriqc_report as report
from fmriqc_report import content
from fmriqc_report.formats.reportlab import (
    DEFAULT_THEME,
    _appendix_chunks,
    _cover_chunks,
    _cover_rows,
    _ensure_svglib_patch,
    _fit_text,
    _svglib_truncates_image_geometry,
    _wrap_text,
)


def test_dashboard_is_a_strict_prefix_of_physics() -> None:
    # The design guarantee: physics renders the dashboard parts, then adds more.
    dashboard = report.parts_for("dashboard")
    physics = report.parts_for("physics")
    assert physics[: len(dashboard)] == dashboard
    assert len(physics) > len(dashboard)


def test_every_tier_composes_to_that_tiers_parts() -> None:
    items = [("a", object()), ("b", object())]  # artifacts are opaque to compose
    for tier in report.TIERS:
        sections = report.compose(items, tier)  # type: ignore[arg-type]
        assert [s.title for s in sections] == ["a", "b"]
        assert all(s.parts == report.parts_for(tier) for s in sections)


def test_parts_for_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        report.parts_for("commissioning")  # type: ignore[arg-type]


def test_cover_and_appendix_paginate_without_losing_rows() -> None:
    theme = report.Theme()
    scans = tuple(f"scan-{i:03d}" for i in range(100))
    cover_chunks = _cover_chunks(report.Cover(scans), theme)
    assert len(cover_chunks) > 1
    assert tuple(name for chunk in cover_chunks for _, name in chunk) == scans

    rows = tuple((name, f"details for {name}") for name in scans)
    appendix_chunks = _appendix_chunks(report.Appendix(rows, "0.1.0"), theme)
    assert len(appendix_chunks) > 1
    assert tuple(row for chunk in appendix_chunks for row in chunk) == rows


def test_compose_carries_omitted_scans_onto_the_cover_and_appendix(artifact) -> None:
    """A scan left out of the packet is named in it, with the reason.

    Whoever receives the PDF may never see the terminal that printed the error,
    and a packet of three scans reads as complete unless it says otherwise.
    """
    omitted = [("run-2.qa.npz", "not an fmriqc artifact archive")]
    blocks = report.compose(
        [("run-1", artifact)], "dashboard", cover=True, appendix=True, omitted=omitted
    )
    cover, _, appendix = blocks
    assert isinstance(cover, report.Cover) and isinstance(appendix, report.Appendix)
    assert cover.scans == ("run-1",)
    assert cover.omitted == (("run-2.qa.npz", "not an fmriqc artifact archive"),)
    assert appendix.rows[-1] == (
        "run-2.qa.npz",
        "omitted from this packet: not an fmriqc artifact archive",
    )
    # The cover lists them after the scans, under their own heading.
    kinds = [kind for kind, _ in _cover_rows(cover)]
    assert kinds == ["scan", "heading", "omitted"]


def test_catalog_prose_wraps_within_the_content_width() -> None:
    """A definition or method is wrapped, never truncated, and never overruns.

    The catalog's sentences grew when they were made to describe the code
    exactly; the pages that draw them have no right margin to spill into.
    """
    width = DEFAULT_THEME.content_width - 8
    font = DEFAULT_THEME.font_body
    for doc in content.METRIC_DOCS:
        for text in (doc.definition, doc.method):
            lines = _wrap_text(text, font, 8, width)
            assert " ".join(lines) == text  # every word survives
            for line in lines:
                assert pdfmetrics.stringWidth(line, font, 8) <= width


def test_report_text_is_truncated_to_the_available_width() -> None:
    fitted = _fit_text("a very long scan name" * 20, "Helvetica", 10, 100)
    assert fitted.endswith("...")
    assert pdfmetrics.stringWidth(fitted, "Helvetica", 10) <= 100


def test_svglib_converter_preserves_fractional_image_geometry() -> None:
    """Once the alignment fix is installed, the converter keeps fractional geometry.

    The fix is installed on the first render, not at import, so the test
    installs it explicitly: without that it passed only when a render test had
    already run in the same session, and failed alone.
    """
    _ensure_svglib_patch()
    converter = _svglib.Svg2RlgShapeConverter.convertImage
    assert not _svglib_truncates_image_geometry(converter)


def test_svglib_probe_rejects_an_unknown_converter_shape() -> None:
    def unknown_converter(self, node):
        return object()

    with pytest.raises(RuntimeError, match="unsupported image converter API"):
        _svglib_truncates_image_geometry(unknown_converter)
