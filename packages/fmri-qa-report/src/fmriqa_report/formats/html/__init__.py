"""Offline, self-contained HTML report pages."""

from .figures import FIGURE_ASSETS, FigureAsset, RenderedFigure, render_figures
from .run import render_run_page

__all__ = [
    "FIGURE_ASSETS",
    "FigureAsset",
    "RenderedFigure",
    "render_figures",
    "render_run_page",
]
