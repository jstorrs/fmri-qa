"""The report document model: tier -> parts composition and its invariants."""

import pytest
from reportlab.pdfbase import pdfmetrics

from fmriqc import report
from fmriqc.report.formats.reportlab import (
    _appendix_chunks,
    _cover_chunks,
    _fit_text,
)


def test_dashboard_is_a_strict_prefix_of_physics() -> None:
    # The design guarantee: physics renders the dashboard parts, then adds more.
    dashboard = report.parts_for("dashboard")
    physics = report.parts_for("physics")
    assert physics[: len(dashboard)] == dashboard
    assert len(physics) > len(dashboard)


def test_every_tier_composes_to_that_tiers_parts() -> None:
    items = [("a", object()), ("b", object())]  # results are opaque to compose
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
    assert tuple(name for chunk in cover_chunks for name in chunk) == scans

    rows = tuple((name, f"details for {name}") for name in scans)
    appendix_chunks = _appendix_chunks(report.Appendix(rows, "0.1.0"), theme)
    assert len(appendix_chunks) > 1
    assert tuple(row for chunk in appendix_chunks for row in chunk) == rows


def test_report_text_is_truncated_to_the_available_width() -> None:
    fitted = _fit_text("a very long scan name" * 20, "Helvetica", 10, 100)
    assert fitted.endswith("...")
    assert pdfmetrics.stringWidth(fitted, "Helvetica", 10) <= 100
