"""SVG figures rendered for the offline static HTML report."""

from dataclasses import replace
from xml.etree import ElementTree

import matplotlib
import numpy as np
import pytest
from matplotlib.figure import Figure

from fmriqc_report.formats.html import figures
from fmriqc_report.panels.timeseries import plot_fig


def _hrefs_bytes(svg: bytes) -> list[str]:
    root = ElementTree.fromstring(svg)  # noqa: S314
    return [
        value
        for element in root.iter()
        for name, value in element.attrib.items()
        if name.endswith("href")
    ]


@pytest.fixture(scope="module")
def rendered(artifact):
    """One real rendering of the fixed figure inventory, reused across tests."""
    return figures.render_figures(artifact)


def test_render_figures_returns_standalone_svg_documents(rendered) -> None:
    expected_names = (
        "signal",
        "sfnr",
        "fluctuation_noise",
        "static_noise",
        "ghost_regions",
        "weisskoff",
        "rdc",
        "roi_signal",
        "roi_residual",
        "spectrum",
        "outliers",
        "motion",
        "center_of_mass",
        "psf",
    )
    assert tuple(asset.name for asset in figures.FIGURE_ASSETS) == expected_names
    assert len(rendered) == 14
    assert tuple(item.asset for item in rendered) == figures.FIGURE_ASSETS
    for item in rendered:
        assert item.svg.startswith(b"<?xml")
        ElementTree.fromstring(item.svg)  # noqa: S314
        assert all(
            href.startswith(("#", "data:image/", "http://www.w3.org/"))
            for href in _hrefs_bytes(item.svg)
        )


def test_figure_assets_pin_their_report_sections() -> None:
    """The five image panels lead; every plot after them is a stability plot."""
    sections = {asset.name: asset.section for asset in figures.FIGURE_ASSETS}
    assert [name for name, section in sections.items() if section == "image"] == [
        "signal",
        "sfnr",
        "fluctuation_noise",
        "static_noise",
        "ghost_regions",
    ]
    assert [name for name, section in sections.items() if section == "stability"] == [
        "weisskoff",
        "rdc",
        "roi_signal",
        "roi_residual",
        "spectrum",
        "outliers",
        "motion",
        "center_of_mass",
        "psf",
    ]


def test_render_figures_renders_unknown_ghost_and_unresolved_values(artifact) -> None:
    curves = artifact.curves
    unresolved = replace(
        curves,
        translation=np.full_like(curves.translation, np.nan),
        scale_pct=np.full_like(curves.scale_pct, np.nan),
        shear_pct=np.full_like(curves.shear_pct, np.nan),
        weisskoff=replace(
            curves.weisskoff,
            rdc=np.full_like(curves.weisskoff.rdc, np.nan),
        ),
    )
    changed = replace(
        artifact,
        images=replace(artifact.images, ghost=None),
        curves=unresolved,
        measurements=replace(artifact.measurements, rdc=float("nan")),
    )

    rendered = figures.render_figures(changed)

    assert all(len(item.svg) > 0 for item in rendered)


def test_render_figures_is_byte_reproducible(artifact) -> None:
    first = figures.render_figures(artifact)
    second = figures.render_figures(artifact)

    assert tuple(item.svg for item in first) == tuple(item.svg for item in second)


def test_render_figures_keeps_matplotlib_configuration_local(artifact) -> None:
    before_backend = matplotlib.get_backend()
    before_rc = matplotlib.rcParams.copy()

    figures.render_figures(artifact)

    assert matplotlib.get_backend() == before_backend
    assert matplotlib.rcParams == before_rc


def test_render_figures_forces_inline_images_without_leaking_configuration(
    artifact,
) -> None:
    with matplotlib.rc_context({"svg.image_inline": False}):
        rendered = figures.render_figures(artifact)
        assert matplotlib.rcParams["svg.image_inline"] is False

    assert all(
        any(href.startswith("data:image/") for href in _hrefs_bytes(item.svg))
        for item in rendered[:5]
    )


def test_render_figures_clears_every_figure_when_saving_fails(
    artifact, monkeypatch
) -> None:
    built = [Figure().add_subplot(111).figure for _ in figures.FIGURE_ASSETS]

    monkeypatch.setattr(figures, "_build_figures", lambda _artifact: built)

    def fail_save(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(figures, "_save_svg", fail_save)

    with pytest.raises(OSError, match="disk full"):
        figures.render_figures(artifact)

    assert all(not figure.axes for figure in built)


def test_build_figures_clears_completed_figures_when_a_later_plot_fails(
    artifact, monkeypatch
) -> None:
    image = Figure()
    image.add_subplot(111)
    first_plot = Figure()
    first_plot.add_subplot(111)
    calls = 0

    def build_plot(*_args, **_kwargs) -> Figure:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_plot
        raise RuntimeError("plot failed")

    monkeypatch.setattr(figures, "panel_figs", lambda _artifact: [image])
    monkeypatch.setattr(figures, "plot_fig", build_plot)

    with pytest.raises(RuntimeError, match="plot failed"):
        figures._build_figures(artifact)

    assert not image.axes
    assert not first_plot.axes


def test_plot_fig_clears_its_figure_when_its_callback_fails() -> None:
    captured: list[Figure] = []

    def fail_draw(ax) -> None:
        captured.append(ax.figure)
        raise RuntimeError("draw failed")

    with pytest.raises(RuntimeError, match="draw failed"):
        plot_fig(fail_draw, (1.0, 1.0))

    assert len(captured) == 1
    assert not captured[0].axes


def test_a_theme_font_family_reaches_the_rc_params() -> None:
    from fmriqc_report.theme import Theme

    assert "font.family" not in Theme().rc_params()
    assert Theme(panel_font_family="serif").rc_params()["font.family"] == "serif"
