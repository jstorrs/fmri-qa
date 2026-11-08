"""SVG figures rendered for the offline static HTML report."""

from dataclasses import replace
from xml.etree import ElementTree

import matplotlib
import numpy as np
import pytest

from fmriqa_report.formats.html import figures


def _hrefs_bytes(svg: bytes) -> list[str]:
    root = ElementTree.fromstring(svg)  # noqa: S314
    return [
        value
        for element in root.iter()
        for name, value in element.attrib.items()
        if name.endswith("href")
    ]


@pytest.fixture(scope="module")
def rendered(analysis):
    """One real rendering of the fixed figure inventory, reused across tests."""
    return figures.render_figures(analysis)


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


def test_render_figures_renders_unknown_ghost_and_unresolved_values(analysis) -> None:
    curves = analysis.curves
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
        analysis,
        images=replace(analysis.images, ghost=None),
        curves=unresolved,
        measurements=replace(analysis.measurements, rdc=float("nan")),
    )

    rendered = figures.render_figures(changed)

    assert all(len(item.svg) > 0 for item in rendered)


def test_render_figures_is_byte_reproducible(analysis) -> None:
    first = figures.render_figures(analysis)
    second = figures.render_figures(analysis)

    assert tuple(item.svg for item in first) == tuple(item.svg for item in second)


def test_render_figures_keeps_matplotlib_configuration_local(analysis) -> None:
    before_backend = matplotlib.get_backend()
    before_rc = matplotlib.rcParams.copy()

    figures.render_figures(analysis)

    assert matplotlib.get_backend() == before_backend
    assert matplotlib.rcParams == before_rc


def test_render_figures_forces_inline_images_without_leaking_configuration(
    analysis,
) -> None:
    with matplotlib.rc_context({"svg.image_inline": False}):
        rendered = figures.render_figures(analysis)
        assert matplotlib.rcParams["svg.image_inline"] is False

    assert all(
        any(href.startswith("data:image/") for href in _hrefs_bytes(item.svg))
        for item in rendered[:5]
    )


def test_a_theme_font_family_reaches_the_rc_params() -> None:
    from fmriqa_report.theme import Theme

    assert "font.family" not in Theme().rc_params()
    assert Theme(panel_font_family="serif").rc_params()["font.family"] == "serif"
