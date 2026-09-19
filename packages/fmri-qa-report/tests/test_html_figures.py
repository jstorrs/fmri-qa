"""SVG assets written for the future static HTML report."""

from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import matplotlib
import numpy as np
import pytest
from matplotlib.figure import Figure

from fmriqc_report.formats.html import figures
from fmriqc_report.panels.images import panel_figs
from fmriqc_report.panels.timeseries import plot_fig


def _hrefs(svg: Path) -> list[str]:
    # The test parses only SVG files this writer just created, never user input.
    root = ElementTree.parse(svg).getroot()  # noqa: S314
    return [
        value
        for element in root.iter()
        for name, value in element.attrib.items()
        if name.endswith("href")
    ]


def test_write_figures_writes_the_complete_valid_svg_inventory(
    tmp_path, artifact
) -> None:
    assets = figures.write_figures(artifact, tmp_path)
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
    assert tuple(asset.name for asset in assets) == expected_names
    assert len(assets) == 14
    image_figures = panel_figs(artifact)
    for asset in assets:
        assert asset.path == tmp_path / f"{asset.name}.svg"
        assert asset.path.is_file()
        assert all(
            href.startswith(("#", "data:image/", "http://www.w3.org/"))
            for href in _hrefs(asset.path)
        )
    try:
        for asset, figure in zip(assets[:5], image_figures, strict=True):
            root = ElementTree.parse(asset.path).getroot()  # noqa: S314
            *_, width, height = (
                float(value) for value in root.attrib["viewBox"].split()
            )
            assert (width, height) == pytest.approx(
                (72 * figure.get_figwidth(), 72 * figure.get_figheight())
            )
    finally:
        for figure in image_figures:
            figure.clear()


def test_write_figures_renders_unknown_ghost_and_unresolved_values(
    tmp_path, artifact
) -> None:
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

    assets = figures.write_figures(changed, tmp_path)

    assert all(
        asset.path.is_file() and asset.path.stat().st_size > 0 for asset in assets
    )


def test_write_figures_keeps_matplotlib_configuration_local(tmp_path, artifact) -> None:
    before_backend = matplotlib.get_backend()
    before_rc = matplotlib.rcParams.copy()

    figures.write_figures(artifact, tmp_path)

    assert matplotlib.get_backend() == before_backend
    assert matplotlib.rcParams == before_rc


def test_write_figures_forces_inline_images_without_leaking_configuration(
    tmp_path, artifact
) -> None:
    with matplotlib.rc_context({"svg.image_inline": False}):
        assets = figures.write_figures(artifact, tmp_path)
        assert matplotlib.rcParams["svg.image_inline"] is False

    assert not list(tmp_path.glob("*.png"))
    assert all(
        any(href.startswith("data:image/") for href in _hrefs(asset.path))
        for asset in assets[:5]
    )


def test_write_figures_clears_every_figure_when_saving_fails(
    tmp_path, artifact, monkeypatch
) -> None:
    built = [Figure().add_subplot(111).figure for _ in figures.FIGURE_ASSETS]

    monkeypatch.setattr(figures, "_build_figures", lambda _artifact: built)

    def fail_save(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(figures, "_save_svg", fail_save)

    with pytest.raises(OSError, match="disk full"):
        figures.write_figures(artifact, tmp_path)

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
