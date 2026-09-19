"""Self-contained SVG figure assets for one rendered QA run.

``write_figures`` consumes a completed :class:`fmriqc.analysis.QAArtifact` and
writes the fixed image and stability figure set for a future HTML report.  It
only draws values already present in the artifact; it neither loads inputs nor
recomputes measurements.

If a write raises, files successfully written before the failure remain in
``output_dir`` and the failed target may be partial.  The later site publisher
owns staging and cleanup, while this small asset writer makes no attempt to
remove pre-existing or partial output.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from fmriqc.analysis import QAArtifact

from ...panels.images import panel_figs
from ...panels.timeseries import (
    plot_com,
    plot_fig,
    plot_motion,
    plot_outliers,
    plot_psf,
    plot_rdc,
    plot_residual,
    plot_signal,
    plot_spectrum,
    plot_weisskoff,
)
from ...theme import DEFAULT_THEME, Theme

__all__ = ["FIGURE_ASSETS", "FigureAsset", "write_figures"]


_PLOT_FIGSIZE = (6.4, 4.0)
_PLOT_FONT_SIZE = 11


@dataclass(frozen=True, slots=True)
class FigureAsset:
    """One fixed SVG asset and the text a future HTML renderer can expose."""

    name: str
    title: str
    description: str
    path: Path


def _assets(output_dir: Path) -> tuple[FigureAsset, ...]:
    """Return the stable figure inventory rooted at ``output_dir``."""
    records = (
        (
            "signal",
            "Signal",
            "Mean phantom signal with the phantom outline and summary ROI.",
        ),
        (
            "sfnr",
            "SFNR",
            "Voxelwise signal-to-fluctuation-noise ratio with the summary ROI.",
        ),
        (
            "fluctuation_noise",
            "Fluctuation noise",
            (
                "Log-scaled temporal fluctuation-noise image with phantom and ROI "
                "overlays."
            ),
        ),
        (
            "static_noise",
            "Static noise",
            "Odd-even static-noise image with the summary ROI.",
        ),
        (
            "ghost_regions",
            "N/2 ghost regions",
            "Mean image with the phase-encode and readout ghost sampling regions.",
        ),
        (
            "weisskoff",
            "Weisskoff curve",
            (
                "Measured coefficient of variation by ROI width against the ideal "
                "reference."
            ),
        ),
        (
            "rdc",
            "Decorrelation factor by ROI width",
            ("Measured decorrelation factor by ROI width against the ideal reference."),
        ),
        (
            "roi_signal",
            "ROI mean signal",
            "ROI mean signal over time with its fitted trend.",
        ),
        (
            "roi_residual",
            "ROI residual",
            "Detrended ROI mean residual over time.",
        ),
        (
            "spectrum",
            "Residual spectrum",
            "Magnitude spectrum of the detrended ROI residual.",
        ),
        (
            "outliers",
            "Outlier fraction",
            "Per-volume fraction of outlier voxels over time.",
        ),
        (
            "motion",
            "In-plane motion",
            "Registration translation and strain estimates over time.",
        ),
        (
            "center_of_mass",
            "Whole-slice center of mass",
            "Whole-slice center-of-mass deviation over time.",
        ),
        (
            "psf",
            "Directional point-spread function",
            ("Empirical and Gaussian directional point-spread profiles."),
        ),
    )
    return tuple(
        FigureAsset(name, title, description, output_dir / f"{name}.svg")
        for name, title, description in records
    )


# The same fixed inventory without a run-specific destination.  Keeping names,
# titles, and descriptions here means the HTML composer can use this vocabulary
# without duplicating its fourteen figure identities.
FIGURE_ASSETS = _assets(Path())


def _build_figures(artifact: QAArtifact) -> list[Figure]:
    """Build the fourteen figures in ``FIGURE_ASSETS`` order."""
    figures = list(panel_figs(artifact))

    curves, measurements = artifact.curves, artifact.measurements
    draws: tuple[Callable[[Axes], object], ...] = (
        lambda ax: plot_weisskoff(
            ax, curves.weisskoff, measurements.rdc, fs=_PLOT_FONT_SIZE
        ),
        lambda ax: plot_rdc(ax, curves.weisskoff, fs=_PLOT_FONT_SIZE),
        lambda ax: plot_signal(ax, curves, fs=_PLOT_FONT_SIZE),
        lambda ax: plot_residual(
            ax,
            curves,
            fs=_PLOT_FONT_SIZE,
            tc_outlier=measurements.tc_outlier,
        ),
        lambda ax: plot_spectrum(
            ax,
            curves,
            fs=_PLOT_FONT_SIZE,
            spec_outlier=measurements.spec_outlier,
        ),
        lambda ax: plot_outliers(ax, curves, fs=_PLOT_FONT_SIZE),
        lambda ax: plot_motion(ax, curves, fs=_PLOT_FONT_SIZE),
        lambda ax: plot_com(ax, curves, fs=_PLOT_FONT_SIZE),
        lambda ax: plot_psf(ax, curves.psf, fs=_PLOT_FONT_SIZE),
    )
    try:
        figures.extend(plot_fig(draw, _PLOT_FIGSIZE) for draw in draws)
    except Exception:
        for figure in figures:
            figure.clear()
        raise
    return figures


def _save_svg(figure: Figure, path: Path) -> None:
    """Save one figure as an SVG without a creation timestamp."""
    figure.savefig(path, format="svg", metadata={"Date": None})


def write_figures(
    artifact: QAArtifact,
    output_dir: Path | str,
    *,
    theme: Theme = DEFAULT_THEME,
) -> tuple[FigureAsset, ...]:
    """Write the fixed self-contained SVG inventory for ``artifact``.

    The returned assets have absolute or caller-relative paths rooted at the
    supplied ``output_dir``.  Rendering happens inside a local matplotlib
    ``rc_context`` and figures are cleared in a ``finally`` block, including
    when a save fails; this driver neither selects a backend nor uses pyplot.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    assets = _assets(destination)
    rc_params = {**theme.rc_params(), "svg.image_inline": True}
    with matplotlib.rc_context(rc_params):
        figures = _build_figures(artifact)
        try:
            for asset, figure in zip(assets, figures, strict=True):
                _save_svg(figure, asset.path)
        finally:
            for figure in figures:
                figure.clear()
    return assets
