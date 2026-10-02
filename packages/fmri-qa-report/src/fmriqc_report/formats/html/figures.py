"""Self-contained SVG figures for one rendered QA run.

``render_figures`` consumes a completed :class:`fmriqc.analysis.QAArtifact` and
renders the fixed image and stability figure set as standalone SVG documents
in memory: a run page embeds every one as a ``data:`` URI, so nothing here
ever writes a figure to disk. Rendering only draws values already present in
the artifact; it neither loads inputs nor recomputes measurements.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

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

__all__ = [
    "FIGURE_ASSETS",
    "FigureAsset",
    "RenderedFigure",
    "render_figures",
]


_PLOT_FIGSIZE = (6.4, 4.0)
_SVG_HASHSALT = "fmriqc-report"


@dataclass(frozen=True, slots=True)
class FigureAsset:
    """One fixed figure's identity, caption text, and the report section it fills."""

    name: str
    title: str
    description: str
    section: Literal["image", "stability"]


@dataclass(frozen=True, slots=True)
class RenderedFigure:
    """One figure's identity together with its complete standalone SVG document."""

    asset: FigureAsset
    svg: bytes


# The stable figure inventory in render order; each asset names its own section.
# Keeping this vocabulary at module scope means the HTML composer can use it
# without duplicating its fourteen figure identities.
FIGURE_ASSETS: tuple[FigureAsset, ...] = (
    FigureAsset(
        name="signal",
        title="Signal",
        description="Mean phantom signal with the phantom outline and summary ROI.",
        section="image",
    ),
    FigureAsset(
        name="sfnr",
        title="SFNR",
        description="Voxelwise signal-to-fluctuation-noise ratio with the summary ROI.",
        section="image",
    ),
    FigureAsset(
        name="fluctuation_noise",
        title="Fluctuation noise",
        description=(
            "Log-scaled temporal fluctuation-noise image with phantom and ROI overlays."
        ),
        section="image",
    ),
    FigureAsset(
        name="static_noise",
        title="Static noise",
        description="Odd-even static-noise image with the summary ROI.",
        section="image",
    ),
    FigureAsset(
        name="ghost_regions",
        title="N/2 ghost regions",
        description=(
            "Mean image with the phase-encode and readout ghost sampling regions."
        ),
        section="image",
    ),
    FigureAsset(
        name="weisskoff",
        title="Weisskoff curve",
        description=(
            "Measured coefficient of variation by ROI width against the ideal "
            "reference."
        ),
        section="stability",
    ),
    FigureAsset(
        name="rdc",
        title="Decorrelation factor by ROI width",
        description=(
            "Measured decorrelation factor by ROI width against the ideal reference."
        ),
        section="stability",
    ),
    FigureAsset(
        name="roi_signal",
        title="ROI mean signal",
        description="ROI mean signal over time with its fitted trend.",
        section="stability",
    ),
    FigureAsset(
        name="roi_residual",
        title="ROI residual",
        description="Detrended ROI mean residual over time.",
        section="stability",
    ),
    FigureAsset(
        name="spectrum",
        title="Residual spectrum",
        description="Magnitude spectrum of the detrended ROI residual.",
        section="stability",
    ),
    FigureAsset(
        name="outliers",
        title="Outlier fraction",
        description="Per-volume fraction of outlier voxels over time.",
        section="stability",
    ),
    FigureAsset(
        name="motion",
        title="In-plane motion",
        description="Registration translation and strain estimates over time.",
        section="stability",
    ),
    FigureAsset(
        name="center_of_mass",
        title="Whole-slice center of mass",
        description="Whole-slice center-of-mass deviation over time.",
        section="stability",
    ),
    FigureAsset(
        name="psf",
        title="Directional point-spread function",
        description="Empirical and Gaussian directional point-spread profiles.",
        section="stability",
    ),
)


def _build_figures(artifact: QAArtifact) -> list[Figure]:
    """Build the fourteen figures in ``FIGURE_ASSETS`` order."""
    figures = list(panel_figs(artifact))

    curves, measurements = artifact.curves, artifact.measurements
    draws: tuple[Callable[[Axes], object], ...] = (
        lambda ax: plot_weisskoff(ax, curves.weisskoff, measurements.rdc),
        lambda ax: plot_rdc(ax, curves.weisskoff),
        lambda ax: plot_signal(ax, curves),
        lambda ax: plot_residual(ax, curves, tc_outlier=measurements.tc_outlier),
        lambda ax: plot_spectrum(ax, curves, spec_outlier=measurements.spec_outlier),
        lambda ax: plot_outliers(ax, curves),
        lambda ax: plot_motion(ax, curves),
        lambda ax: plot_com(ax, curves),
        lambda ax: plot_psf(ax, curves.psf),
    )
    figures.extend(plot_fig(draw, _PLOT_FIGSIZE) for draw in draws)
    return figures


def render_figures(
    artifact: QAArtifact, *, theme: Theme = DEFAULT_THEME
) -> tuple[RenderedFigure, ...]:
    """Render the fixed inventory as self-contained SVG documents, in order.

    Rendering happens inside a local matplotlib ``rc_context``; this driver
    neither selects a backend nor uses pyplot. Figures are built with the object
    API, so nothing global holds them and they are freed with their references.
    """
    with matplotlib.rc_context(
        {
            **theme.rc_params(),
            "svg.image_inline": True,
            "svg.hashsalt": _SVG_HASHSALT,
        }
    ):
        figures = _build_figures(artifact)
        rendered = []
        for asset, figure in zip(FIGURE_ASSETS, figures, strict=True):
            buffer = io.BytesIO()
            figure.savefig(buffer, format="svg", metadata={"Date": None})
            rendered.append(RenderedFigure(asset, buffer.getvalue()))
    return tuple(rendered)
