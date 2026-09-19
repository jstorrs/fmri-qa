"""HTML-report assets built from format-agnostic report content.

This package currently writes the per-run SVG figures that a later HTML page
composer will reference.  It deliberately does not import the PDF driver.
"""

from .figures import FIGURE_ASSETS, FigureAsset, write_figures

__all__ = ["FIGURE_ASSETS", "FigureAsset", "write_figures"]
