"""End-to-end rendering: an artifact in, a real PDF out.

These exercise the whole presentation stack the unit tests skip — the summary
text, both panel families, and the ReportLab driver's composition — plus the
guarantees around writing the file itself.
"""

import os
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest

import fmriqc as q
import fmriqc_report as report


def test_importing_the_package_leaves_the_matplotlib_backend_alone() -> None:
    """A library must not change a process-global its importer chose.

    `fmriqc_report` used to call `matplotlib.use("Agg")` at import time,
    silently overriding whatever backend the importing process had already
    selected (e.g. a notebook's inline backend). Run in a fresh interpreter
    with a non-default, display-free backend set via `MPLBACKEND`, so the
    probe reflects only this process's import, not whatever other tests have
    already done to `matplotlib`'s global state.
    """
    code = (
        "import matplotlib\n"
        "before = matplotlib.get_backend()\n"
        "import fmriqc_report\n"
        "after = matplotlib.get_backend()\n"
        "print(before)\n"
        "print(after)\n"
    )
    env = dict(os.environ, MPLBACKEND="svg")
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    before, after = result.stdout.strip().splitlines()
    assert before.lower() == after.lower() == "svg"


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
    reloaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "qa.nc"))
    live_pages = report.write_report([("scan", artifact)], tmp_path / "live.pdf")
    disk_pages = report.write_report([("scan", reloaded)], tmp_path / "disk.pdf")
    assert live_pages == disk_pages == 1
    assert (tmp_path / "disk.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("tier", ["dashboard", "physics"])
def test_blank_scan_with_unresolved_rdc_renders_after_reload(tmp_path, tier) -> None:
    artifact = q.analyze(
        q.QAScan(data=np.zeros((16, 16, 1, 10)), tr=2.0, pe_axis=1),
        q.AnalysisSettings(roi_size=3, trim_sec=0, detrend_order=0),
    )
    reloaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "blank.nc"))
    assert not np.isfinite(reloaded.curves.weisskoff.rdc).any()
    pdf = tmp_path / "blank.pdf"
    pages = report.write_report([("blank", reloaded)], pdf, tier=tier)
    assert pages == len(report.parts_for(tier))
    assert pdf.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize(
    ("values", "maximum", "upper", "unresolved"),
    [
        pytest.param([np.nan, np.nan, np.nan], None, 4.5, 3, id="nan-only"),
        pytest.param([np.inf, -np.inf, np.inf], None, 4.5, 3, id="inf-only"),
        pytest.param([2.0, np.nan, np.inf], 2.0, 3.0, 2, id="mixed"),
        pytest.param([0.0, 0.0, 0.0], 0.0, 4.5, 0, id="zero"),
        pytest.param([1.0, 2.0, 3.0], 3.0, 4.5, 0, id="ordinary"),
    ],
)
def test_rdc_panel_uses_finite_limits(values, maximum, upper, unresolved) -> None:
    from matplotlib.figure import Figure

    from fmriqc.analysis import WeisskoffCurve
    from fmriqc_report.panels.timeseries import plot_rdc

    widths = np.arange(1.0, 4.0)
    rdc = np.array(values)
    wk = WeisskoffCurve(roi_sizes=widths, cv=rdc, cv_ideal=widths, rdc=rdc)
    ax = Figure().add_subplot(111)
    plot_rdc(ax, wk)

    assert ax.get_ylim() == (0.0, upper)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), rdc)
    np.testing.assert_array_equal(ax.lines[1].get_ydata(), widths)
    if maximum is None:
        assert len(ax.lines) == 2
    else:
        assert len(ax.lines) == 3
        np.testing.assert_array_equal(ax.lines[2].get_ydata(), [maximum, maximum])
    assert [t.get_text() for t in ax.texts] == (
        [f"{unresolved}/3 points unresolved"] if unresolved else []
    )


@pytest.mark.parametrize("failed", [0, 1, 38])
def test_motion_panel_marks_unresolved_frames(artifact, failed) -> None:
    from matplotlib.figure import Figure

    from fmriqc_report.panels.timeseries import plot_motion

    translation = np.zeros_like(artifact.curves.translation)
    translation[:failed] = np.nan
    curves = replace(
        artifact.curves,
        translation=translation,
        scale_pct=np.zeros_like(artifact.curves.scale_pct),
        shear_pct=np.zeros_like(artifact.curves.shear_pct),
    )
    ax = Figure().add_subplot(111)
    plot_motion(ax, curves)
    assert [t.get_text() for t in ax.texts] == (
        [f"{failed}/38 frames unresolved"] if failed else []
    )


def test_outlier_panel_shows_measured_percentages_without_a_chance_line(
    artifact,
) -> None:
    from matplotlib.figure import Figure

    from fmriqc_report.panels.timeseries import plot_outliers

    fractions = np.linspace(0.0, 0.02, artifact.curves.time.size)
    curves = replace(artifact.curves, outlier_fraction=fractions)
    ax = Figure().add_subplot(111)
    plot_outliers(ax, curves)

    assert len(ax.lines) == 1
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), curves.time)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), 100.0 * fractions)
    assert ax.get_legend() is None
    assert ax.get_ylabel() == "outliers (%)"


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
    from fmriqc_report.formats.reportlab import packet

    pdf = tmp_path / "existing.pdf"
    pdf.write_bytes(b"existing report")

    def fail_render(*args, **kwargs) -> int:
        raise RuntimeError("injected render failure")

    monkeypatch.setattr(packet, "_render_block", fail_render)
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
        omitted=[("run-2.qa.nc", "unreadable")],
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


@pytest.mark.parametrize("page_size", [(612.0, 792.0), (595.28, 841.89)])
def test_combined_warnings_still_render_one_dashboard_page(
    tmp_path, artifact, page_size
) -> None:
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
    )
    pdf = tmp_path / "warnings.pdf"
    assert (
        report.write_report(
            [("scan", artifact)],
            pdf,
            theme=report.Theme(page_size=page_size, footer="Physics"),
        )
        == 1
    )
    assert pdf.read_bytes().startswith(b"%PDF")
