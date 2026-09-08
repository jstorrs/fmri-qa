"""End-to-end rendering: an artifact in, a real PDF out.

These exercise the whole presentation stack the unit tests skip — the summary
text, both panel families, and the ReportLab driver's composition — plus the
guarantees around writing the file itself.
"""

from dataclasses import replace

import numpy as np
import pytest

import fmriqc as q
import fmriqc_report as report


def test_dashboard_renders_one_page_per_scan(tmp_path, artifact) -> None:
    pdf = tmp_path / "qa.pdf"
    pages = report.write_report([("scan", artifact)], pdf)
    assert pages == 1
    assert pdf.read_bytes().startswith(b"%PDF")


def test_physics_tier_renders_every_part(tmp_path, artifact) -> None:
    pdf = tmp_path / "qa-physics.pdf"
    pages = report.write_report([("scan", artifact)], pdf, tier="physics")
    assert pages == len(report.parts_for("physics"))
    assert pdf.read_bytes().startswith(b"%PDF")


def test_a_scan_without_a_sidecar_still_renders(tmp_path, bare_artifact) -> None:
    """Every acquisition field is optional, so the header must degrade cleanly."""
    pdf = tmp_path / "bare.pdf"
    pages = report.write_report([("bare", bare_artifact)], pdf, appendix=True)
    assert pages == 2
    assert pdf.read_bytes().startswith(b"%PDF")


def test_a_reloaded_artifact_renders_identically(tmp_path, artifact) -> None:
    """The seam's payoff: a saved artifact is as good as a freshly computed one."""
    reloaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "qa.npz"))
    live_pages = report.write_report([("scan", artifact)], tmp_path / "live.pdf")
    disk_pages = report.write_report([("scan", reloaded)], tmp_path / "disk.pdf")
    assert live_pages == disk_pages == 1
    assert (tmp_path / "disk.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("failed", [0, 1, 38])
def test_motion_panel_marks_unresolved_frames(artifact, failed) -> None:
    from matplotlib.figure import Figure

    from fmriqc_report.panels.timeseries import _plot_motion

    translation = np.zeros_like(artifact.curves.translation)
    translation[:failed] = np.nan
    curves = replace(
        artifact.curves,
        translation=translation,
        scale_pct=np.zeros_like(artifact.curves.scale_pct),
        shear_pct=np.zeros_like(artifact.curves.shear_pct),
    )
    ax = Figure().add_subplot(111)
    _plot_motion(ax, curves)
    assert [t.get_text() for t in ax.texts] == (
        [f"{failed}/38 frames unresolved"] if failed else []
    )


def test_write_report_honours_a_custom_theme(tmp_path, artifact) -> None:
    from reportlab.lib.pagesizes import A4

    theme = report.Theme(
        page_size=A4,
        margin=24.0,
        font_body="Times-Roman",
        panel_cmap="magma",
        panel_accent="#8e44ad",
        panel_font_family="serif",
    )
    pdf = tmp_path / "themed.pdf"
    pages = report.write_report([("scan", artifact)], pdf, theme=theme)
    assert pages == 1
    assert pdf.read_bytes().startswith(b"%PDF")


def test_write_report_preserves_destination_on_render_failure(
    tmp_path, artifact, monkeypatch
) -> None:
    from fmriqc_report.formats import reportlab as driver

    pdf = tmp_path / "existing.pdf"
    pdf.write_bytes(b"existing report")

    def fail_render(*args, **kwargs) -> int:
        raise RuntimeError("injected render failure")

    monkeypatch.setattr(driver, "_render_block", fail_render)
    with pytest.raises(RuntimeError, match="injected"):
        report.write_report([("scan", artifact)], pdf)
    assert pdf.read_bytes() == b"existing report"
    assert not list(tmp_path.glob(".existing.pdf.*"))


def test_write_report_builds_a_cover_and_appendix_packet(tmp_path, artifact) -> None:
    items = [("run-1", artifact), ("run-2", artifact)]
    theme = report.Theme(footer="Test MR Physics")
    pdf = tmp_path / "packet.pdf"
    # cover + two dashboard pages + appendix.
    pages = report.write_report(
        items, pdf, tier="dashboard", theme=theme, cover=True, appendix=True
    )
    assert pages == 4
    assert pdf.read_bytes().startswith(b"%PDF")


def test_write_report_marks_an_incomplete_packet(tmp_path, artifact) -> None:
    """A packet missing a requested scan says so where a reader will look.

    The subject metadata is the part of the file this test can read back
    without a PDF parser; the cover, appendix row, and every page footer carry
    the same fact and are rendered here without error.
    """
    pdf = tmp_path / "partial.pdf"
    pages = report.write_report(
        [("run-1", artifact)],
        pdf,
        cover=True,
        appendix=True,
        omitted=[("run-2.qa.npz", "unreadable")],
    )
    assert pages == 3  # cover + one dashboard page + appendix
    assert b"1 of 2 scans; 1 omitted" in pdf.read_bytes()

    whole = tmp_path / "whole.pdf"
    report.write_report([("run-1", artifact)], whole)
    assert b"omitted" not in whole.read_bytes()


def test_cover_renders_a_theme_logo(tmp_path, artifact) -> None:
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGB", (8, 4), color=(10, 77, 122)).save(logo)

    theme = report.Theme(logo=logo, cover_title="Site QA", footer="Physics")
    pdf = tmp_path / "logo_packet.pdf"
    pages = report.write_report([("scan", artifact)], pdf, theme=theme, cover=True)
    assert pages == 2  # cover + one dashboard page
    assert pdf.read_bytes().startswith(b"%PDF")


def test_add_report_pages_accepts_a_bare_artifact(tmp_path, artifact) -> None:
    """The per-scan primitive, with no packet furniture around it."""
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "pages.pdf"
    c = canvas.Canvas(str(pdf), pagesize=report.DEFAULT_THEME.page_size)
    assert report.add_report_pages(c, artifact, "scan") == 1
    c.save()
    assert pdf.read_bytes().startswith(b"%PDF")
